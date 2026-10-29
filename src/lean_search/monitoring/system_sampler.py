"""System usage of the node for the `system` family: GPUs (if NVML is available), the cgroup's CPU and memory, the CPU
time and private memory of the Lean REPL processes, the vLLM processes' memory, and the money spent at an hourly
price."""

import math
import os
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from lean_search.monitoring.families import SystemUsage
from lean_search.monitoring.store import MetricsWriter, RunReader

CGROUP = Path("/sys/fs/cgroup")
PROC = Path("/proc")
LEAN_PROCESS_NAMES = ("repl", "lean")
# vLLM's API servers run as python with vllm on the command line; its engine processes are named VLLM::<role>.
VLLM_COMMAND_MARKER = b"vllm"
VLLM_PROCESS_PREFIX = "VLLM"


@dataclass(frozen=True)
class CpuSnapshot:
    monotonic: float
    usage_seconds: float
    periods: int
    throttled_periods: int
    # utime + stime of each matching process, by pid.
    process_seconds: Mapping[int, float]


@dataclass(frozen=True)
class CpuUsage:
    cores_used: float
    lean_cores_used: float
    throttled_fraction: float


@dataclass(frozen=True)
class HostMemory:
    total_bytes: int
    available_bytes: int
    # Private (anonymous) resident memory per Lean process: shared Mathlib .olean mappings are not counted.
    lean_private_bytes: tuple[int, ...]
    vllm_private_bytes: int


@dataclass(frozen=True)
class GpuUsage:
    utilization: tuple[float, ...]
    memory_used_gib: tuple[float, ...]
    memory_total_gib: tuple[float, ...]
    power_watts: tuple[float, ...]


def process_seconds(proc: Path, names: Collection[str]) -> dict[int, float]:
    ticks = os.sysconf("SC_CLK_TCK")
    seconds = {}
    for stat in proc.glob("[0-9]*/stat"):
        try:
            text = stat.read_text()
        except OSError:
            continue
        # The command name is in parentheses and may itself contain spaces or parentheses.
        name = text[text.index("(") + 1 : text.rindex(")")]
        if name in names:
            fields = text[text.rindex(")") + 2 :].split()
            seconds[int(stat.parent.name)] = (int(fields[11]) + int(fields[12])) / ticks
    return seconds


def cgroup_cpu(cgroup: Path) -> dict[str, int]:
    path = cgroup / "cpu.stat"
    if not path.exists():
        return {}
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def cpu_snapshot(cgroup: Path, proc: Path, names: Collection[str]) -> CpuSnapshot:
    stat = cgroup_cpu(cgroup)
    return CpuSnapshot(
        monotonic=time.monotonic(),
        usage_seconds=stat["usage_usec"] / 1e6 if "usage_usec" in stat else proc_total_seconds(proc),
        periods=stat.get("nr_periods", 0),
        throttled_periods=stat.get("nr_throttled", 0),
        process_seconds=process_seconds(proc, names),
    )


def proc_total_seconds(proc: Path) -> float:
    fields = (proc / "stat").read_text().splitlines()[0].split()[1:]
    # user, nice, system; idle and iowait excluded.
    return (int(fields[0]) + int(fields[1]) + int(fields[2])) / os.sysconf("SC_CLK_TCK")


def cpu_usage(first: CpuSnapshot, second: CpuSnapshot) -> CpuUsage:
    seconds = second.monotonic - first.monotonic
    assert seconds > 0
    # Processes that started or ended in between count only over the part both snapshots saw.
    lean = sum(
        second.process_seconds[pid] - first.process_seconds[pid]
        for pid in second.process_seconds.keys() & first.process_seconds.keys()
    )
    periods = second.periods - first.periods
    return CpuUsage(
        cores_used=(second.usage_seconds - first.usage_seconds) / seconds,
        lean_cores_used=lean / seconds,
        throttled_fraction=(second.throttled_periods - first.throttled_periods) / periods if periods > 0 else 0.0,
    )


def available_cores(cgroup: Path) -> float:
    path = cgroup / "cpu.max"
    if path.exists():
        quota, period = path.read_text().split()
        if quota != "max":
            return int(quota) / int(period)
    return float(os.cpu_count() or 1)


def memory_used_gib(cgroup: Path, proc: Path) -> float:
    stat = cgroup / "memory.stat"
    if stat.exists():
        anonymous = next(int(line.split()[1]) for line in stat.read_text().splitlines() if line.startswith("anon "))
        return anonymous / 2**30
    info = {line.split(":")[0]: int(line.split()[1]) for line in (proc / "meminfo").read_text().splitlines()}
    return (info["MemTotal"] - info["MemAvailable"]) / 2**20


