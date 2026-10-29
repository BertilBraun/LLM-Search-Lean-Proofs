"""The rewritten SFT data of one naming variant: chunk examples of flat proofs plus the rewritten reasoning examples.

Both variants are built from the same items and the same chunks: an item enters only if it is usable numbered and
named, and a chunk only if it fits in both, so the naming A/B compares the names and nothing else. Chunks planned for
the visible mode carry the teacher's explanation (the same text in both variants up to the names); the others, and
those whose explanation was rejected, are non-visible examples.
"""

import hashlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

from lean_search.corpora.records import DataSplit
from lean_search.corpora.tracing import stable_fraction
from lean_search.data_rewrite.chunks import (
    DEFAULT_CHUNK_LENGTHS,
    Chunk,
    ChunkLength,
    ChunkRejection,
    choose_chunks,
)
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExampleStatus,
    ExplanationOutcome,
    ExplanationRejection,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.data_rewrite.replay import has_nested_have_proof
from lean_search.lean.text import find_forbidden_tokens, join_tactics
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin


class NameVariant(StrEnum):
    NUMBERED = "numbered"
    NAMED = "named"


@dataclass(frozen=True)
class BuildConfig:
    # The rewrite run ($LEAN_SEARCH_RUNS/<run>) whose records are used.
    rewrite_run: str
    variant: NameVariant
    chunk_lengths: tuple[ChunkLength, ...] = DEFAULT_CHUNK_LENGTHS
    # Train chunk examples planned for the visible mode (explained by the teacher) per train reasoning example.
    visible_chunk_examples_per_reasoning_example: float = 0.0
    # Share of the train examples that are plain non-visible chunk examples (the reasoning-free mode); 1 takes every
    # chunk not planned for the visible mode.
    non_visible_share: float = 0.5
    validation_chunk_examples: int = 500
    validation_visible_chunk_examples: int = 0
    max_prompt_tokens: int = 2048
    # The policy writes chunks in visible mode under a 1,280-token cap (explanation included).
    max_completion_tokens: int = 512
    tokenizer: str = "Qwen/Qwen3.5-4B"
    seed: str = "data-rewrite"


@dataclass(frozen=True)
class TracedVersion:
    tactics: tuple[str, ...]
    # The goals before each tactic, then after the last.
    goals: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ProofVersions:
    record: RewrittenProof
    numbered: TracedVersion
    named: TracedVersion

    def version(self, variant: NameVariant) -> TracedVersion:
        return self.numbered if variant is NameVariant.NUMBERED else self.named


@dataclass(frozen=True)
class TokenCounts:
    prompt: Callable[[tuple[str, ...]], int]
    completion: Callable[[str], int]


@dataclass(frozen=True)
class ChunkExample:
    source: str
    proof_identifier: str
    split: DataSplit
    start: int
    tactics: int
    # The drawn length (0: the rest of the proof); `tactics` is shorter when the proof ends first or it did not fit.
    drawn: int
    goals: tuple[str, ...]
    tactic_block: str
    goals_after: tuple[str, ...]
    # The teacher's explanation in this variant; "" for a non-visible example.
    explanation: str = ""


class ChunkPosition(NamedTuple):
    proof_identifier: str
    start: int
    tactics: int


@dataclass(frozen=True)
class PlannedChunk:
    versions: ProofVersions
    chunk: Chunk
    # Planned for the visible mode: explained by the teacher, else kept as a non-visible example.
    visible: bool

    @property
    def position(self) -> ChunkPosition:
        return ChunkPosition(self.versions.record.proof_identifier, self.chunk.start, self.chunk.tactics)


@dataclass(frozen=True)
class ChunkPlan:
    """Which items and chunks a build takes: the same in both variants and in the explain pass."""

    train_reasoning: tuple[RewrittenExample, ...]
    validation_reasoning: tuple[RewrittenExample, ...]
    train: tuple[PlannedChunk, ...]
    validation: tuple[PlannedChunk, ...]
    usable_proofs: int
    chunk_candidates: int
    duplicate_chunks: int
    dropped_starts: Counter[ChunkRejection] = field(default_factory=Counter)

    @property
    def visible(self) -> tuple[PlannedChunk, ...]:
        return tuple(planned for planned in (*self.train, *self.validation) if planned.visible)


