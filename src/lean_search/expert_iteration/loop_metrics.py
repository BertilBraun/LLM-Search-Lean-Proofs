"""Online metrics of the loop, free from the actors' output: solve rates and proofs per hour per model version,
and how well the value model's h, as the search used it, matches the labels of the fresh trees."""

import datetime
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.expert_iteration.digests import VersionedValueExample
from lean_search.expert_iteration.shards import AttemptRecord
from lean_search.value.labels import LabelKind
from lean_search.value.metrics import roc_auc, spearman_correlation


@dataclass(frozen=True)
class VersionMetrics:
    version: int
    attempts: int
    first_pass_attempts: int
    first_pass_solved: int
    later_pass_attempts: int
    later_pass_solved: int
    # Solved attempts over the hours between the version's first and last finished attempt.
    proofs_per_hour: float
    attempts_per_hour: float
    mean_root_value_solved: float | None
    mean_root_value_unsolved: float | None
    # h against the exact remaining steps, and h separating dead from exact states, on this version's trees.
    spearman: float | None
    dead_auc: float | None
    labelled_states: int


@dataclass(frozen=True)
class RunTotals:
    attempts: int
    statements: int
    solved_statements: int
    proofs_last_hour: int
    attempts_last_hour: int


def hours_between(first: str, last: str) -> float:
    span = datetime.datetime.fromisoformat(last) - datetime.datetime.fromisoformat(first)
    return span.total_seconds() / 3600


def mean_or_none(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def version_metrics(attempts: Sequence[AttemptRecord], values: Iterable[VersionedValueExample]) -> list[VersionMetrics]:
    by_version: dict[int, list[AttemptRecord]] = defaultdict(list)
    for attempt in attempts:
        by_version[attempt.model_version].append(attempt)
    estimates: dict[int, list[VersionedValueExample]] = defaultdict(list)
    for value in values:
        if value.estimate is not None and value.example.kind != LabelKind.AT_LEAST:
            estimates[value.model_version].append(value)
    metrics = []
    for version in sorted(by_version):
        records = by_version[version]
        first = [attempt for attempt in records if attempt.pass_index == 0]
        later = [attempt for attempt in records if attempt.pass_index > 0]
        hours = hours_between(min(attempt.started_at for attempt in records), max(a.finished_at for a in records))
        exact = [value for value in estimates[version] if value.example.kind == LabelKind.EXACT]
        labelled = estimates[version]
        metrics.append(
            VersionMetrics(
                version=version,
                attempts=len(records),
                first_pass_attempts=len(first),
                first_pass_solved=sum(attempt.proved for attempt in first),
                later_pass_attempts=len(later),
                later_pass_solved=sum(attempt.proved for attempt in later),
                proofs_per_hour=sum(attempt.proved for attempt in records) / hours if hours else 0.0,
                attempts_per_hour=len(records) / hours if hours else 0.0,
                mean_root_value_solved=mean_or_none(
                    [a.root_value for a in records if a.proved and a.root_value is not None]
                ),
                mean_root_value_unsolved=mean_or_none(
                    [a.root_value for a in records if not a.proved and a.root_value is not None]
                ),
                spearman=spearman_correlation(
                    [value.estimate for value in exact if value.estimate is not None],
                    [float(value.example.steps) for value in exact],
                )
                if len(exact) > 1
                else None,
                dead_auc=roc_auc(
                    [value.estimate for value in labelled if value.estimate is not None],
                    [value.example.kind == LabelKind.DEAD for value in labelled],
                ),
                labelled_states=len(labelled),
            )
        )
    return metrics


def run_totals(attempts: Sequence[AttemptRecord], current: datetime.datetime) -> RunTotals:
    hour_ago = (current - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    recent = [attempt for attempt in attempts if attempt.finished_at >= hour_ago]
    return RunTotals(
        attempts=len(attempts),
        statements=len({attempt.problem_name for attempt in attempts}),
        solved_statements=len({attempt.problem_name for attempt in attempts if attempt.proved}),
        proofs_last_hour=sum(attempt.proved for attempt in recent),
        attempts_last_hour=len(recent),
    )
