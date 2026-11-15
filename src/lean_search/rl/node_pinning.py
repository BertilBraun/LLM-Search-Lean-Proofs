"""The CPUs a study job runs on (DESIGN.md, "Follow-up study: controlled arms", "Load": the Lean side pinned below the
node's CPU quota through deployment/background.sh, identical for every arm and evaluation).

background.sh pins to BACKGROUND_CPU_LIST (taskset's CPU list, e.g. 48-95,144-191) or to the last BACKGROUND_CPUS of
all the host's CPUs (`nproc --all`; 32 when neither is set), never both. Servers run on SERVER_CPU_LIST and training
jobs on TRAINING_CPU_LIST (monitoring/cpu_layout.py). Before a launcher starts, the layout is checked: the background
set against the CPUs the process may use and against the cgroup quota with a reserve for the servers, no physical core
shared between the background set and the servers' or training jobs' CPUs; a background set that leaves less than
the reserve of the quota beside it is refused unless SERVER_RESERVE_CORES sets a smaller reserve (recorded). Each
session of a run records its CPUs, the layout and the cgroup's CPU counters (pinning.jsonl beside its results) and is
refused when its layout differs from the run's first session's, so an unpinned or differently pinned run shows and
cannot pass for the same.
"""

import dataclasses
import datetime
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lean_search.monitoring.cgroup import CGROUP_ROOT, CpuCounters, cpu_counters, cpu_quota_cores
from lean_search.monitoring.cpu_layout import (
    allowed_cpu_list,
    cpu_list_text,
    environment_setting,
    parse_cpu_list,
    server_cpu_list,
    shared_cores,
    training_cpu_list,
)
from lean_search.search.records import from_json_object, to_json

PINNING_FILE = "pinning.jsonl"
# background.sh's set when neither BACKGROUND_CPUS nor BACKGROUND_CPU_LIST is set.
DEFAULT_BACKGROUND_CPUS = 32
# Cores of the quota kept for the servers and the search orchestrator beside the background set (SERVER_RESERVE_CORES
# overrides it, recorded). On the 2026-11-15 node the 8 servers used under 4 cores beside Lean's 96 (quota 105.3).
DEFAULT_SERVER_RESERVE_CORES = 8.0


@dataclass(frozen=True)
class PinningRecord:
    recorded_at: str
    # The CPUs this process may run on, and how many the host has.
    affinity: tuple[int, ...]
    cpu_count: int
    # The cgroup's CPU quota in cores; None without one.
    quota_cores: float | None
    # The environment's BACKGROUND_CPUS and BACKGROUND_CPU_LIST; None when unset (the list also in older records).
    background_cpus: int | None
    background_cpu_list: str | None = None
    # Where servers and training jobs run (their settings or defaults) and what the cgroup's cpuset allows; None in
    # records from before them.
    server_cpu_list: str | None = None
    training_cpu_list: str | None = None
    allowed_cpu_list: str | None = None
    # The node environment file environment.sh sourced, and its sha256; None without one.
    node_environment: str | None = None
    node_environment_sha256: str | None = None
    # The cgroup's CPU counters when recorded: between two records, the CPU time used and the periods throttled.
    cpu_counters: CpuCounters | None = None
    # This session started with --allow-other-pinning on a layout other than the run's first session's.
    other_pinning_allowed: bool = False
    # SERVER_RESERVE_CORES when set: the quota's reserve beside the background set in place of the default.
    server_reserve_cores: float | None = None


@dataclass(frozen=True)
class PinningCheck:
    refusals: tuple[str, ...]
    warnings: tuple[str, ...]


def node_environment_file() -> Path | None:
    """The node environment file environment.sh sourced (it exports the path whether or not the file exists)."""
    path = environment_setting("LEAN_SEARCH_NODE_ENVIRONMENT")
    return Path(path) if path is not None and Path(path).is_file() else None


