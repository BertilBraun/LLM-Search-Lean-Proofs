"""Fake cgroup trees: v2 as on the earlier nodes, v1 as on the Vast.ai node of 2026-11-15 (one mount per controller)."""

from pathlib import Path

V2_TREE = {
    "cgroup.controllers": "cpuset cpu io memory pids",
    "cpu.max": "6100000 100000",
    "cpu.stat": "usage_usec 5000000\nuser_usec 4000000\nsystem_usec 1000000\nnr_periods 10\nnr_throttled 3\n"
    "throttled_usec 700",
    "memory.max": "128849018880",
    "memory.current": "8589934592",
    "memory.stat": "anon 3221225472\nfile 5368709120\nshmem 1048576",
}
V1_TREE = {
    "cpu/cpu.cfs_quota_us": "10532571",
    "cpu/cpu.cfs_period_us": "100000",
    "cpu/cpu.stat": "nr_periods 179768\nnr_throttled 4\nthrottled_time 0\nnr_bursts 0\nburst_time 0",
    "cpuacct/cpuacct.usage": "5000000000",
    "memory/memory.limit_in_bytes": "196109926400",
    "memory/memory.usage_in_bytes": "8589934592",
    "memory/memory.stat": "cache 5368709120\nrss 2147483648\nrss_huge 0\nshmem 1048576\nmapped_file 0\n"
    "total_cache 5368709120\ntotal_rss 3221225472\ntotal_rss_huge 0",
}


def cgroup_tree(root: Path, files: dict[str, str]) -> Path:
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n")
    return root
