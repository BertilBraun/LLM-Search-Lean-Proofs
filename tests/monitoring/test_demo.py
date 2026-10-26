from pathlib import Path

import pytest

from lean_search.monitoring.demo import DemoSchedule, demo_runs
from lean_search.monitoring.families import FAMILIES
from lean_search.monitoring.store import MetricsWriter, RunReader

NOW = 1_800_000_000.0


@pytest.fixture(scope="module")
def demo_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("demo")
    demo_runs(MetricsWriter(directory / "main"), MetricsWriter(directory / "control"), 0.5, DemoSchedule(), NOW)
    return directory


@pytest.mark.parametrize("run", ["main", "control"])
def test_demo_writes_every_family(demo_directory: Path, run: str) -> None:
    assert RunReader(demo_directory / run).families() == sorted(family.family for family in FAMILIES)


def test_demo_baseline_evaluation_is_policy_version_zero(demo_directory: Path) -> None:
    assert RunReader(demo_directory / "main").series("fixed_targets").policy_versions[0] == 0


def test_demo_records_end_before_now(demo_directory: Path) -> None:
    assert max(RunReader(demo_directory / "main").series("system").times) <= NOW
