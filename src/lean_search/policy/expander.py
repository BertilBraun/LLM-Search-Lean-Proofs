"""The policy as a search expander: one request with n samples per expansion, parsed into distinct candidates."""

import contextlib
import dataclasses
import functools
import itertools
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
from transformers import AutoTokenizer

from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.policy.client import Generation, PolicyClient, Sample
from lean_search.policy.config import FeedbackConfig, PolicyConfig
from lean_search.policy.prompts import (
    FENCE,
    ChatTemplate,
    FailedAttempt,
    ParsedSamples,
    ParseFailure,
    answer_opening,
    error_summary,
    forced_answer_prompt,
    forced_sample,
    parse_samples,
    render_prompt,
    shortened,
    stop_sequences,
    truncated_before_answer,
)
from lean_search.retrieval.provider import LemmaProvider, load_lemma_provider
from lean_search.retrieval.statistics import LemmaStatistics
from lean_search.search.expanders import Candidate, CandidateBatch, CandidateBatches, SearchContext
from lean_search.search.texts import GeneratedText, UnparsedSample
from lean_search.search.tree import Edge, EdgeOutcome, FailureKind, Node, NodeStatus, SearchTree, StepSource

MINIMUM_GENERATED_TOKENS = 32
# Room for the closing of the thoughts and the opened block.
FORCED_ANSWER_PROMPT_SLACK = 64
# Failures whose message says what was wrong with the block (not infrastructure, not a missing block).
FEEDBACK_FAILURE_KINDS = frozenset(
    {FailureKind.ERROR, FailureKind.UNKNOWN_IDENTIFIER, FailureKind.HEARTBEAT_TIMEOUT, FailureKind.FORBIDDEN}
)


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
    # Feedback rounds (policy.feedback), also counted in the totals above.
    feedback_requests: int = 0

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
    parsed: ParsedSamples,
    generation: Generation,
    forced: ForcedAnswers | None = None,
    *,
    samples: Sequence[Sample] | None = None,
    prompt: str = "",
    ends_turn_on_stop: bool = True,
    temperature: float | None = None,
    top_p: float | None = None,
    feedback: bool = False,
) -> CandidateBatch:
    """The whole request's cost and every sample's text: candidates with their samples, unparsed samples apart."""
    # A request with stop sequences ends at the fence, not at the end of turn.
    forced = forced or ForcedAnswers()
    samples = generation.samples if samples is None else samples

    def ended_turn(index: int) -> bool:
        return ends_turn_on_stop and index not in forced.sample_indices and samples[index].finish_reason == "stop"

    candidates = tuple(
        Candidate(
            candidate.tactic_block,
            StepSource.POLICY,
            log_probability=candidate.log_probability,
            prompt_tokens=generation.prompt_token_count,
            generated_tokens=candidate.generated_tokens,
            forced=candidate.forced,
            sample_count=candidate.sample_count,
            completions=tuple(
                GeneratedText(samples[index].text, ended_turn(index), positions, samples[index].tokens.rounded())
                for index, positions in zip(candidate.sample_indices, candidate.block_positions, strict=True)
            ),
            feedback=feedback,
        )
        for candidate in parsed.candidates
    )
    unparsed = tuple(
        UnparsedSample(samples[index].text, ended_turn(index), failure.value, samples[index].tokens.rounded())
        for index, failure in zip(parsed.failed_sample_indices, parsed.failures, strict=True)
    )
    return CandidateBatch(
        candidates,
        generation.prompt_token_count + forced.prompt_tokens,
        generation.completion_token_count + forced.generated_tokens,
        prompt=prompt,
        unparsed=unparsed,
        temperature=temperature,
        top_p=top_p,
        feedback=feedback,
    )


@dataclass(frozen=True)
class SampledExpansion:
    generation: Generation
    # The generation's samples with forced answers in place of the ones cut off before their block.
    samples: list[Sample]
    parsed: ParsedSamples
    forced: ForcedAnswers
    prompt: str = ""
    feedback: bool = False


@dataclass(frozen=True)
class PromptContext:
    """What a node's prompts show besides its goals; the feedback round adds the failed attempts."""

    lemmas: tuple[str, ...] = ()
    failed_tactics: tuple[str, ...] = ()
    failed_attempts: tuple[FailedAttempt, ...] = ()