@dataclass(frozen=True)
class BuiltData:
    train: tuple[ReasoningExample, ...]
    validation: tuple[ReasoningExample, ...]
    train_chunks: tuple[ChunkExample, ...]
    validation_chunks: tuple[ChunkExample, ...]
    # The rewritten reasoning examples among `train`.
    train_reasoning: tuple[ReasoningExample, ...]
    usable_proofs: int
    usable_examples: int
    chunk_candidates: int
    duplicate_chunks: int
    dropped_starts: Counter[ChunkRejection] = field(default_factory=Counter)
    # Per chunk planned for the visible mode (train and validation), and the teacher's rejected attempts for them.
    explanation_outcomes: Counter[ExplanationOutcome] = field(default_factory=Counter)
    explanation_rejections: Counter[ExplanationRejection] = field(default_factory=Counter)


def proof_versions(record: RewrittenProof) -> ProofVersions | None:
    """The flat proof numbered and named, or None unless it is usable in both variants."""
    if record.status is not ProofStatus.KEPT or not record.named.status.usable:
        return None
    numbered = TracedVersion(record.tactics, record.goals)
    if record.named.status is NamedStatus.NOTHING_TO_RENAME:
        return ProofVersions(record, numbered, numbered)
    return ProofVersions(record, numbered, TracedVersion(record.named.tactics, record.named.goals))


def chunk_block(version: TracedVersion, chunk: Chunk) -> str:
    return normalize_tactic_block(join_tactics(version.tactics[chunk.start : chunk.end]))


def chunk_rejection(
    versions: ProofVersions, counts: TokenCounts, config: BuildConfig
) -> Callable[[int, int], ChunkRejection | None]:
    nested = [has_nested_have_proof([tactic]) for tactic in versions.numbered.tactics]

    def rejection(start: int, end: int) -> ChunkRejection | None:
        if any(nested[start:end]):
            return ChunkRejection.NESTED_HAVE
        for version in (versions.numbered, versions.named):
            if counts.prompt(version.goals[start]) > config.max_prompt_tokens:
                return ChunkRejection.PROMPT_TOO_LONG
            block = chunk_block(version, Chunk(start, end, 0))
            if find_forbidden_tokens(block):
                return ChunkRejection.FORBIDDEN
            if counts.completion(block) > config.max_completion_tokens:
                return ChunkRejection.COMPLETION_TOO_LONG
        return None

    return rejection


def chunk_example(versions: ProofVersions, chunk: Chunk, variant: NameVariant, explanation: str = "") -> ChunkExample:
    record = versions.record
    version = versions.version(variant)
    return ChunkExample(
        source=record.source,
        proof_identifier=record.proof_identifier,
        split=record.split,
        start=chunk.start,
        tactics=chunk.tactics,
        drawn=chunk.drawn,
        goals=version.goals[chunk.start],
        tactic_block=chunk_block(version, chunk),
        goals_after=version.goals[chunk.end],
        explanation=explanation,
    )


def chunk_key(versions: ProofVersions, chunk: Chunk) -> bytes:
    """Duplicates are judged on the numbered text, so both variants drop the same chunks."""
    version = versions.numbered
    text = "\0".join((*version.goals[chunk.start], "\1", chunk_block(version, chunk)))
    return hashlib.sha256(text.encode()).digest()


def replay_example(chunk: ChunkExample) -> ReasoningExample:
    return ReasoningExample(
        chunk.source,
        chunk.proof_identifier,
        chunk.start,
        chunk.goals,
        chunk.tactic_block,
        None,
        "",
        ReasoningOrigin.REPLAY,
    )