def memory_limit_bytes(cgroup: Path, host_total: int) -> int:
    path = cgroup / "memory.max"
    if path.exists() and (limit := path.read_text().strip()) != "max":
        return min(int(limit), host_total)
    return host_total


class PrivateMemory(NamedTuple):
    lean_bytes: tuple[int, ...]
    vllm_bytes: int


def private_memory(proc: Path, lean_names: Collection[str]) -> PrivateMemory:
    """RssAnon of every Lean process, and the sum over vLLM's processes."""
    lean = []
    vllm = 0
    for status in proc.glob("[0-9]*/status"):
        try:
            text = status.read_text()
            command_line = (status.parent / "cmdline").read_bytes()
        except OSError:
            continue
        fields = {key: value.strip() for key, _, value in (line.partition(":") for line in text.splitlines())}
        private = int(fields.get("RssAnon", "0 kB").split()[0]) * 1024
        if fields["Name"] in lean_names:
            lean.append(private)
        elif fields["Name"].startswith(VLLM_PROCESS_PREFIX) or VLLM_COMMAND_MARKER in command_line:
            vllm += private
    return PrivateMemory(tuple(lean), vllm)


def host_memory(cgroup: Path, proc: Path, lean_names: Collection[str]) -> HostMemory:
    lines = (proc / "meminfo").read_text().splitlines()
    info = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in lines}
    total = memory_limit_bytes(cgroup, info["MemTotal"])
    available = min(info["MemAvailable"], total - round(memory_used_gib(cgroup, proc) * 2**30))
    processes = private_memory(proc, lean_names)
    return HostMemory(total, available, processes.lean_bytes, processes.vllm_bytes)


def percentile_90(values: Collection[int]) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1] if ordered else 0


class GpuReader:
    def __init__(self) -> None:
        try:
            import pynvml
        except ImportError:
            self.handles = []
            return
        self.pynvml = pynvml
        pynvml.nvmlInit()
        self.handles = [pynvml.nvmlDeviceGetHandleByIndex(index) for index in range(pynvml.nvmlDeviceGetCount())]

    def usage(self) -> GpuUsage:
        if not self.handles:
            return GpuUsage((), (), (), ())
        nvml = self.pynvml
        memory = [nvml.nvmlDeviceGetMemoryInfo(handle) for handle in self.handles]
        return GpuUsage(
            utilization=tuple(float(nvml.nvmlDeviceGetUtilizationRates(handle).gpu) for handle in self.handles),
            memory_used_gib=tuple(info.used / 2**30 for info in memory),
            memory_total_gib=tuple(info.total / 2**30 for info in memory),
            power_watts=tuple(nvml.nvmlDeviceGetPowerUsage(handle) / 1000 for handle in self.handles),
        )


def run_started_at(run_directory: Path, default: float) -> float:
    """The first system record's time, so the cost survives restarts of the sampler."""
    times = RunReader(run_directory).series(SystemUsage.family).times
    return times[0] if times else default


def record_system(
    run_directory: Path, interval_seconds: float, hourly_price: float, process_names: Collection[str]
) -> None:
    writer = MetricsWriter(run_directory)
    started_at = run_started_at(run_directory, time.time())
    gpus = GpuReader()
    cores = available_cores(CGROUP)
    previous = cpu_snapshot(CGROUP, PROC, process_names)
    while True:
        time.sleep(interval_seconds)
        current = cpu_snapshot(CGROUP, PROC, process_names)
        cpu = cpu_usage(previous, current)
        gpu = gpus.usage()
        memory = host_memory(CGROUP, PROC, process_names)
        now = time.time()
        writer.write(
            SystemUsage(
                gpu_utilization=gpu.utilization,
                gpu_memory_used_gib=gpu.memory_used_gib,
                gpu_memory_total_gib=gpu.memory_total_gib,
                gpu_power_watts=gpu.power_watts,
                cpu_cores_used=cpu.cores_used,
                cpu_cores_available=cores,
                lean_cores_used=cpu.lean_cores_used,
                cpu_throttled_fraction=cpu.throttled_fraction,
                memory_used_gib=memory_used_gib(CGROUP, PROC),
                hourly_price=hourly_price,
                cost_so_far=hourly_price * (now - started_at) / 3600,
                memory_total_gib=memory.total_bytes / 2**30,
                memory_available_gib=memory.available_bytes / 2**30,
                lean_processes=len(memory.lean_private_bytes),
                lean_private_memory_gib=sum(memory.lean_private_bytes) / 2**30,
                lean_private_memory_p90_gib=percentile_90(memory.lean_private_bytes) / 2**30,
                vllm_private_memory_gib=memory.vllm_private_bytes / 2**30,
            ),
            record_time=now,
        )
        previous = current
