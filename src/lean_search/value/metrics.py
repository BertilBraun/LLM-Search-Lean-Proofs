"""Validation metrics of predicted bin distributions against value labels."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.value.bins import BIN_COUNT, DEAD_BIN, Readout, step_bin
from lean_search.value.labels import LabelKind, ValueExample


@dataclass(frozen=True)
class ValueMetrics:
    examples: int
    # Exact and dead labels: the most likely bin is the label's bin.
    bin_accuracy: float | None
    # Exact labels: expected steps given alive against the label's steps, 8+ read out as in the readout.
    alive_mean_absolute_error: float | None
    # Exact labels: rank correlation of h with the remaining steps.
    spearman: float | None
    # p_dead separating dead from exact labels.
    dead_auc: float | None
    # Censored labels: mean probability of "at least n more steps or dead".
    at_least_probability: float | None
    # Rows: label bin of exact and dead labels; columns: most likely bin.
    confusion: tuple[tuple[int, ...], ...]


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks; tied values share the mean of their ranks."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman_correlation(first: Sequence[float], second: Sequence[float]) -> float | None:
    """None when either side is constant."""
    first_ranks = average_ranks(first)
    second_ranks = average_ranks(second)
    first_mean = sum(first_ranks) / len(first_ranks)
    second_mean = sum(second_ranks) / len(second_ranks)
    covariance = sum((a - first_mean) * (b - second_mean) for a, b in zip(first_ranks, second_ranks, strict=True))
    first_spread = math.sqrt(sum((a - first_mean) ** 2 for a in first_ranks))
    second_spread = math.sqrt(sum((b - second_mean) ** 2 for b in second_ranks))
    if first_spread == 0 or second_spread == 0:
        return None
    return covariance / (first_spread * second_spread)


def roc_auc(scores: Sequence[float], positives: Sequence[bool]) -> float | None:
    """The probability that a random positive scores above a random negative (ties count half)."""
    positive_count = sum(positives)
    negative_count = len(positives) - positive_count
    if positive_count == 0 or negative_count == 0:
        return None
    rank_sum = sum(rank for rank, positive in zip(average_ranks(scores), positives, strict=True) if positive)
    return (rank_sum - positive_count * (positive_count + 1) / 2) / (positive_count * negative_count)


def label_bin(example: ValueExample) -> int:
    return DEAD_BIN if example.kind == LabelKind.DEAD else step_bin(example.steps)


def value_metrics(
    distributions: Sequence[Sequence[float]], examples: Sequence[ValueExample], readout: Readout
) -> ValueMetrics:
    confusion = [[0] * BIN_COUNT for _ in range(BIN_COUNT)]
    correct: list[float] = []
    absolute_errors: list[float] = []
    predicted_steps: list[float] = []
    exact_steps: list[float] = []
    dead_scores: list[float] = []
    is_dead: list[bool] = []
    at_least_probabilities: list[float] = []
    for distribution, example in zip(distributions, examples, strict=True):
        predicted_bin = max(range(BIN_COUNT), key=lambda index: distribution[index])
        if example.kind == LabelKind.AT_LEAST:
            first_bin = step_bin(example.steps)
            at_least_probabilities.append(sum(distribution[first_bin:]))
            continue
        confusion[label_bin(example)][predicted_bin] += 1
        correct.append(float(predicted_bin == label_bin(example)))
        dead_scores.append(distribution[DEAD_BIN])
        is_dead.append(example.kind == LabelKind.DEAD)
        if example.kind == LabelKind.EXACT:
            absolute_errors.append(
                abs(readout.alive_remaining_steps(distribution) - readout.label_steps(example.steps))
            )
            predicted_steps.append(readout.remaining_steps(distribution))
            exact_steps.append(float(example.steps))
    return ValueMetrics(
        examples=len(examples),
        bin_accuracy=mean(correct),
        alive_mean_absolute_error=mean(absolute_errors),
        spearman=spearman_correlation(predicted_steps, exact_steps) if len(exact_steps) > 1 else None,
        dead_auc=roc_auc(dead_scores, is_dead),
        at_least_probability=mean(at_least_probabilities),
        confusion=tuple(tuple(row) for row in confusion),
    )