def node_edges(tree: SearchTree, node: Node, source: StepSource) -> list[Edge]:
    return [edge for edge in tree.edges if edge.parent_id == node.node_id and edge.source == source]


def failed_automation(tree: SearchTree, node: Node) -> tuple[str, ...]:
    """The sweep's tactics that failed at the node, in the sweep's order."""
    return tuple(
        edge.text for edge in node_edges(tree, node, StepSource.AUTOMATION) if edge.outcome == EdgeOutcome.FAILED
    )


def failed_blocks(edges: Sequence[Edge]) -> list[Edge]:
    """The node's distinct policy blocks that failed with an error to show and reached no state, those behind the most
    samples first. A block that made progress before failing is not a failed attempt."""
    failed = [
        edge
        for edge in edges
        if edge.source == StepSource.POLICY
        and edge.repeat_of is None
        and edge.outcome in (EdgeOutcome.FAILED, EdgeOutcome.REJECTED)
        and edge.failure is not None
        and edge.failure.kind in FEEDBACK_FAILURE_KINDS
    ]
    return sorted(failed, key=lambda edge: -edge.sample_count)


def new_states(edges: Sequence[Edge]) -> int:
    """New states the node's policy samples (and their repairs) reached."""
    return sum(edge.source != StepSource.AUTOMATION and edge.outcome == EdgeOutcome.CHILD for edge in edges)


def feedback_fires(edges: Sequence[Edge], min_children: int, proves: Callable[[Edge], bool]) -> bool:
    """`edges`: the node's after its first request ran. With harvesting the search asks again after a proof; the node
    is closed by then."""
    return (
        new_states(edges) < min_children
        and bool(failed_blocks(edges))
        and not any(proves(edge) for edge in edges if edge.outcome == EdgeOutcome.CHILD)
    )


def failed_attempt(edge: Edge, config: FeedbackConfig) -> FailedAttempt:
    assert edge.failure is not None
    return FailedAttempt(
        shortened(edge.text, config.max_block_characters),
        shortened(error_summary(edge.failure.message), config.max_error_characters),
    )


