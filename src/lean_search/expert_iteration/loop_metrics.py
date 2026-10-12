"""Online metrics of the loop, free from the searches' output: solve rates and proofs per hour per model version,
the yield of each budget stage per GPU-second, and how well the value model's h, as the search used it, matches the
labels of the fresh trees.

GPU time is attributed to stages by their share of the generated tokens (decoding dominates the servers' work): the
servers' GPU-seconds during search, spread evenly over every generated token.
"""

import datetime
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.expert_iteration.digests import VersionedValueExample
from lean_search.expert_iteration.shards import AttemptRecord, Decision
from lean_search.value.labels import LabelKind
from lean_search.value.metrics import roc_auc, spearman_correlation


@dataclass(frozen=True)
class VersionMetrics:
    version: int
    # Stage records started on this version.
    attempts: int
    first_stage_attempts: int
    first_stage_solved: int
    later_stage_attempts: int
    later_stage_solved: int
    # First and harvested proofs.
    proofs: int
    # Over the hours between the version's first and last finished stage.
    proofs_per_hour: float
    attempts_per_hour: float
    mean_root_value_solved: float | None
    mean_root_value_unsolved: float | None
    # h against the exact remaining steps, and h separating dead from exact states, on this version's trees.
    spearman: float | None
    dead_auc: float | None
    labelled_states: int


@dataclass(frozen=True)
class StageMetrics:
    stage: int
    attempts: int
    solved: int
    proofs: int
    escalated: int
    expansions: int
    generated_tokens: int
    gpu_seconds: float
    proofs_per_gpu_hour: float
    mean_wall_seconds: float


@dataclass(frozen=True)
class RunTotals:
    attempts: int
    statements: int
    solved_statements: int
    proofs: int
    proofs_last_hour: int
    attempts_last_hour: int


@dataclass(frozen=True)
class Interval:
    started_at: str
    finished_at: str


def hours_between(first: str, last: str) -> float:
    span = datetime.datetime.fromisoformat(last) - datetime.datetime.fromisoformat(first)
    return span.total_seconds() / 3600


def mean_or_none(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def search_seconds(attempts: Sequence[AttemptRecord], pauses: Sequence[Interval]) -> float:
    """From the first stage's start to the last stage's end, without the training phases in between."""
    if not attempts:
        return 0.0
    first = min(attempt.started_at for attempt in attempts)
    last = max(attempt.finished_at for attempt in attempts)
    paused = sum(
        hours_between(max(pause.started_at, first), min(pause.finished_at, last))
        for pause in pauses
        if pause.finished_at > first and pause.started_at < last
    )
    return (hours_between(first, last) - paused) * 3600


def stage_metrics(attempts: Sequence[AttemptRecord], gpus: int, searched_seconds: float) -> list[StageMetrics]:
    total_tokens = sum(attempt.generated_tokens for attempt in attempts)
    gpu_seconds_per_token = gpus * searched_seconds / total_tokens if total_tokens else 0.0
    by_stage: dict[int, list[AttemptRecord]] = defaultdict(list)
    for attempt in attempts:
        by_stage[attempt.stage].append(attempt)
    metrics = []
    for stage in sorted(by_stage):
        records = by_stage[stage]
        proofs = sum(attempt.proofs for attempt in records)
        tokens = sum(attempt.generated_tokens for attempt in records)
        gpu_seconds = tokens * gpu_seconds_per_token
        metrics.append(
            StageMetrics(
                stage=stage,
                attempts=len(records),
                solved=sum(attempt.proved for attempt in records),
                proofs=proofs,
                escalated=sum(attempt.decision == Decision.ESCALATED for attempt in records),
                expansions=sum(attempt.expansions + attempt.harvest_expansions for attempt in records),
                generated_tokens=tokens,
                gpu_seconds=gpu_seconds,
                proofs_per_gpu_hour=proofs / gpu_seconds * 3600 if gpu_seconds else 0.0,
                mean_wall_seconds=statistics.fmean(attempt.wall_seconds for attempt in records),
            )
        )
    return metrics


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
        first = [attempt for attempt in records if attempt.stage == 0]
        later = [attempt for attempt in records if attempt.stage > 0]
        hours = hours_between(min(attempt.started_at for attempt in records), max(a.finished_at for a in records))
        proofs = sum(attempt.proofs for attempt in records)
        exact = [value for value in estimates[version] if value.example.kind == LabelKind.EXACT]
        labelled = estimates[version]
        metrics.append(
            VersionMetrics(
                version=version,
                attempts=len(records),
                first_stage_attempts=len(first),
                first_stage_solved=sum(attempt.proved for attempt in first),
                later_stage_attempts=len(later),
                later_stage_solved=sum(attempt.proved for attempt in later),
                proofs=proofs,
                proofs_per_hour=proofs / hours if hours else 0.0,
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
        proofs=sum(attempt.proofs for attempt in attempts),
        proofs_last_hour=sum(attempt.proofs for attempt in recent),
        attempts_last_hour=len(recent),
    )