def chunk_training_example(chunk: ChunkExample) -> ReasoningExample:
    """A visible-mode example when the chunk has an explanation (a step whose reasoning was written afterwards)."""
    if not chunk.explanation:
        return replay_example(chunk)
    return ReasoningExample(
        chunk.source,
        chunk.proof_identifier,
        chunk.start,
        chunk.goals,
        chunk.tactic_block,
        chunk.explanation,
        "",
        ReasoningOrigin.RATIONALIZED,
        visible=True,
    )


def usable_example(record: RewrittenExample) -> bool:
    return record.status is ExampleStatus.KEPT and record.named.status.usable


def rewritten_example(record: RewrittenExample, variant: NameVariant) -> ReasoningExample:
    """The reasoning example with its flat block, and in the named variant the renamed goals, block and reasoning."""
    named = record.named
    match variant:
        case NameVariant.NAMED if named.status is NamedStatus.RENAMED:
            return ReasoningExample(
                record.original.source,
                record.original.proof_identifier,
                record.original.step_index,
                named.goals,
                named.tactic_block,
                named.reasoning,
                record.original.thinking_instruction,
                record.original.origin,
                record.original.visible,
            )
        case _:
            original = record.original
            return ReasoningExample(
                original.source,
                original.proof_identifier,
                original.step_index,
                original.goals,
                record.tactic_block,
                original.reasoning,
                original.thinking_instruction,
                original.origin,
                original.visible,
            )


def reasoning_key(record: RewrittenExample) -> str:
    """The same in both variants, so both list their examples in the same order."""
    original = record.original
    return f"reasoning#{original.proof_identifier}#{original.step_index}#{original.reasoning}#{original.tactic_block}"


def ordered[T](items: Sequence[T], key: Callable[[T], str], seed: str) -> list[T]:
    return sorted(items, key=lambda item: stable_fraction(key(item), seed))


def train_chunk_counts(available: int, reasoning: int, config: BuildConfig) -> tuple[int, int]:
    """How many train chunks are planned for the visible mode, and how many stay non-visible."""
    visible = min(available, round(config.visible_chunk_examples_per_reasoning_example * reasoning))
    remaining = available - visible
    if config.non_visible_share >= 1:
        return visible, remaining
    non_visible = round(config.non_visible_share / (1 - config.non_visible_share) * (reasoning + visible))
    return visible, min(remaining, non_visible)


def planned_chunks(
    candidates: Sequence[tuple[ProofVersions, Chunk]], visible: int, non_visible: int
) -> tuple[PlannedChunk, ...]:
    return (
        *(PlannedChunk(versions, chunk, True) for versions, chunk in candidates[:visible]),
        *(PlannedChunk(versions, chunk, False) for versions, chunk in candidates[visible : visible + non_visible]),
    )


