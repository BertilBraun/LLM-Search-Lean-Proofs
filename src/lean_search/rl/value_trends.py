"""The value benchmark as a trend: each newly served value model's fresh scores, kept per value version, against v0's
and against those of the value model served before it."""

from dataclasses import dataclass
from pathlib import Path

from lean_search.monitoring.families import ValueBenchmarkTrend
from lean_search.rl.loop_config import ValueBenchmarkConfig
from lean_search.value.benchmark import (
    BenchmarkScores,
    ValueBenchmark,
    benchmark_metrics,
    fresh_estimates,
    read_scores,
    write_scores,
)
from lean_search.value.bins import Readout
from lean_search.value.diagnostics import benchmark_calibration, prediction_distribution, scored
from lean_search.value.pair_statistics import PairStatistic, pair_share, pair_statistic, remaining_steps

SCORES_PREFIX = "scores_v"
SCORES_SUFFIX = ".json.gz"


@dataclass(frozen=True)
class VersionScores:
    value_version: int
    scores: BenchmarkScores


def scores_path(directory: Path, value_version: int) -> Path:
    return directory / f"{SCORES_PREFIX}{value_version:04d}{SCORES_SUFFIX}"


def scored_versions(directory: Path) -> list[int]:
    return sorted(
        int(path.name.removeprefix(SCORES_PREFIX).removesuffix(SCORES_SUFFIX))
        for path in directory.glob(f"{SCORES_PREFIX}*{SCORES_SUFFIX}")
    )


def keep_scores(directory: Path, value_version: int, scores: BenchmarkScores) -> None:
    write_scores(scores_path(directory, value_version), scores)


def earlier_scores(
    directory: Path, value_version: int, reference_version: int
) -> tuple[VersionScores | None, VersionScores | None]:
    """The reference's scores and those of the latest value version scored before this one, where kept."""
    versions = scored_versions(directory)
    reference = (
        VersionScores(reference_version, read_scores(scores_path(directory, reference_version)))
        if reference_version in versions and reference_version != value_version
        else None
    )
    before = [version for version in versions if version < value_version]
    previous = VersionScores(before[-1], read_scores(scores_path(directory, before[-1]))) if before else None
    return reference, previous


def against(
    benchmark: ValueBenchmark,
    steps: list[float | None],
    other: VersionScores | None,
    readout: Readout,
    config: ValueBenchmarkConfig,
) -> PairStatistic | None:
    if other is None:
        return None
    return pair_statistic(benchmark, steps, remaining_steps(other.scores, readout), config.benchmark, config.pairs)


def benchmark_trend(
    benchmark: ValueBenchmark,
    scores: VersionScores,
    reference: VersionScores | None,
    previous: VersionScores | None,
    readout: Readout,
    config: ValueBenchmarkConfig,
    scoring_seconds: float,
) -> ValueBenchmarkTrend:
    steps = remaining_steps(scores.scores, readout)
    return ValueBenchmarkTrend(
        value_version=scores.value_version,
        pairs=pair_share(benchmark, steps, config.benchmark),
        reference_value_version=None if reference is None else reference.value_version,
        previous_value_version=None if previous is None else previous.value_version,
        against_reference=against(benchmark, steps, reference, readout, config),
        against_previous=against(benchmark, steps, previous, readout, config),
        metrics=benchmark_metrics(benchmark, fresh_estimates(benchmark, scores.scores, readout), config.benchmark),
        predictions=prediction_distribution(scored(scores.scores), readout),
        calibration=benchmark_calibration(benchmark, scores.scores),
        scoring_seconds=scoring_seconds,
    )


def worse_than_reference(trend: ValueBenchmarkTrend) -> bool:
    """The share of correctly ordered sibling pairs below v0's, the paired bootstrap interval wholly below 0."""
    statistic = trend.against_reference
    return statistic is not None and statistic.upper is not None and statistic.upper < 0


def difference_text(name: str, version: int | None, statistic: PairStatistic | None) -> str:
    if version is None or statistic is None or statistic.difference is None:
        return ""
    return f"; against {name} v{version} {statistic.difference:+.3f} [{statistic.lower:+.3f}, {statistic.upper:+.3f}]"


def trend_text(trend: ValueBenchmarkTrend) -> str:
    share = "-" if trend.pairs.share is None else f"{trend.pairs.share:.3f}"
    return (
        f"Value benchmark of value v{trend.value_version}: {share} of {trend.pairs.pairs} labelled sibling pairs "
        f"({trend.pairs.problems} problems) ordered by h"
        + difference_text("v0", trend.reference_value_version, trend.against_reference)
        + difference_text("the previous", trend.previous_value_version, trend.against_previous)
        + f"; scored in {trend.scoring_seconds:.0f} s"
    )
