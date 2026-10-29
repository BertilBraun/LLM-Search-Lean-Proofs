import os
from pathlib import Path

import pytest

from lean_search.monitoring.system_sampler import (
    CpuSnapshot,
    available_cores,
    cpu_usage,
    host_memory,
    memory_limit_bytes,
    percentile_90,
    private_memory,
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


def write_status(proc: Path, pid: int, name: str, private_kib: int, command_line: bytes = b"") -> None:
    directory = proc / str(pid)
    directory.mkdir()
    status = f"Name:\t{name}\nVmRSS:\t{private_kib + 4000} kB\nRssAnon:\t{private_kib} kB\n"
    (directory / "status").write_text(status)
    (directory / "cmdline").write_bytes(command_line)


def test_lean_private_memory_is_per_repl_process(tmp_path: Path) -> None:
    write_status(tmp_path, 7, "repl", 1024)
    write_status(tmp_path, 8, "python3", 2048)
    assert private_memory(tmp_path, {"repl"}).lean_bytes == (1 << 20,)


@pytest.mark.parametrize(
    ("name", "command_line"),
    [("VLLM::EngineCor", b"python3\0-c\0spawn"), ("python3", b"python3\0-m\0vllm.entrypoints.openai.api_server")],
)
def test_vllm_processes_count_by_name_or_command_line(tmp_path: Path, name: str, command_line: bytes) -> None:
    write_status(tmp_path, 9, name, 1024, command_line)
    assert private_memory(tmp_path, {"repl"}).vllm_bytes == 1 << 20


@pytest.mark.parametrize(("memory_max", "limit"), [("1073741824", 1 << 30), ("max", 4 << 30)])
def test_the_memory_limit_follows_the_cgroup(tmp_path: Path, memory_max: str, limit: int) -> None:
    (tmp_path / "memory.max").write_text(memory_max + "\n")
    assert memory_limit_bytes(tmp_path, 4 << 30) == limit


def test_available_memory_is_the_limit_less_the_cgroups_anonymous_memory(tmp_path: Path) -> None:
    cgroup, proc = tmp_path / "cgroup", tmp_path / "proc"
    cgroup.mkdir()
    proc.mkdir()
    (cgroup / "memory.max").write_text(f"{8 << 30}\n")
    (cgroup / "memory.stat").write_text(f"anon {3 << 30}\nfile {1 << 30}\n")
    (proc / "meminfo").write_text(f"MemTotal: {64 << 20} kB\nMemAvailable: {60 << 20} kB\n")
    assert host_memory(cgroup, proc, {"repl"}).available_bytes == 5 << 30


def test_percentile_90_of_ten_values_is_the_ninth() -> None:
    assert percentile_90(range(1, 11)) == 9
