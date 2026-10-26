import os
from pathlib import Path

import pytest

from lean_search.monitoring.system_sampler import (
    CpuSnapshot,
    available_cores,
    cpu_usage,
    process_seconds,
)

TICKS = os.sysconf("SC_CLK_TCK")


def snapshot(monotonic: float, usage: float, processes: dict[int, float], throttled: int = 0) -> CpuSnapshot:
    return CpuSnapshot(
        monotonic, usage, periods=int(monotonic * 10), throttled_periods=throttled, process_seconds=processes
    )


def test_cores_used_is_cpu_time_over_wall_time() -> None:
    usage = cpu_usage(snapshot(0.0, 100.0, {}), snapshot(10.0, 400.0, {}))
    assert usage.cores_used == 30.0


def test_lean_cores_count_only_processes_seen_twice() -> None:
    usage = cpu_usage(snapshot(0.0, 0.0, {1: 5.0, 2: 9.0}), snapshot(10.0, 0.0, {1: 25.0, 3: 50.0}))
    assert usage.lean_cores_used == 2.0


def test_throttled_fraction_is_over_elapsed_periods() -> None:
    usage = cpu_usage(snapshot(0.0, 0.0, {}, throttled=0), snapshot(10.0, 0.0, {}, throttled=25))
    assert usage.throttled_fraction == 0.25


def write_stat(proc: Path, pid: int, name: str, user_ticks: int, system_ticks: int) -> None:
    directory = proc / str(pid)
    directory.mkdir()
    fields = ["S", "1", "1", "1", "0", "-1", "0", "0", "0", "0", "0", str(user_ticks), str(system_ticks), "0", "0"]
    (directory / "stat").write_text(f"{pid} ({name}) {' '.join(fields)}\n")


def test_process_seconds_sum_user_and_system_time(tmp_path: Path) -> None:
    write_stat(tmp_path, 7, "repl", user_ticks=3 * TICKS, system_ticks=TICKS)
    assert process_seconds(tmp_path, {"repl"}) == {7: 4.0}


def test_process_seconds_skip_other_names(tmp_path: Path) -> None:
    write_stat(tmp_path, 8, "python3", user_ticks=TICKS, system_ticks=0)
    assert process_seconds(tmp_path, {"repl"}) == {}


def test_process_names_may_contain_spaces_and_parentheses(tmp_path: Path) -> None:
    write_stat(tmp_path, 9, "lean (x) y", user_ticks=TICKS, system_ticks=0)
    assert process_seconds(tmp_path, {"lean (x) y"}) == {9: 1.0}


@pytest.mark.parametrize(("cpu_max", "cores"), [("4600000 100000", 46.0), ("150000 100000", 1.5)])
def test_available_cores_follow_the_cgroup_quota(tmp_path: Path, cpu_max: str, cores: float) -> None:
    (tmp_path / "cpu.max").write_text(cpu_max)
    assert available_cores(tmp_path) == cores


def test_unlimited_cgroup_has_every_cpu(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("max 100000")
    assert available_cores(tmp_path) == float(os.cpu_count() or 1)