def current_pinning(cgroup: Path = CGROUP_ROOT) -> PinningRecord:
    background = environment_setting("BACKGROUND_CPUS")
    reserve = environment_setting("SERVER_RESERVE_CORES")
    node_environment = node_environment_file()
    return PinningRecord(
        recorded_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        affinity=tuple(sorted(os.sched_getaffinity(0))),
        cpu_count=os.cpu_count() or 0,
        quota_cores=cpu_quota_cores(cgroup),
        background_cpus=int(background) if background else None,
        background_cpu_list=environment_setting("BACKGROUND_CPU_LIST"),
        server_cpu_list=server_cpu_list(cgroup),
        training_cpu_list=training_cpu_list(cgroup),
        allowed_cpu_list=allowed_cpu_list(cgroup),
        node_environment=None if node_environment is None else str(node_environment),
        node_environment_sha256=None
        if node_environment is None
        else hashlib.sha256(node_environment.read_bytes()).hexdigest(),
        cpu_counters=cpu_counters(cgroup),
        server_reserve_cores=None if reserve is None else float(reserve),
    )


def append_pinning(directory: Path, record: PinningRecord) -> PinningRecord:
    """One line per session of a run: a resumed run may have run on other CPUs."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / PINNING_FILE).open("a", encoding="utf-8") as handle:
        handle.write(to_json(record) + "\n")
    return record


def read_pinning(directory: Path) -> list[PinningRecord]:
    path = directory / PINNING_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [from_json_object(PinningRecord, json.loads(line)) for line in lines if line.strip()]


def background_set(background_cpus: int | None, background_cpu_list: str | None, cpu_count: int) -> tuple[int, ...]:
    """The CPUs deployment/background.sh pins to: BACKGROUND_CPU_LIST, or the last BACKGROUND_CPUS of all the host's."""
    match background_cpus, background_cpu_list:
        case int(), str():
            raise ValueError("Set BACKGROUND_CPUS or BACKGROUND_CPU_LIST, not both (deployment/background.sh)")
        case None, str():
            return parse_cpu_list(background_cpu_list)
        case _:
            last = DEFAULT_BACKGROUND_CPUS if background_cpus is None else background_cpus
            return tuple(range(max(0, cpu_count - last), cpu_count))


def server_reserve_cores() -> float:
    reserve = environment_setting("SERVER_RESERVE_CORES")
    return DEFAULT_SERVER_RESERVE_CORES if reserve is None else float(reserve)


def pinning_check(record: PinningRecord, siblings: Mapping[int, tuple[int, ...]], reserve_cores: float) -> PinningCheck:
    """Whether the environment's layout will do for a study job. Refused: not exactly one of BACKGROUND_CPUS and
    BACKGROUND_CPU_LIST, a set outside the CPUs this process may use, a background set not below the quota, or one
    sharing a physical core with the servers' or training jobs' CPUs (a warning instead for those that are every CPU
    the cgroup allows on a node without a node environment, the old single-socket layout), or a background set that
    leaves less of the quota than `reserve_cores` beside it. A warning: no topology (`siblings` empty), so every CPU
    counts as a core of its own. ValueError for a malformed CPU list."""
    if (record.background_cpus is None) == (record.background_cpu_list is None):
        both = record.background_cpus is not None
        hint = " (both set: BACKGROUND_CPU_LIST= or BACKGROUND_CPUS= unsets the node environment's)" if both else ""
        return PinningCheck(
            (f"Set exactly one of BACKGROUND_CPUS and BACKGROUND_CPU_LIST{hint}: every study job runs pinned.",), ()
        )
    assert record.server_cpu_list is not None and record.training_cpu_list is not None
    assert record.allowed_cpu_list is not None
    pinned = background_set(record.background_cpus, record.background_cpu_list, record.cpu_count)
    refusals = []
    warnings = []
    outside = sorted(set(pinned) - set(record.affinity))
    if outside:
        refusals.append(f"background.sh would pin CPUs this process may not use: {cpu_list_text(outside)}")
    quota = record.quota_cores
    if quota is not None and len(pinned) >= quota:
        refusals.append(f"background.sh would pin {len(pinned)} CPUs, not below the cgroup quota of {quota:g} cores")
    elif quota is not None and len(pinned) + reserve_cores > quota:
        refusals.append(
            f"background.sh's {len(pinned)} CPUs leave {quota - len(pinned):.1f} cores of the {quota:g}-core quota "
            f"beside them, less than the {reserve_cores:g} reserved for the servers and the orchestrator: once Lean "
            "fills its CPUs the cgroup throttles the GPU feeders with it. Pin fewer CPUs (BACKGROUND_CPU_LIST), or set "
            "SERVER_RESERVE_CORES to the cores the servers and the orchestrator were measured to use (recorded in "
            "each run's pinning.jsonl)"
        )
    if not siblings:
        warnings.append(
            "The kernel shows no CPU topology here (no /sys/devices/system/cpu/cpu<N>/topology/thread_siblings_list, "
            "as some containers hide it): every CPU counts as a physical core of its own, so a Lean CPU sharing a core "
            "with a server's or training job's goes unnoticed; check the lists against the host's topology"
        )
    old_default = record.node_environment is None
    allowed = set(parse_cpu_list(record.allowed_cpu_list))
    for name, cpu_list in (
        ("SERVER_CPU_LIST", record.server_cpu_list),
        ("TRAINING_CPU_LIST", record.training_cpu_list),
    ):
        cpus = parse_cpu_list(cpu_list)
        outside = sorted(set(cpus) - set(record.affinity))
        if outside:
            refusals.append(f"{name}={cpu_list} names CPUs this process may not use: {cpu_list_text(outside)}")
        cores = shared_cores(pinned, cpus, siblings)
        if not cores:
            continue
        shared = f"{name}={cpu_list} shares {len(cores)} physical cores with background.sh's CPUs"
        if old_default and set(cpus) == allowed:
            warnings.append(f"{shared}: every CPU the cgroup allows, as on a node without a node environment")
        else:
            refusals.append(f"{shared} ({cpu_list_text(cpu for core in cores for cpu in core)})")
    return PinningCheck(tuple(refusals), tuple(warnings))


