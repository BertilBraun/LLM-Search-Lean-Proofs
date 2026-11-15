"""The CPUs a study job runs on (DESIGN.md, "Follow-up study: controlled arms", "Load": the Lean side pinned below the
node's CPU quota through deployment/background.sh, identical for every arm and evaluation).

background.sh pins to BACKGROUND_CPU_LIST (taskset's CPU list, e.g. 48-95,144-191) or to the last BACKGROUND_CPUS of
all the host's CPUs (`nproc --all`; 32 when neither is set), never both. Before a launcher starts, that set is checked
against the CPUs the process may use and against the cgroup quota; each run then records the CPUs it actually ran on
(pinning.jsonl beside its results), so an unpinned or differently pinned run shows.
"""

import datetime
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lean_search.monitoring.cgroup import cpu_quota_cores
from lean_search.search.records import from_json_object, to_json

PINNING_FILE = "pinning.jsonl"
# background.sh's set when neither BACKGROUND_CPUS nor BACKGROUND_CPU_LIST is set.
DEFAULT_BACKGROUND_CPUS = 32
CPU_RANGE = r"\d+(-\d+(:[1-9]\d*)?)?"
CPU_LIST_PATTERN = re.compile(rf"{CPU_RANGE}(,{CPU_RANGE})*")


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


def parse_cpu_list(text: str) -> tuple[int, ...]:
    """taskset's --cpu-list syntax (48-95,144-191; 0-10:2 is every second CPU), sorted; ValueError for anything else."""
    if not CPU_LIST_PATTERN.fullmatch(text):
        raise ValueError(f"Not a CPU list such as 48-95,144-191: {text!r}")
    cpus: set[int] = set()
    for part in text.split(","):
        first, _, rest = part.partition("-")
        last, _, stride = rest.partition(":")
        if last and int(last) < int(first):
            raise ValueError(f"The CPU range {part!r} ends before it starts")
        cpus.update(range(int(first), int(last or first) + 1, int(stride or 1)))
    return tuple(sorted(cpus))


def cpu_list_text(cpus: Iterable[int]) -> str:
    """The shortest CPU list for the CPUs, e.g. 48-95,144-191."""
    ranges: list[list[int]] = []
    for cpu in sorted(cpus):
        if ranges and ranges[-1][1] == cpu - 1:
            ranges[-1][1] = cpu
        else:
            ranges.append([cpu, cpu])
    return ",".join(str(first) if first == last else f"{first}-{last}" for first, last in ranges)


def environment_setting(name: str) -> str | None:
    """An environment variable; None when unset or empty (an empty one is how a command unsets an exported one)."""
    return os.environ.get(name) or None


def current_pinning() -> PinningRecord:
    background = environment_setting("BACKGROUND_CPUS")
    return PinningRecord(
        recorded_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        affinity=tuple(sorted(os.sched_getaffinity(0))),
        cpu_count=os.cpu_count() or 0,
        quota_cores=cpu_quota_cores(),
        background_cpus=int(background) if background else None,
        background_cpu_list=environment_setting("BACKGROUND_CPU_LIST"),
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


def pinning_refusals(record: PinningRecord) -> list[str]:
    """Why the environment's pinning would not do for a study job: not exactly one of BACKGROUND_CPUS and
    BACKGROUND_CPU_LIST set, or background.sh's set outside the CPUs this process may use or not smaller than the quota
    (the pinned job would leave the servers nothing)."""
    if (record.background_cpus is None) == (record.background_cpu_list is None):
        return [
            "Set exactly one of BACKGROUND_CPUS and BACKGROUND_CPU_LIST: every study job runs pinned (DESIGN.md, Load)."
        ]
    pinned = background_set(record.background_cpus, record.background_cpu_list, record.cpu_count)
    refusals = []
    outside = sorted(set(pinned) - set(record.affinity))
    if outside:
        refusals.append(f"background.sh would pin CPUs this process may not use: {cpu_list_text(outside)}")
    if record.quota_cores is not None and len(pinned) >= record.quota_cores:
        refusals.append(
            f"background.sh would pin {len(pinned)} CPUs, not below the cgroup quota of {record.quota_cores:g} cores"
        )
    return refusals


def pinned_as_background(record: PinningRecord) -> bool:
    """The process runs on exactly background.sh's set for its BACKGROUND_CPUS or BACKGROUND_CPU_LIST."""
    if record.background_cpus is None and record.background_cpu_list is None:
        return False
    return record.affinity == background_set(record.background_cpus, record.background_cpu_list, record.cpu_count)
