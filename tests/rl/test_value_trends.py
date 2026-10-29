from pathlib import Path

from lean_search.rl.loop_config import ValueBenchmarkConfig
from lean_search.rl.value_trends import (
    VersionScores,
    benchmark_trend,
    earlier_scores,
    keep_scores,
    scored_versions,
)
from lean_search.value.benchmark import BenchmarkScores, ValueBenchmark, benchmark_fingerprint
from lean_search.value.bins import Readout

EMPTY = ValueBenchmark(provenance=(), states=(), groups=())


def scores(model: str) -> BenchmarkScores:
    return BenchmarkScores(model, benchmark_fingerprint(EMPTY), ())


def kept(directory: Path, versions: list[int]) -> None:
    for version in versions:
        keep_scores(directory, version, scores(f"v{version}"))


def test_kept_scores_list_their_value_versions_in_order(tmp_path: Path) -> None:
    kept(tmp_path, [8, 0, 4])
    assert scored_versions(tmp_path) == [0, 4, 8]


def test_the_previous_scores_are_the_latest_value_version_before(tmp_path: Path) -> None:
    kept(tmp_path, [0, 4, 8, 12])
    _, previous = earlier_scores(tmp_path, 12, 0)
    assert previous is not None and previous.scores.model == "v8"


def test_the_reference_has_no_reference_but_itself(tmp_path: Path) -> None:
    kept(tmp_path, [0])
    assert earlier_scores(tmp_path, 0, 0) == (None, None)


def test_a_trend_names_the_value_versions_it_compares(tmp_path: Path) -> None:
    trend = benchmark_trend(
        EMPTY,
        VersionScores(8, scores("v8")),
        VersionScores(0, scores("v0")),
        VersionScores(4, scores("v4")),
        Readout(),
        ValueBenchmarkConfig(),
        30.0,
    )
    assert (trend.value_version, trend.reference_value_version, trend.previous_value_version) == (8, 0, 4)