def pinned_as_background(record: PinningRecord) -> bool:
    """The process runs on exactly background.sh's set for its BACKGROUND_CPUS or BACKGROUND_CPU_LIST."""
    if record.background_cpus is None and record.background_cpu_list is None:
        return False
    return record.affinity == background_set(record.background_cpus, record.background_cpu_list, record.cpu_count)


def layout_differences(first: PinningRecord, current: PinningRecord) -> list[str]:
    """How the current session's CPU layout differs from the run's first: its CPUs, the host's, the quota and the
    settings (the servers' and training jobs' lists only where the first record has them)."""
    compared: list[tuple[str, object, object]] = [
        ("affinity", cpu_list_text(first.affinity), cpu_list_text(current.affinity)),
        ("CPU count", first.cpu_count, current.cpu_count),
        ("cgroup quota", first.quota_cores, current.quota_cores),
        ("BACKGROUND_CPUS", first.background_cpus, current.background_cpus),
        ("BACKGROUND_CPU_LIST", first.background_cpu_list, current.background_cpu_list),
    ]
    if first.server_cpu_list is not None:
        compared.append(("SERVER_CPU_LIST", first.server_cpu_list, current.server_cpu_list))
    if first.training_cpu_list is not None:
        compared.append(("TRAINING_CPU_LIST", first.training_cpu_list, current.training_cpu_list))
    return [f"{label} {before} -> {now}" for label, before, now in compared if before != now]


def session_refusals(directory: Path, record: PinningRecord, require_background: bool) -> list[str]:
    """Why a session of the run in `directory` may not start with this pinning: not pinned through background.sh
    (when required), or a layout other than the run's first session's without --allow-other-pinning."""
    refusals = []
    if require_background and not pinned_as_background(record):
        refusals.append(
            "Run it pinned through deployment/background.sh (the node environment's BACKGROUND_CPU_LIST, or "
            "BACKGROUND_CPUS=<n>)."
        )
    earlier = read_pinning(directory)
    differences = layout_differences(earlier[0], record) if earlier else []
    if differences and not record.other_pinning_allowed:
        refusals.append(
            f"This session's CPU layout differs from the run's first session's ({'; '.join(differences)}): resume it "
            "on that layout, or with --allow-other-pinning (recorded in pinning.jsonl)."
        )
    return refusals


def record_session_pinning(directory: Path, require_background: bool, allow_other_pinning: bool) -> list[str]:
    """Appends this session's pinning to the run's pinning.jsonl unless refused (`session_refusals`); the refusals."""
    record = dataclasses.replace(current_pinning(), other_pinning_allowed=allow_other_pinning)
    refusals = session_refusals(directory, record, require_background)
    if not refusals:
        append_pinning(directory, record)
    return refusals
