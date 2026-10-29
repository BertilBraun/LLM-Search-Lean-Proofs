"""Mixed step lengths: from each state of a flat proof a chunk of k consecutive top-level tactics, k drawn per state."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from lean_search.corpora.tracing import stable_fraction

# A chunk length of 0 takes the rest of the proof.
REST_OF_PROOF = 0


@dataclass(frozen=True)
class ChunkLength:
    tactics: int
    weight: float = 1.0


DEFAULT_CHUNK_LENGTHS = (
    ChunkLength(1),
    ChunkLength(3),
    ChunkLength(5),
    ChunkLength(7),
    ChunkLength(REST_OF_PROOF),
)


class ChunkRejection(StrEnum):
    PROMPT_TOO_LONG = "prompt_too_long"
    COMPLETION_TOO_LONG = "completion_too_long"
    FORBIDDEN = "forbidden"
    # The chunk contains a tactic in which flattening left a nested `have … := by` proof.
    NESTED_HAVE = "nested_have"


@dataclass(frozen=True)
class Chunk:
    # Tactics start..end-1 of the flat proof; `drawn` is the length drawn for the start state (0: the rest).
    start: int
    end: int
    drawn: int

    @property
    def tactics(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class ChunkChoices:
    chunks: tuple[Chunk, ...]
    # Start states without any chunk that passes, by the rejection of the shortest one tried.
    dropped: Counter[ChunkRejection] = field(default_factory=Counter)


def drawn_length(key: str, lengths: Sequence[ChunkLength], seed: str) -> int:
    """A length drawn with the configured weights, fixed by the key (the proof and the start state)."""
    total = sum(length.weight for length in lengths)
    point = stable_fraction(key, f"{seed} chunk") * total
    for length in lengths:
        point -= length.weight
        if point < 0:
            return length.tactics
    return lengths[-1].tactics


def chunk_size(drawn: int, start: int, total: int) -> int:
    remaining = total - start
    return remaining if drawn == REST_OF_PROOF else min(drawn, remaining)


def fallback_sizes(size: int, lengths: Sequence[ChunkLength]) -> list[int]:
    """The size itself, then each shorter configured length (longest first) for when it does not fit."""
    shorter = sorted({length.tactics for length in lengths if 0 < length.tactics < size}, reverse=True)
    return [size, *shorter]


def choose_chunks(
    key: str,
    total: int,
    lengths: Sequence[ChunkLength],
    seed: str,
    rejection: Callable[[int, int], ChunkRejection | None],
) -> ChunkChoices:
    """One chunk per start state of a proof with `total` tactics; `rejection(start, end)` vets each candidate."""
    chunks: list[Chunk] = []
    dropped: Counter[ChunkRejection] = Counter()
    for start in range(total):
        drawn = drawn_length(f"{key}#{start}", lengths, seed)
        last_rejection: ChunkRejection | None = None
        for size in fallback_sizes(chunk_size(drawn, start, total), lengths):
            last_rejection = rejection(start, start + size)
            if last_rejection is None:
                chunks.append(Chunk(start, start + size, drawn))
                break
        if last_rejection is not None:
            dropped[last_rejection] += 1
    return ChunkChoices(tuple(chunks), dropped)
