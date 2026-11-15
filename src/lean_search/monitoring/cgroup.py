"""The container's CPU quota, CPU counters and memory from its cgroup, under cgroup v2 (one unified hierarchy:
cpu.max, cpu.stat, memory.*) or v1 (one mount per controller: cpu/, cpuacct/, memory/). Each reader returns None
when its controller's files are absent."""

from dataclasses import dataclass
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
# v1 reports no memory limit as PAGE_COUNTER_MAX pages, just under 2**63 bytes.
V1_UNLIMITED_MEMORY_BYTES = 1 << 62


@dataclass(frozen=True)
class CpuCounters:
    usage_seconds: float
    # Enforcement periods of the quota so far, and those in which the cgroup was throttled.
    periods: int
    throttled_periods: int


def stat_fields(path: Path) -> dict[str, int]:
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def cpu_quota_cores(root: Path = CGROUP_ROOT) -> float | None:
    """The CPU quota in cores; None when unlimited."""
    cpu_max = root / "cpu.max"
    v1_quota = root / "cpu" / "cpu.cfs_quota_us"
    if cpu_max.exists():
        quota, period = cpu_max.read_text().split()
        return None if quota == "max" else int(quota) / int(period)
    if v1_quota.exists():
        quota_microseconds = int(v1_quota.read_text())
        period_microseconds = int((root / "cpu" / "cpu.cfs_period_us").read_text())
        return None if quota_microseconds == -1 else quota_microseconds / period_microseconds
    return None


def cpu_counters(root: Path = CGROUP_ROOT) -> CpuCounters | None:
    v2_stat = root / "cpu.stat"
    v1_usage = root / "cpuacct" / "cpuacct.usage"
    if v2_stat.exists():
        stat = stat_fields(v2_stat)
        # v2 lists the periods only while the cpu controller is enabled.
        return CpuCounters(stat["usage_usec"] / 1e6, stat.get("nr_periods", 0), stat.get("nr_throttled", 0))
    if v1_usage.exists():
        stat = stat_fields(root / "cpu" / "cpu.stat")
        return CpuCounters(int(v1_usage.read_text()) / 1e9, stat["nr_periods"], stat["nr_throttled"])
    return None


def memory_limit_bytes(root: Path = CGROUP_ROOT) -> int | None:
    """The memory limit; None when unlimited."""
    v2_limit = root / "memory.max"
    v1_limit = root / "memory" / "memory.limit_in_bytes"
    if v2_limit.exists():
        limit = v2_limit.read_text().strip()
        return None if limit == "max" else int(limit)
    if v1_limit.exists():
        limit_bytes = int(v1_limit.read_text())
        return None if limit_bytes >= V1_UNLIMITED_MEMORY_BYTES else limit_bytes
    return None


def memory_used_bytes(root: Path = CGROUP_ROOT) -> int | None:
    """All memory charged to the cgroup, page cache included."""
    v2_current = root / "memory.current"
    v1_usage = root / "memory" / "memory.usage_in_bytes"
    if v2_current.exists():
        return int(v2_current.read_text())
    if v1_usage.exists():
        return int(v1_usage.read_text())
    return None


def anonymous_memory_bytes(root: Path = CGROUP_ROOT) -> int | None:
    """Anonymous memory of the cgroup and its children; page cache and shared memory are not counted."""
    v2_stat = root / "memory.stat"
    v1_stat = root / "memory" / "memory.stat"
    if v2_stat.exists():
        return stat_fields(v2_stat)["anon"]
    if v1_stat.exists():
        # v1's rss leaves out child cgroups; total_rss counts them, as v2's anon does.
        return stat_fields(v1_stat)["total_rss"]
    return None
