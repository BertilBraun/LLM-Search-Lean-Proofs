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
from lean_search.policy.client import Generation, PolicyClient, Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.prompts import (
    FENCE,
    ChatTemplate,
    ParsedSamples,
    ParseFailure,
    forced_answer_prompt,
    forced_sample,
    parse_samples,
    render_prompt,
    stop_sequences,
    truncated_in_thinking,
)
from lean_search.retrieval.provider import LemmaProvider, load_lemma_provider
from lean_search.retrieval.statistics import LemmaStatistics
from lean_search.search.expanders import Candidate, CandidateBatch, CandidateBatches, SearchContext
from lean_search.search.tree import Node, StepSource

MINIMUM_GENERATED_TOKENS = 32
# Room for the closing of the thoughts and the opened block, and for re-tokenizing the thoughts as prompt text.
FORCED_ANSWER_PROMPT_SLACK = 64


class PolicyTokenizer(ChatTemplate, Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True)
class ForcedAnswers:
    """The samples of a request whose answers were forced, and what the forcing request cost."""

    sample_indices: frozenset[int] = frozenset()
    prompt_tokens: int = 0
    generated_tokens: int = 0


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
    # Tokens of requests whose samples all failed to parse; the search charges them like every other request's.
    unattributed_generated_tokens: int = 0
    request_seconds: float = 0.0
    # From the first request's start to the latest response, for samples per second under the search's load.
    window_seconds: float = 0.0
    lemmas: LemmaStatistics | None = None
    # Budget forcing: samples cut off inside their thoughts that were continued with closed thoughts, the forced
    # samples that gave a usable block, and the forcing requests' tokens (also counted in the totals above).
    forced_samples: int = 0
    forced_blocks: int = 0
    forced_prompt_tokens: int = 0
    forced_generated_tokens: int = 0

    def record(
        self, generation: Generation, parsed: ParsedSamples, seconds: float, forced: ForcedAnswers | None = None
    ) -> None:
        forced = forced or ForcedAnswers()
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
            self.unattributed_generated_tokens += generation.completion_token_count + forced.generated_tokens
        self.prompt_tokens += generation.prompt_token_count + forced.prompt_tokens
        self.cached_prompt_tokens += generation.cached_prompt_token_count
        self.generated_tokens += generation.completion_token_count + forced.generated_tokens
        self.request_seconds += seconds
        self.forced_samples += len(forced.sample_indices)
        self.forced_blocks += sum(candidate.forced_sample_count for candidate in parsed.candidates)
        self.forced_prompt_tokens += forced.prompt_tokens
        self.forced_generated_tokens += forced.generated_tokens


def candidate_batch(
    parsed: ParsedSamples, generation: Generation, forced: ForcedAnswers | None = None
) -> CandidateBatch:
    """The whole request's cost, failed samples and forcing included; each candidate logs its own samples."""
    forced = forced or ForcedAnswers()
    candidates = tuple(
        Candidate(
            candidate.tactic_block,
            StepSource.POLICY,
            log_probability=candidate.log_probability,
            prompt_tokens=generation.prompt_token_count,
            generated_tokens=candidate.generated_tokens,
            forced=candidate.forced,
        )
        for candidate in parsed.candidates
    )
    return CandidateBatch(
        candidates,
        generation.prompt_token_count + forced.prompt_tokens,
        generation.completion_token_count + forced.generated_tokens,
    )


class PolicyExpander:
    def __init__(
        self,
        config: PolicyConfig,
        tokenizer: PolicyTokenizer,
        clients: Sequence[PolicyClient],
        max_model_length: int,
        forbidden_steps: Sequence[str] = (),
        lemma_provider: LemmaProvider | None = None,
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self.max_model_length = max_model_length
        self.forbidden_tokens = FORBIDDEN_TOKENS | frozenset(forbidden_steps)
        self.lemma_provider = lemma_provider
        self.statistics = PolicyStatistics(lemmas=lemma_provider.statistics if lemma_provider else None)
        self._clients = itertools.cycle(clients)
        self._first_request_started: float | None = None

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        lemmas = await self.lemma_provider.lemma_lines(node.state, context.repl) if self.lemma_provider else ()
        prompt = render_prompt(
            self.tokenizer,
            node.goals,
            lemmas,
            few_shot=self.config.few_shot,
            thinking=self.config.thinking,
            thinking_instruction=self.config.thinking_instruction,
        )
        prompt_tokens = len(self.tokenizer.encode(prompt, add_special_tokens=False))
        max_tokens = min(self.config.max_tokens, self.max_model_length - prompt_tokens)
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            self.statistics.prompts_too_long += 1
            return
        generation, seconds = await self._generate(prompt, max_tokens)
        samples, forced, forcing_seconds = await self.force_answers(prompt, prompt_tokens, generation.samples)
        parsed = parse_samples(
            samples,
            thinking=self.config.thinking,
            forbidden_tokens=self.forbidden_tokens,
            forced_indices=forced.sample_indices,
        )
        self.statistics.record(generation, parsed, seconds + forcing_seconds, forced)
        yield candidate_batch(parsed, generation, forced)

    async def force_answers(
        self, prompt: str, prompt_tokens: int, samples: Sequence[Sample]
    ) -> tuple[list[Sample], ForcedAnswers, float]:
        """Budget forcing: one request continues every sample cut off inside its thoughts after closing them."""
        truncated = [index for index, sample in enumerate(samples) if truncated_in_thinking(sample)]
        if not (self.config.thinking and self.config.force_answer_on_truncation and truncated):
            return list(samples), ForcedAnswers(), 0.0
        longest = max(samples[index].token_count for index in truncated)
        max_tokens = min(
            self.config.forced_answer_tokens,
            self.max_model_length - prompt_tokens - longest - FORCED_ANSWER_PROMPT_SLACK,
        )
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            return list(samples), ForcedAnswers(), 0.0
        started = time.monotonic()
        continuations = await next(self._clients).generate_each(
            [forced_answer_prompt(prompt, samples[index]) for index in truncated],
            max_tokens=max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            stop=(FENCE,),
            adapter=self.config.adapter,
        )
        forced = list(samples)
        for index, continuation in zip(truncated, continuations.samples, strict=True):
            forced[index] = forced_sample(samples[index], continuation)
        answers = ForcedAnswers(
            frozenset(truncated), continuations.prompt_token_count, continuations.completion_token_count
        )
        return forced, answers, time.monotonic() - started

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
    lemma_provider = await load_lemma_provider(config.retrieval) if config.retrieval.enabled else None
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(server_url, config.model, timeout_seconds=config.request_timeout_seconds)
            )
            for server_url in config.server_urls
        ]
        yield PolicyExpander(config, tokenizer, clients, max_model_length, forbidden_steps, lemma_provider)
