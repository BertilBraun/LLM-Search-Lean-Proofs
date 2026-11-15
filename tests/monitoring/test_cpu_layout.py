import os
import subprocess
import sys
from pathlib import Path

import pytest
from cgroup_trees import V1_TREE, V2_TREE, cgroup_tree

from lean_search.monitoring.cpu_layout import (
    allowed_cpu_list,
    cpu_list_text,
    on_training_cpus,
    parse_cpu_list,
    server_cpu_list,
    shared_cores,
    thread_siblings,
    training_cpu_list,
)

ALLOWED_CPUS = tuple(sorted(os.sched_getaffinity(0)))


@pytest.mark.parametrize(
    ("text", "cpus"),
    [("3", (3,)), ("0-3", (0, 1, 2, 3)), ("6,0-1", (0, 1, 6)), ("0-6:3", (0, 3, 6))],
    ids=["one", "range", "unordered", "stride"],
)
def test_a_cpu_list_parses_as_taskset_reads_it(text: str, cpus: tuple[int, ...]) -> None:
    assert parse_cpu_list(text) == cpus


@pytest.mark.parametrize("text", ["", "a", "0-", "1,,2", "5-3", "0-6:0", " 0-3"])
def test_a_malformed_cpu_list_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="CPU"):
        parse_cpu_list(text)


def test_cpus_print_as_their_shortest_list() -> None:
    assert cpu_list_text((48, 49, 50, 144, 146, 147)) == "48-50,144,146-147"


@pytest.mark.parametrize("files", [V2_TREE, V1_TREE], ids=["v2", "v1"])
def test_the_allowed_cpus_are_the_cgroups_cpuset(tmp_path: Path, files: dict[str, str]) -> None:
    assert allowed_cpu_list(cgroup_tree(tmp_path, files)) == "0-191"


def test_without_a_cpuset_every_cpu_of_the_host_is_allowed(tmp_path: Path) -> None:
    assert allowed_cpu_list(tmp_path) == f"0-{(os.cpu_count() or 1) - 1}"


def test_servers_run_on_every_allowed_cpu_by_default(tmp_path: Path) -> None:
    assert server_cpu_list(cgroup_tree(tmp_path, V1_TREE)) == "0-191"


def test_servers_run_on_server_cpu_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_CPU_LIST", "0-47,96-143")
    assert server_cpu_list(cgroup_tree(tmp_path, V1_TREE)) == "0-47,96-143"


def test_training_runs_on_the_servers_cpus_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_CPU_LIST", "0-47,96-143")
    assert training_cpu_list(cgroup_tree(tmp_path, V1_TREE)) == "0-47,96-143"


def test_training_runs_on_training_cpu_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINING_CPU_LIST", "0-23,96-119")
    assert training_cpu_list(cgroup_tree(tmp_path, V1_TREE)) == "0-23,96-119"


@pytest.mark.skipif(len(ALLOWED_CPUS) < 2, reason="needs a CPU for the caller and another for the job")
def test_a_job_started_on_the_training_cpus_leaves_its_pinned_callers_cpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINING_CPU_LIST", str(ALLOWED_CPUS[-1]))
    job = on_training_cpus([sys.executable, "-c", "import os; print(sorted(os.sched_getaffinity(0)))"])
    pinned_caller = ["taskset", "--cpu-list", str(ALLOWED_CPUS[0])]
    result = subprocess.run([*pinned_caller, *job], capture_output=True, text=True, check=True)  # noqa: S603
    assert result.stdout == f"[{ALLOWED_CPUS[-1]}]\n"


def topology_tree(root: Path, siblings: dict[int, str]) -> Path:
    for cpu, text in siblings.items():
        path = root / f"cpu{cpu}" / "topology" / "thread_siblings_list"
        path.parent.mkdir(parents=True)
        path.write_text(f"{text}\n", encoding="utf-8")
    (root / "cpufreq").mkdir()
    return root


def test_the_kernels_thread_siblings_name_each_cpus_core(tmp_path: Path) -> None:
    root = topology_tree(tmp_path, {0: "0,2", 1: "1,3", 2: "0,2", 3: "1,3"})
    assert thread_siblings(root) == {0: (0, 2), 1: (1, 3), 2: (0, 2), 3: (1, 3)}


def test_two_threads_of_one_core_share_it() -> None:
    siblings = {0: (0, 2), 1: (1, 3), 2: (0, 2), 3: (1, 3)}
    assert shared_cores((0,), (2, 3), siblings) == [(0, 2)]


def test_cpus_on_other_cores_share_none() -> None:
    siblings = {0: (0, 2), 1: (1, 3), 2: (0, 2), 3: (1, 3)}
    assert shared_cores((0, 2), (1, 3), siblings) == []
