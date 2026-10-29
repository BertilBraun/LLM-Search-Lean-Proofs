"""The rewritten SFT data of one naming variant: chunk examples of flat proofs plus the rewritten reasoning examples.

Both variants are built from the same items and the same chunks: an item enters only if it is usable numbered and
named, and a chunk only if it fits in both, so the naming A/B compares the names and nothing else.
"""

import hashlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

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
    ExampleStatus,
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
    # Train chunk examples per train reasoning example; 0 takes every chunk example.
    chunk_examples_per_reasoning_example: float = 1.0
    validation_chunk_examples: int = 500
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


@dataclass(frozen=True)
class BuiltData:
    train: tuple[ReasoningExample, ...]
    validation: tuple[ReasoningExample, ...]
    train_chunks: tuple[ChunkExample, ...]
    validation_chunks: tuple[ChunkExample, ...]
    usable_proofs: int
    usable_examples: int
    chunk_candidates: int
    duplicate_chunks: int
    dropped_starts: Counter[ChunkRejection] = field(default_factory=Counter)


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


def chunk_example(versions: ProofVersions, chunk: Chunk, variant: NameVariant) -> ChunkExample:
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


def build_data(
    proofs: Sequence[RewrittenProof],
    examples: Sequence[RewrittenExample],
    config: BuildConfig,
    counts: TokenCounts,
) -> BuiltData:
    usable_proofs = [versions for record in proofs if (versions := proof_versions(record)) is not None]
    reasoning = [record for record in examples if usable_example(record)]
    train_reasoning = [
        (reasoning_key(record), rewritten_example(record, config.variant))
        for record in reasoning
        if record.split is DataSplit.TRAIN
    ]
    validation_reasoning = [
        rewritten_example(record, config.variant) for record in reasoning if record.split is DataSplit.VALIDATION
    ]
    seen: set[bytes] = set()
    duplicates = candidates = 0
    dropped: Counter[ChunkRejection] = Counter()
    chunks: list[ChunkExample] = []
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
            chunks.append(chunk_example(versions, chunk, config.variant))
    by_position = ordered(chunks, lambda chunk: f"{chunk.proof_identifier}#{chunk.start}", f"{config.seed} chunks")
    train_chunks = [chunk for chunk in by_position if chunk.split is DataSplit.TRAIN]
    if config.chunk_examples_per_reasoning_example:
        train_chunks = train_chunks[: round(config.chunk_examples_per_reasoning_example * len(train_reasoning))]
    validation_chunks = [chunk for chunk in by_position if chunk.split is DataSplit.VALIDATION]
    validation_chunks = validation_chunks[: config.validation_chunk_examples]
    keyed_chunks = [(f"chunk#{chunk.proof_identifier}#{chunk.start}", replay_example(chunk)) for chunk in train_chunks]
    train = ordered([*train_reasoning, *keyed_chunks], lambda pair: pair[0], f"{config.seed} order")
    return BuiltData(
        train=tuple(example for _, example in train),
        # The trainer's greedy-generation check reads the first validation examples: the non-reasoning chunks.
        validation=(*map(replay_example, validation_chunks), *validation_reasoning),
        train_chunks=tuple(train_chunks),
        validation_chunks=tuple(validation_chunks),
        usable_proofs=len(usable_proofs),
        usable_examples=len(reasoning),
        chunk_candidates=candidates,
        duplicate_chunks=duplicates,
        dropped_starts=dropped,
    )
