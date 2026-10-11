"""The policy as a search expander: one request with n samples per expansion, parsed into distinct candidates."""

import contextlib
import itertools
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from transformers import AutoTokenizer

from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.policy.client import Generation, PolicyClient
from lean_search.policy.config import PolicyConfig
from lean_search.policy.prompts import (
    ChatTemplate,
    ParsedSamples,
    ParseFailure,
    parse_samples,
    render_prompt,
    stop_sequences,
)
from lean_search.search.expanders import Candidate, CandidateBatches, SearchContext
from lean_search.search.tree import Node, StepSource

MINIMUM_GENERATED_TOKENS = 32


class PolicyTokenizer(ChatTemplate, Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass
class PolicyStatistics:
    requests: int = 0
    samples: int = 0
    candidates: int = 0
    duplicate_samples: int = 0
    truncated_samples: int = 0
    samples_without_block: int = 0
    empty_samples: int = 0
    forbidden_samples: int = 0
    requests_without_candidates: int = 0
    prompts_too_long: int = 0
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    generated_tokens: int = 0
    # Tokens of requests whose samples all failed to parse: no candidate carries them into the search's accounting.
    unattributed_generated_tokens: int = 0
    request_seconds: float = 0.0
    # From the first request's start to the latest response, for samples per second under the search's load.
    window_seconds: float = 0.0

    def record(self, generation: Generation, parsed: ParsedSamples, seconds: float) -> None:
        self.requests += 1
        self.samples += len(generation.samples)
        self.candidates += len(parsed.candidates)
        self.duplicate_samples += parsed.duplicate_samples
        for failure in parsed.failures:
            match failure:
                case ParseFailure.TRUNCATED:
                    self.truncated_samples += 1
                case ParseFailure.NO_BLOCK:
                    self.samples_without_block += 1
                case ParseFailure.EMPTY:
                    self.empty_samples += 1
                case ParseFailure.FORBIDDEN:
                    self.forbidden_samples += 1
        if not parsed.candidates:
            self.requests_without_candidates += 1
            self.unattributed_generated_tokens += generation.completion_token_count
        self.prompt_tokens += generation.prompt_token_count
        self.cached_prompt_tokens += generation.cached_prompt_token_count
        self.generated_tokens += generation.completion_token_count
        self.request_seconds += seconds


def search_candidates(parsed: ParsedSamples, prompt_tokens: int) -> list[Candidate]:
    # The search sums tokens over candidates, so the first one also carries the prompt and the failed samples.
    return [
        Candidate(
            candidate.tactic_block,
            StepSource.POLICY,
            log_probability=candidate.log_probability,
            prompt_tokens=prompt_tokens if index == 0 else 0,
            generated_tokens=candidate.generated_tokens + (parsed.failed_generated_tokens if index == 0 else 0),
        )
        for index, candidate in enumerate(parsed.candidates)
    ]


class PolicyExpander:
    def __init__(
        self,
        config: PolicyConfig,
        tokenizer: PolicyTokenizer,
        clients: Sequence[PolicyClient],
        max_model_length: int,
        forbidden_steps: Sequence[str] = (),
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self.max_model_length = max_model_length
        self.forbidden_tokens = FORBIDDEN_TOKENS | frozenset(forbidden_steps)
        self.statistics = PolicyStatistics()
        self._clients = itertools.cycle(clients)
        self._first_request_started: float | None = None

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        prompt = render_prompt(self.tokenizer, node.goals, few_shot=self.config.few_shot, thinking=self.config.thinking)
        prompt_tokens = len(self.tokenizer.encode(prompt, add_special_tokens=False))
        max_tokens = min(self.config.max_tokens, self.max_model_length - prompt_tokens)
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            self.statistics.prompts_too_long += 1
            return
        generation, seconds = await self._generate(prompt, max_tokens)
        parsed = parse_samples(
            generation.samples, thinking=self.config.thinking, forbidden_tokens=self.forbidden_tokens
        )
        self.statistics.record(generation, parsed, seconds)
        candidates = search_candidates(parsed, generation.prompt_token_count)
        if candidates:
            yield candidates

    async def _generate(self, prompt: str, max_tokens: int) -> tuple[Generation, float]:
        started = time.monotonic()
        if self._first_request_started is None:
            self._first_request_started = started
        generation = await next(self._clients).generate(
            prompt,
            sample_count=self.config.sample_count,
            max_tokens=max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            stop=stop_sequences(self.config.thinking),
            adapter=self.config.adapter,
        )
        finished = time.monotonic()
        self.statistics.window_seconds = finished - self._first_request_started
        return generation, finished - started


def load_tokenizer(name_or_path: str) -> PolicyTokenizer:
    return AutoTokenizer.from_pretrained(name_or_path)


async def served_max_model_length(server_url: str, model: str) -> int:
    async with httpx.AsyncClient(base_url=server_url.rstrip("/"), timeout=30.0) as http:
        response = await http.get("/models")
        response.raise_for_status()
    (served,) = (entry for entry in response.json()["data"] if entry["id"] == model)
    return served["max_model_len"]


@contextlib.asynccontextmanager
async def open_policy_expander(
    config: PolicyConfig, forbidden_steps: Sequence[str] = ()
) -> AsyncIterator[PolicyExpander]:
    tokenizer = load_tokenizer(config.tokenizer)
    max_model_length = min(
        [await served_max_model_length(server_url, config.model) for server_url in config.server_urls]
    )
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(server_url, config.model, timeout_seconds=config.request_timeout_seconds)
            )
            for server_url in config.server_urls
        ]
        yield PolicyExpander(config, tokenizer, clients, max_model_length, forbidden_steps)