def proves(tree: SearchTree, edge: Edge) -> bool:
    """`edge` reached a new state: a verified proof (a failed verification marks it FAILED)."""
    assert edge.target_id is not None
    target = tree.node(edge.target_id)
    return target.is_proved and target.status != NodeStatus.FAILED


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
        prompt_context = await self.prompt_context(node, context)
        sampled = await self.sample(node, context, prompt_context)
        if sampled is None:
            return
        yield self.batch(sampled)
        # The search ran the batch before asking for the next: its edges are in the tree.
        feedback = self.config.feedback
        if not feedback.enabled:
            return
        tree = context.tree
        edges = [edge for edge in tree.edges if edge.parent_id == node.node_id]
        if not feedback_fires(edges, feedback.min_children, functools.partial(proves, tree)):
            return
        attempts = tuple(failed_attempt(edge, feedback) for edge in failed_blocks(edges)[: feedback.max_attempts])
        shown = attempts if feedback.show_attempts else ()
        feedback_context = dataclasses.replace(prompt_context, failed_attempts=shown)
        sampled = await self.sample(node, context, feedback_context, feedback.sample_count, feedback=True)
        if sampled is not None:
            self.statistics.feedback_requests += 1
            yield self.batch(sampled)

    async def prompt_context(self, node: Node, context: SearchContext) -> PromptContext:
        lemmas = await self.lemma_provider.lemma_lines(node.state, context.repl) if self.lemma_provider else ()
        failed_tactics = failed_automation(context.tree, node) if self.config.failed_automation_in_prompt else ()
        return PromptContext(tuple(lemmas), failed_tactics)

    def batch(self, sampled: "SampledExpansion") -> CandidateBatch:
        return candidate_batch(
            sampled.parsed,
            sampled.generation,
            sampled.forced,
            samples=sampled.samples,
            prompt=sampled.prompt,
            ends_turn_on_stop=not stop_sequences(self.config.thinking, self.config.visible_reasoning),
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            feedback=sampled.feedback,
        )

    async def sample(
        self,
        node: Node,
        context: SearchContext,
        prompt_context: PromptContext | None = None,
        sample_count: int | None = None,
        feedback: bool = False,
    ) -> SampledExpansion | None:
        """The node's samples (forced answers in place) and their candidates; None when the prompt is too long."""
        if prompt_context is None:
            prompt_context = await self.prompt_context(node, context)
        prompt = render_prompt(
            self.tokenizer,
            node.goals,
            prompt_context.lemmas,
            few_shot=self.config.few_shot,
            thinking=self.config.thinking,
            thinking_instruction=self.config.thinking_instruction,
            visible=self.config.visible_reasoning,
            failed_tactics=prompt_context.failed_tactics,
            failed_attempts=prompt_context.failed_attempts,
        )
        prompt_token_ids = self.tokenizer.encode(prompt, add_special_tokens=False)
        max_tokens = min(self.config.max_tokens, self.max_model_length - len(prompt_token_ids))
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            self.statistics.prompts_too_long += 1
            return None
        sample_count = self.config.sample_count if sample_count is None else sample_count
        generation, seconds = await self._generate(prompt, max_tokens, sample_count)
        samples, forced, forcing_seconds = await self.force_answers(prompt_token_ids, generation.samples)
        parsed = parse_samples(
            samples,
            thinking=self.config.thinking,
            forbidden_tokens=self.forbidden_tokens,
            forced_indices=forced.sample_indices,
            visible=self.config.visible_reasoning,
        )
        self.statistics.record(generation, parsed, seconds + forcing_seconds, forced)
        return SampledExpansion(generation, samples, parsed, forced, prompt, feedback)

    async def force_answers(
        self, prompt_token_ids: Sequence[int], samples: Sequence[Sample]
    ) -> tuple[list[Sample], ForcedAnswers, float]:
        started = time.monotonic()
        forced_samples, forced = await force_answers(
            next(self._clients), self.config, self.tokenizer, prompt_token_ids, self.max_model_length, samples
        )
        return forced_samples, forced, time.monotonic() - started if forced.sample_indices else 0.0

    async def _generate(self, prompt: str, max_tokens: int, sample_count: int) -> tuple[Generation, float]:
        started = time.monotonic()
        if self._first_request_started is None:
            self._first_request_started = started
        generation = await next(self._clients).generate(
            prompt,
            sample_count=sample_count,
            max_tokens=max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            stop=stop_sequences(self.config.thinking, self.config.visible_reasoning),
            adapter=self.config.adapter,
        )
        finished = time.monotonic()
        self.statistics.window_seconds = finished - self._first_request_started
        return generation, finished - started


async def force_answers(
    client: PolicyClient,
    config: PolicyConfig,
    tokenizer: PolicyTokenizer,
    prompt_token_ids: Sequence[int],
    max_model_length: int,
    samples: Sequence[Sample],
) -> tuple[list[Sample], ForcedAnswers]:
    """Budget forcing: one request continues every sample cut off before its block, its reasoning closed."""
    visible = config.visible_reasoning
    truncated = [index for index, sample in enumerate(samples) if truncated_before_answer(sample, visible=visible)]
    if not (config.reasons and config.force_answer_on_truncation and truncated):
        return list(samples), ForcedAnswers()
    longest = max(samples[index].token_count for index in truncated)
    room = max_model_length - len(prompt_token_ids)
    max_tokens = min(config.forced_answer_tokens, room - longest - FORCED_ANSWER_PROMPT_SLACK)
    if max_tokens < MINIMUM_GENERATED_TOKENS:
        return list(samples), ForcedAnswers()
    opening_token_ids = tokenizer.encode(answer_opening(visible=visible), add_special_tokens=False)
    continuations = await client.generate_each(
        [forced_answer_prompt(prompt_token_ids, samples[index], opening_token_ids) for index in truncated],
        max_tokens=max_tokens,
        temperature=config.temperature,
        top_p=config.top_p,
        stop=(FENCE,),
        adapter=config.adapter,
    )
    forced = list(samples)
    for index, continuation in zip(truncated, continuations.samples, strict=True):
        forced[index] = forced_sample(samples[index], opening_token_ids, continuation, visible=visible)
    return forced, ForcedAnswers(
        frozenset(truncated), continuations.prompt_token_count, continuations.completion_token_count
    )


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
