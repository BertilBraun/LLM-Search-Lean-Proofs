import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from cgroup_trees import V1_TREE, V2_TREE, cgroup_tree

from lean_search.monitoring.cgroup import (
    CpuCounters,
    anonymous_memory_bytes,
    cpu_counters,
    cpu_quota_cores,
    memory_limit_bytes,
    memory_used_bytes,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
CGROUP_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "cgroup.sh"
BOTH_LAYOUTS = pytest.mark.parametrize("files", [V2_TREE, V1_TREE], ids=["v2", "v1"])
UNLIMITED_QUOTAS = pytest.mark.parametrize(
    "files", [V2_TREE | {"cpu.max": "max 100000"}, V1_TREE | {"cpu/cpu.cfs_quota_us": "-1"}], ids=["v2", "v1"]
)


@pytest.mark.parametrize(("files", "cores"), [(V2_TREE, 61.0), (V1_TREE, 105.32571)], ids=["v2", "v1"])
def test_the_quota_reads_in_cores(tmp_path: Path, files: dict[str, str], cores: float) -> None:
    assert cpu_quota_cores(cgroup_tree(tmp_path, files)) == pytest.approx(cores)


@UNLIMITED_QUOTAS
def test_an_unlimited_quota_reads_as_none(tmp_path: Path, files: dict[str, str]) -> None:
    assert cpu_quota_cores(cgroup_tree(tmp_path, files)) is None


@pytest.mark.parametrize(
    ("files", "counters"),
    [(V2_TREE, CpuCounters(5.0, 10, 3)), (V1_TREE, CpuCounters(5.0, 179768, 4))],
    ids=["v2", "v1"],
)
def test_the_cpu_counters_read_usage_in_seconds_and_periods(
    tmp_path: Path, files: dict[str, str], counters: CpuCounters
) -> None:
    assert cpu_counters(cgroup_tree(tmp_path, files)) == counters


def test_v2_cpu_counters_without_the_cpu_controller_have_no_periods(tmp_path: Path) -> None:
    files = V2_TREE | {"cpu.stat": "usage_usec 5000000\nuser_usec 4000000\nsystem_usec 1000000"}
    assert cpu_counters(cgroup_tree(tmp_path, files)) == CpuCounters(5.0, 0, 0)


@pytest.mark.parametrize(("files", "limit"), [(V2_TREE, 128849018880), (V1_TREE, 196109926400)], ids=["v2", "v1"])
def test_the_memory_limit_reads_in_bytes(tmp_path: Path, files: dict[str, str], limit: int) -> None:
    assert memory_limit_bytes(cgroup_tree(tmp_path, files)) == limit


@pytest.mark.parametrize(
    "files",
    [V2_TREE | {"memory.max": "max"}, V1_TREE | {"memory/memory.limit_in_bytes": "9223372036854771712"}],
    ids=["v2", "v1"],
)
def test_an_unlimited_memory_limit_reads_as_none(tmp_path: Path, files: dict[str, str]) -> None:
    assert memory_limit_bytes(cgroup_tree(tmp_path, files)) is None


@BOTH_LAYOUTS
def test_used_memory_counts_the_page_cache(tmp_path: Path, files: dict[str, str]) -> None:
    assert memory_used_bytes(cgroup_tree(tmp_path, files)) == 8 << 30


@BOTH_LAYOUTS
def test_anonymous_memory_includes_child_cgroups(tmp_path: Path, files: dict[str, str]) -> None:
    assert anonymous_memory_bytes(cgroup_tree(tmp_path, files)) == 3 << 30


@pytest.mark.parametrize(
    "reader", [cpu_quota_cores, cpu_counters, memory_limit_bytes, memory_used_bytes, anonymous_memory_bytes]
)
def test_readers_without_their_controller_return_none(tmp_path: Path, reader: Callable[[Path], object]) -> None:
    assert reader(tmp_path) is None


def shell_quota(root: Path) -> str:
    command = f'set -euo pipefail; source "{CGROUP_SCRIPT}"; cgroup_quota_cores'
    environment = os.environ | {"CGROUP_ROOT": str(root)}
    return subprocess.run(["bash", "-c", command], env=environment, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize(
    ("files", "printed"),
    [(V2_TREE, "61\n"), (V1_TREE, "105\n"), (V2_TREE | {"cpu.max": "50000 100000"}, "1\n")],
    ids=["v2", "v1", "below one core"],
)
def test_the_shell_quota_prints_whole_cores_and_at_least_one(
    tmp_path: Path, files: dict[str, str], printed: str
) -> None:
    assert shell_quota(cgroup_tree(tmp_path, files)) == printed


@UNLIMITED_QUOTAS
def test_the_shell_quota_prints_nothing_when_unlimited(tmp_path: Path, files: dict[str, str]) -> None:
    assert shell_quota(cgroup_tree(tmp_path, files)) == ""


def test_the_shell_quota_prints_nothing_without_a_cpu_controller(tmp_path: Path) -> None:
    assert shell_quota(tmp_path) == ""


def shell_allowed_cpus(root: Path) -> str:
    command = f'set -euo pipefail; source "{CGROUP_SCRIPT}"; cgroup_allowed_cpus'
    environment = os.environ | {"CGROUP_ROOT": str(root)}
    return subprocess.run(["bash", "-c", command], env=environment, capture_output=True, text=True, check=True).stdout


@BOTH_LAYOUTS
def test_the_allowed_cpus_are_the_cgroups_cpuset(tmp_path: Path, files: dict[str, str]) -> None:
    assert shell_allowed_cpus(cgroup_tree(tmp_path, files)) == "0-191\n"


def test_without_a_cpuset_every_cpu_of_the_host_is_allowed(tmp_path: Path) -> None:
    assert shell_allowed_cpus(tmp_path) == f"0-{os.cpu_count() - 1}\n"
