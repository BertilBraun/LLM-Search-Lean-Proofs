"""Offline retrieval metrics on LeanDojo states: recall@k, hit rate@k, MRR, and premise accessibility."""

import functools
import statistics
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedExample:
    gold: frozenset[str]
    ranked: tuple[str, ...]


@dataclass(frozen=True)
class RecallAtK:
    k: int
    # Mean over states of the fraction of gold premises in the top k (ReProver's R@k).
    recall: float
    # Fraction of states with at least one gold premise in the top k.
    hit_rate: float


@dataclass(frozen=True)
class RecallSummary:
    examples: int
    mean_gold_premises: float
    at_k: tuple[RecallAtK, ...]
    mean_reciprocal_rank: float


def recall_at_k(gold: Collection[str], ranked: Sequence[str], k: int) -> float:
    return len(set(ranked[:k]) & set(gold)) / len(gold)


def hit_at_k(gold: Collection[str], ranked: Sequence[str], k: int) -> bool:
    return not set(ranked[:k]).isdisjoint(gold)


def reciprocal_rank(gold: Collection[str], ranked: Sequence[str]) -> float:
    return next((1 / (rank + 1) for rank, name in enumerate(ranked) if name in gold), 0.0)


def summarize_recall(examples: Sequence[RankedExample], ks: Sequence[int]) -> RecallSummary:
    return RecallSummary(
        examples=len(examples),
        mean_gold_premises=statistics.fmean(len(example.gold) for example in examples),
        at_k=tuple(
            RecallAtK(
                k,
                statistics.fmean(recall_at_k(example.gold, example.ranked, k) for example in examples),
                statistics.fmean(hit_at_k(example.gold, example.ranked, k) for example in examples),
            )
            for k in ks
        ),
        mean_reciprocal_rank=statistics.fmean(reciprocal_rank(example.gold, example.ranked) for example in examples),
    )


def transitive_imports(imports: Mapping[str, Sequence[str]]) -> dict[str, frozenset[str]]:
    """Every file each file depends on, itself excluded; imports of files outside the mapping are ignored."""

    @functools.cache
    def closure(file_path: str) -> frozenset[str]:
        reached: set[str] = set()
        for imported in imports.get(file_path, ()):
            if imported in imports:
                reached.add(imported)
                reached |= closure(imported)
        return frozenset(reached)

    return {file_path: closure(file_path) for file_path in imports}
