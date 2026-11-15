"""The node's CPUs as the deployment scripts lay them out (deployment/README.md, "CPU budget", "Node environment"): CPU
lists in taskset's syntax, the CPUs the cgroup's cpuset allows, where servers and training jobs run, and which logical
CPUs share a physical core."""

import os
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path

from lean_search.monitoring.cgroup import CGROUP_ROOT

CPU_DEVICES_ROOT = Path("/sys/devices/system/cpu")
CPU_RANGE = r"\d+(-\d+(:[1-9]\d*)?)?"
CPU_LIST_PATTERN = re.compile(rf"{CPU_RANGE}(,{CPU_RANGE})*")


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


def allowed_cpu_list(root: Path = CGROUP_ROOT) -> str:
    """The CPUs the cgroup's cpuset allows (v2 cpuset.cpus.effective, v1 cpuset/cpuset.cpus), else all the host's:
    deployment/cgroup.sh's cgroup_allowed_cpus, never the caller's affinity."""
    v2_cpus = root / "cpuset.cpus.effective"
    v1_cpus = root / "cpuset" / "cpuset.cpus"
    text = ""
    if v2_cpus.exists():
        text = v2_cpus.read_text().strip()
    elif v1_cpus.exists():
        text = v1_cpus.read_text().strip()
    return text or f"0-{(os.cpu_count() or 1) - 1}"


def server_cpu_list(root: Path = CGROUP_ROOT) -> str:
    """Where deployment/serve_model.sh runs a server: SERVER_CPU_LIST, else every CPU the cgroup allows."""
    return environment_setting("SERVER_CPU_LIST") or allowed_cpu_list(root)


def training_cpu_list(root: Path = CGROUP_ROOT) -> str:
    """Where training jobs and CPU merges run: TRAINING_CPU_LIST, else the servers' CPUs (the training GPUs' servers
    are stopped or asleep while it trains)."""
    return environment_setting("TRAINING_CPU_LIST") or server_cpu_list(root)


def on_training_cpus(arguments: Sequence[str], root: Path = CGROUP_ROOT) -> list[str]:
    """The command with its affinity reset to the training CPUs: a caller pinned to Lean's CPUs passes them on."""
    return ["taskset", "--cpu-list", training_cpu_list(root), *arguments]


def thread_siblings(root: Path = CPU_DEVICES_ROOT) -> dict[int, tuple[int, ...]]:
    """Each logical CPU's physical core, as the CPUs on it (itself included), from the kernel's topology."""
    return {
        int(path.parent.parent.name.removeprefix("cpu")): parse_cpu_list(path.read_text().strip())
        for path in root.glob("cpu[0-9]*/topology/thread_siblings_list")
    }


def shared_cores(
    first: Collection[int], second: Collection[int], siblings: Mapping[int, tuple[int, ...]]
) -> list[tuple[int, ...]]:
    """The physical cores both sets run on (a CPU without a topology entry is a core of its own)."""
    cores_of_first = {siblings.get(cpu, (cpu,)) for cpu in first}
    return sorted(cores_of_first & {siblings.get(cpu, (cpu,)) for cpu in second})
