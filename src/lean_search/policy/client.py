import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Self

import httpx

TOKEN_ID_PREFIX = "token_id:"
TRANSPORT_ATTEMPTS = 3
# Timeouts are not retried: a request that ran out its timeout would only run it out again.
RETRIED_TRANSPORT_ERRORS = (httpx.NetworkError, httpx.RemoteProtocolError)


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Sample:
    text: str
    # Sum of the raw (temperature 1, unfiltered) log-probabilities of the generated tokens.
    cumulative_logprob: float
    token_count: int
    finish_reason: str


@dataclass(frozen=True)
class Generation:
    samples: list[Sample]
    prompt_token_count: int
    cached_prompt_token_count: int
    completion_token_count: int


@dataclass(frozen=True)
class NextTokenDistribution:
    logprob_by_token_id: dict[int, float]
    prompt_token_count: int
    cached_prompt_token_count: int


@dataclass(frozen=True)
class NextTokenDistributions:
    # One per prompt, in order; the server reports token counts for the request as a whole.
    logprobs_by_token_id: tuple[dict[int, float], ...]
    prompt_token_count: int
    cached_prompt_token_count: int


class PolicyClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 1800.0, max_connections: int = 512) -> None:
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=30.0),
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
        )
        # Requests beyond the pool size wait here: httpx's own queue costs quadratic CPU in its length.
        self._in_flight = asyncio.Semaphore(max_connections)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def generate(
        self,
        prompt: str,
        *,
        sample_count: int,
        max_tokens: int,
        temperature: float = 1.0,
        top_p: float = 1.0,
        stop: Sequence[str] = (),
        adapter: str | None = None,
        seed: int | None = None,
        ignore_eos: bool = False,
    ) -> Generation:
        body = {
            "prompt": prompt,
            "logprobs": 0,
            **_sampling_fields(sample_count, max_tokens, temperature, top_p, stop, seed, ignore_eos),
        }
        response = await self._post("/completions", body, adapter)
        samples = [
            _sample(choice["text"], choice["logprobs"]["token_logprobs"], choice["finish_reason"])
            for choice in sorted(response["choices"], key=lambda choice: choice["index"])
        ]
        return _generation(samples, response["usage"])

    async def generate_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        enable_thinking: bool,
        sample_count: int,
        max_tokens: int,
        temperature: float = 1.0,
        top_p: float = 1.0,
        stop: Sequence[str] = (),
        adapter: str | None = None,
        seed: int | None = None,
        ignore_eos: bool = False,
    ) -> Generation:
        body = {
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "logprobs": True,
            "top_logprobs": 0,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
            **_sampling_fields(sample_count, max_tokens, temperature, top_p, stop, seed, ignore_eos),
        }
        response = await self._post("/chat/completions", body, adapter)
        samples = [
            _sample(
                choice["message"]["content"] or "",
                [token["logprob"] for token in choice["logprobs"]["content"]],
                choice["finish_reason"],
            )
            for choice in sorted(response["choices"], key=lambda choice: choice["index"])
        ]
        return _generation(samples, response["usage"])

    async def score_next_token(
        self, prompt: str, *, top_k: int = 20, adapter: str | None = None
    ) -> NextTokenDistribution:
        scored = await self.score_next_tokens([prompt], top_k=top_k, adapter=adapter)
        return NextTokenDistribution(
            scored.logprobs_by_token_id[0], scored.prompt_token_count, scored.cached_prompt_token_count
        )

    async def score_next_tokens(
        self, prompts: Sequence[str], *, top_k: int = 20, adapter: str | None = None
    ) -> NextTokenDistributions:
        """Many prompts in one request, which saves the client's per-request overhead (~10 ms of CPU each)."""
        body = {
            "prompt": list(prompts),
            "max_tokens": 1,
            "temperature": 0.0,
            "logprobs": top_k,
            "return_tokens_as_token_ids": True,
        }
        response = await self._post("/completions", body, adapter)
        usage = response["usage"]
        return NextTokenDistributions(
            logprobs_by_token_id=tuple(
                {
                    int(token.removeprefix(TOKEN_ID_PREFIX)): logprob
                    for token, logprob in choice["logprobs"]["top_logprobs"][0].items()
                }
                for choice in sorted(response["choices"], key=lambda choice: choice["index"])
            ),
            prompt_token_count=usage["prompt_tokens"],
            cached_prompt_token_count=_cached_prompt_token_count(usage),
        )

    async def load_adapter(self, name: str, path: str) -> None:
        response = await self._http.post("/load_lora_adapter", json={"lora_name": name, "lora_path": path})
        response.raise_for_status()

    async def unload_adapter(self, name: str) -> None:
        response = await self._http.post("/unload_lora_adapter", json={"lora_name": name})
        response.raise_for_status()

    async def _post(self, path: str, body: dict[str, Any], adapter: str | None) -> dict[str, Any]:
        # Under load vLLM sometimes closes a kept-alive connection mid-request; every request here can be repeated.
        for _ in range(TRANSPORT_ATTEMPTS - 1):
            try:
                return await self._post_once(path, body, adapter)
            except RETRIED_TRANSPORT_ERRORS:
                pass
        return await self._post_once(path, body, adapter)

    async def _post_once(self, path: str, body: dict[str, Any], adapter: str | None) -> dict[str, Any]:
        async with self._in_flight:
            response = await self._http.post(path, json={"model": adapter or self.model, **body})
        response.raise_for_status()
        return response.json()


def _sampling_fields(
    sample_count: int,
    max_tokens: int,
    temperature: float,
    top_p: float,
    stop: Sequence[str],
    seed: int | None,
    ignore_eos: bool,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "n": sample_count,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stop": list(stop),
        "ignore_eos": ignore_eos,
    }
    if seed is not None:
        fields["seed"] = seed
    return fields


def _sample(text: str, token_logprobs: list[float], finish_reason: str) -> Sample:
    return Sample(
        text=text,
        cumulative_logprob=sum(token_logprobs),
        token_count=len(token_logprobs),
        finish_reason=finish_reason,
    )


def _generation(samples: list[Sample], usage: dict[str, Any]) -> Generation:
    return Generation(
        samples=samples,
        prompt_token_count=usage["prompt_tokens"],
        cached_prompt_token_count=_cached_prompt_token_count(usage),
        completion_token_count=usage["completion_tokens"],
    )


def _cached_prompt_token_count(usage: dict[str, Any]) -> int:
    details = usage.get("prompt_tokens_details")
    return details["cached_tokens"] if details else 0