def plan_chunks(
    proofs: Sequence[RewrittenProof],
    examples: Sequence[RewrittenExample],
    config: BuildConfig,
    counts: TokenCounts,
) -> ChunkPlan:
    usable_proofs = [versions for record in proofs if (versions := proof_versions(record)) is not None]
    reasoning = [record for record in examples if usable_example(record)]
    train_reasoning = tuple(record for record in reasoning if record.split is DataSplit.TRAIN)
    seen: set[bytes] = set()
    duplicates = candidates = 0
    dropped: Counter[ChunkRejection] = Counter()
    chunks: list[tuple[ProofVersions, Chunk]] = []
    for versions in ordered(usable_proofs, lambda versions: versions.record.proof_identifier, f"{config.seed} proofs"):
        choices = choose_chunks(
            versions.record.proof_identifier,
            len(versions.numbered.tactics),
            config.chunk_lengths,
            config.seed,
            chunk_rejection(versions, counts, config),
        )
        dropped.update(choices.dropped)
        for chunk in choices.chunks:
            candidates += 1
            key = chunk_key(versions, chunk)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            chunks.append((versions, chunk))
    by_position = ordered(
        chunks, lambda pair: f"{pair[0].record.proof_identifier}#{pair[1].start}", f"{config.seed} chunks"
    )
    train = [pair for pair in by_position if pair[0].record.split is DataSplit.TRAIN]
    validation = [pair for pair in by_position if pair[0].record.split is DataSplit.VALIDATION]
    visible, non_visible = train_chunk_counts(len(train), len(train_reasoning), config)
    # Non-visible first: these are the chunks validation took before the visible mode had chunk examples.
    non_visible_validation = validation[: config.validation_chunk_examples]
    visible_validation = validation[len(non_visible_validation) :][: config.validation_visible_chunk_examples]
    return ChunkPlan(
        train_reasoning=train_reasoning,
        validation_reasoning=tuple(record for record in reasoning if record.split is DataSplit.VALIDATION),
        train=planned_chunks(train, visible, non_visible),
        validation=(
            *planned_chunks(non_visible_validation, 0, len(non_visible_validation)),
            *planned_chunks(visible_validation, len(visible_validation), 0),
        ),
        usable_proofs=len(usable_proofs),
        chunk_candidates=candidates,
        duplicate_chunks=duplicates,
        dropped_starts=dropped,
    )


def explained_chunk(
    planned: PlannedChunk, explanations: Mapping[ChunkPosition, ChunkExplanation], variant: NameVariant
) -> ChunkExample:
    record = explanations.get(planned.position) if planned.visible else None
    explanation = ""
    if record is not None and record.outcome is ExplanationOutcome.EXPLAINED:
        explanation = record.named if variant is NameVariant.NAMED else record.numbered
    return chunk_example(planned.versions, planned.chunk, variant, explanation)


def build_data(
    proofs: Sequence[RewrittenProof],
    examples: Sequence[RewrittenExample],
    config: BuildConfig,
    counts: TokenCounts,
    explanations: Mapping[ChunkPosition, ChunkExplanation] | None = None,
) -> BuiltData:
    """The data of one variant; a chunk planned for the visible mode without an accepted explanation stays plain."""
    explanations = explanations or {}
    plan = plan_chunks(proofs, examples, config, counts)
    train_reasoning = [
        (reasoning_key(record), rewritten_example(record, config.variant)) for record in plan.train_reasoning
    ]
    train_chunks = [explained_chunk(planned, explanations, config.variant) for planned in plan.train]
    validation_chunks = [explained_chunk(planned, explanations, config.variant) for planned in plan.validation]
    keyed_chunks = [
        (f"chunk#{chunk.proof_identifier}#{chunk.start}", chunk_training_example(chunk)) for chunk in train_chunks
    ]
    train = ordered([*train_reasoning, *keyed_chunks], lambda pair: pair[0], f"{config.seed} order")
    records = [explanations.get(planned.position) for planned in plan.visible]
    return BuiltData(
        train=tuple(example for _, example in train),
        # The trainer's greedy-generation check reads the first validation examples: the non-visible chunks.
        validation=(
            *(replay_example(chunk) for chunk in validation_chunks if not chunk.explanation),
            *(chunk_training_example(chunk) for chunk in validation_chunks if chunk.explanation),
            *(rewritten_example(record, config.variant) for record in plan.validation_reasoning),
        ),
        train_chunks=tuple(train_chunks),
        validation_chunks=tuple(validation_chunks),
        train_reasoning=tuple(example for _, example in train_reasoning),
        usable_proofs=plan.usable_proofs,
        usable_examples=len(plan.train_reasoning) + len(plan.validation_reasoning),
        chunk_candidates=plan.chunk_candidates,
        duplicate_chunks=plan.duplicate_chunks,
        dropped_starts=plan.dropped_starts,
        explanation_outcomes=Counter(
            ExplanationOutcome.NOT_REQUESTED if record is None else record.outcome for record in records
        ),
        explanation_rejections=Counter(
            rejected.rejection for record in records if record is not None for rejected in record.rejected
        ),
    )
