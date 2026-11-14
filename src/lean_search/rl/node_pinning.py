"""The CPUs a study job runs on (DESIGN.md, "Follow-up study: controlled arms", "Load": the Lean side pinned below the
node's CPU quota through deployment/background.sh, identical for every arm and evaluation).

background.sh pins to the last BACKGROUND_CPUS of all the host's CPUs (`nproc --all`). Before a launcher starts, that
set is checked against the CPUs the process may use and against the cgroup quota; each run then records the CPUs it
actually ran on (pinning.jsonl beside its results), so an unpinned or differently pinned run shows.
"""

import datetime
import json
import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from lean_search.search.records import from_json_object, to_json

CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
PINNING_FILE = "pinning.jsonl"


@dataclass(frozen=True)
class PinningRecord:
    recorded_at: str
    # The CPUs this process may run on, and how many the host has.
    affinity: tuple[int, ...]
    cpu_count: int
    # The cgroup's CPU quota in cores; None without one.
    quota_cores: float | None
    # The environment's BACKGROUND_CPUS; None when unset.
    background_cpus: int | None


def quota_cores(cpu_max_text: str) -> float | None:
    """cgroup v2's cpu.max ("<quota> <period>" or "max <period>") in cores."""
    quota, period = cpu_max_text.split()
    return None if quota == "max" else int(quota) / int(period)


def current_pinning() -> PinningRecord:
    background = os.environ.get("BACKGROUND_CPUS")
    return PinningRecord(
        recorded_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        affinity=tuple(sorted(os.sched_getaffinity(0))),
        cpu_count=os.cpu_count() or 0,
        quota_cores=quota_cores(CPU_MAX.read_text(encoding="utf-8")) if CPU_MAX.exists() else None,
        background_cpus=int(background) if background else None,
    )


def append_pinning(directory: Path) -> PinningRecord:
    """One line per session of a run: a resumed run may have run on other CPUs."""
    record = current_pinning()
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


def background_set(background_cpus: int, cpu_count: int) -> tuple[int, ...]:
    """The CPUs deployment/background.sh pins to: the last `background_cpus` of all the host's."""
    return tuple(range(cpu_count - background_cpus, cpu_count))


def pinning_refusals(background_cpus: int, cpu_count: int, allowed: Collection[int], quota: float | None) -> list[str]:
    """Why background.sh's set would not do: outside the CPUs this process may use, or not below the quota (the
    pinned job would leave the unpinned servers nothing)."""
    pinned = background_set(background_cpus, cpu_count)
    refusals = []
    outside = sorted(set(pinned) - set(allowed))
    if outside:
        refusals.append(f"background.sh would pin CPUs this process may not use: {outside}")
    if quota is not None and background_cpus >= quota:
        refusals.append(f"BACKGROUND_CPUS={background_cpus} is not below the cgroup quota of {quota:g} cores")
    return refusals


def pinned_as_background(record: PinningRecord) -> bool:
    """The process runs on exactly background.sh's set for its BACKGROUND_CPUS."""
    return record.background_cpus is not None and record.affinity == background_set(
        record.background_cpus, record.cpu_count
    )
