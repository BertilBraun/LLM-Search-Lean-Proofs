"""Hypothesis names proposed by a larger model behind an OpenAI-compatible endpoint (e.g. vLLM on the node)."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

from lean_search.data_rewrite.naming import (
    HypothesisNamer,
    NameSource,
    NamingConfig,
    NamingRequest,
    RuleBasedNamer,
)
from lean_search.policy.client import ChatMessage, PolicyClient

NAMER_SYSTEM_PROMPT = (
    "You are a Lean 4 and Mathlib expert. You give hypotheses short, descriptive names in Mathlib style: snake_case, "
    "starting with h, saying what the hypothesis states, e.g. hx_pos for 0 < x, hab for a ≤ b, h_sum for "
    "a + b + c = 3, hf for a definition of f, hp_prime for Nat.Prime p."
)
# Names starting with `h` are the ones a proposal could clash with; listing every identifier would bury them.
MAX_LISTED_TAKEN_NAMES = 40


@dataclass(frozen=True)
class ModelNamerConfig:
    model: str = ""
    base_url: str = "http://127.0.0.1:8000/v1"
    max_tokens: int = 512
    temperature: float = 0.0
    requests_in_flight: int = 64
    request_timeout_seconds: float = 600.0
    enable_thinking: bool = False


def naming_messages(request: NamingRequest, config: NamingConfig) -> list[ChatMessage]:
    hypotheses = "\n".join(f"- {hypothesis.name} : {hypothesis.type}" for hypothesis in request.hypotheses)
    taken = sorted(name for name in request.taken if name.startswith("h"))[:MAX_LISTED_TAKEN_NAMES]
    rules = (
        f"Each name must be a valid Lean identifier of ASCII letters, digits and underscores, at most "
        f"{config.max_name_length} characters, different from the others and from these names in use: "
        f"{', '.join(taken) or 'none'}. Do not number the names (no h1, h₂)."
    )
    user = (
        f"Theorem:\n```lean\n{request.context.strip()}\n```\n\nName these hypotheses:\n{hypotheses}\n\n{rules}\n\n"
        "Reply with a JSON object that maps each old name to its new name, and nothing else."
    )
    return [ChatMessage("system", NAMER_SYSTEM_PROMPT), ChatMessage("user", user)]


def parse_names(reply: str, request: NamingRequest) -> tuple[str, ...]:
    """The proposed name per hypothesis, "" where the reply has none (the model's output is not trusted)."""
    start, end = reply.find("{"), reply.rfind("}")
    try:
        parsed = json.loads(reply[start : end + 1]) if 0 <= start < end else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    names = [parsed.get(hypothesis.name, "") for hypothesis in request.hypotheses]
    return tuple(name.strip() if isinstance(name, str) else "" for name in names)


class ModelNamer:
    source = NameSource.MODEL

    def __init__(self, client: PolicyClient, config: ModelNamerConfig, naming: NamingConfig) -> None:
        self.client = client
        self.config = config
        self.naming = naming

    async def propose(self, requests: Sequence[NamingRequest]) -> list[tuple[str, ...]]:
        return list(await asyncio.gather(*(self._propose_one(request) for request in requests)))

    async def _propose_one(self, request: NamingRequest) -> tuple[str, ...]:
        try:
            generation = await self.client.generate_chat(
                naming_messages(request, self.naming),
                enable_thinking=self.config.enable_thinking,
                sample_count=1,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
        except httpx.HTTPStatusError:
            # A request the server refuses (e.g. a prompt over its context) falls back to rule-based names.
            return ("",) * len(request.hypotheses)
        return parse_names(generation.samples[0].text, request)


@contextlib.asynccontextmanager
async def open_namer(model: ModelNamerConfig | None, naming: NamingConfig) -> AsyncIterator[HypothesisNamer]:
    """The model namer when a model is configured, else the rule-based one."""
    if model is None or not model.model:
        yield RuleBasedNamer(naming)
        return
    async with PolicyClient(
        model.base_url, model.model, model.request_timeout_seconds, model.requests_in_flight
    ) as client:
        yield ModelNamer(client, model, naming)
