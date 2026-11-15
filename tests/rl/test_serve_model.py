"""deployment/serve_model.sh with a stand-in for vLLM: the server runs on SERVER_CPU_LIST (by default every CPU the
cgroup allows) whatever its caller's affinity, at its caller's niceness (with a warning when not 0), <name>.cpus records
both, and its pid file stays trusted through the taskset it is started under."""

import contextlib
import json
import os
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from server_process_fakes import fake_vllm_server_executable

from lean_search.monitoring.cpu_layout import cpu_list_text

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
DEPLOYMENT_DIRECTORY = REPOSITORY_DIRECTORY / "deployment"
NAME = "policy-gpu0"
ALLOWED_CPUS = tuple(sorted(os.sched_getaffinity(0)))
# The caller runs on the first allowed CPU, the server on the others.
PINNED_CALLER = ["taskset", "--cpu-list", str(ALLOWED_CPUS[0])]
NICED_CALLER = [*PINNED_CALLER, "nice", "-n", "19"]
SERVER_CPUS = ALLOWED_CPUS[1:]
SERVER_CPU_LIST = ",".join(map(str, SERVER_CPUS))

pytestmark = pytest.mark.skipif(len(ALLOWED_CPUS) < 2, reason="needs a CPU for the caller and one for the server")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def server_environment(directory: Path, settings: dict[str, str]) -> dict[str, str]:
    return os.environ | {
        "LEAN_SEARCH_RUNS": str(directory / "runs"),
        "LEAN_SEARCH_VLLM_EXECUTABLE": str(fake_vllm_server_executable(directory)),
        "SERVER_START_TIMEOUT": "60",
        "HF_HUB_OFFLINE": "1",
        **settings,
    }


@contextlib.contextmanager
def started_server(
    directory: Path, caller: list[str], settings: dict[str, str]
) -> Iterator[subprocess.CompletedProcess[str]]:
    """serve_model.sh run by `caller` (a taskset and nice prefix); the server is stopped afterwards."""
    weights = directory / "weights"
    weights.mkdir()
    (weights / "config.json").write_text(json.dumps({"model_type": "gpt2"}), encoding="utf-8")
    environment = server_environment(directory, settings)
    command = [*caller, "bash", str(DEPLOYMENT_DIRECTORY / "serve_model.sh"), NAME, str(weights), "0", str(free_port())]
    try:
        yield subprocess.run(command, env=environment, capture_output=True, text=True, check=False, timeout=120)  # noqa: S603
    finally:
        stop = ["bash", str(DEPLOYMENT_DIRECTORY / "stop_model.sh"), NAME]
        subprocess.run(stop, env=environment, capture_output=True, check=False)  # noqa: S603


def server_process_id(directory: Path) -> int:
    return int((directory / "runs" / "servers" / f"{NAME}.pid").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pinned_start(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A server started by a caller pinned to another CPU, with SERVER_CPU_LIST set: its directory."""
    directory = tmp_path_factory.mktemp("serve_model")
    with started_server(directory, PINNED_CALLER, {"SERVER_CPU_LIST": SERVER_CPU_LIST}) as result:
        assert result.returncode == 0, result.stderr
        yield directory


def test_a_server_started_by_a_pinned_caller_runs_on_server_cpu_list(pinned_start: Path) -> None:
    assert os.sched_getaffinity(server_process_id(pinned_start)) == set(SERVER_CPUS)


def test_a_server_start_records_its_cpus_and_niceness(pinned_start: Path) -> None:
    record = pinned_start / "runs" / "servers" / f"{NAME}.cpus"
    assert record.read_text(encoding="utf-8") == f"{cpu_list_text(SERVER_CPUS)} 0\n"


def test_a_server_started_under_taskset_keeps_a_trusted_pid_file(pinned_start: Path) -> None:
    pid_file = pinned_start / "runs" / "servers" / f"{NAME}.pid"
    command = f'source "{DEPLOYMENT_DIRECTORY / "server_pid.sh"}"; trusted_server_pid "$1" "$2"'
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", command, "trusted", str(pid_file), NAME], capture_output=True, text=True, check=False
    )
    assert result.stdout == f"{server_process_id(pinned_start)}\n"


def test_without_server_cpu_list_a_server_runs_on_every_cpu_the_cgroup_allows(tmp_path: Path) -> None:
    cpuset = tmp_path / "cgroup" / "cpuset" / "cpuset.cpus"
    cpuset.parent.mkdir(parents=True)
    cpuset.write_text(f"{SERVER_CPU_LIST}\n", encoding="utf-8")
    with started_server(tmp_path, PINNED_CALLER, {"CGROUP_ROOT": str(tmp_path / "cgroup")}) as result:
        assert result.returncode == 0, result.stderr
        assert os.sched_getaffinity(server_process_id(tmp_path)) == set(SERVER_CPUS)


def test_a_niced_callers_server_starts_at_that_niceness_with_a_warning_and_records_it(tmp_path: Path) -> None:
    with started_server(tmp_path, NICED_CALLER, {"SERVER_CPU_LIST": SERVER_CPU_LIST}) as result:
        record = (tmp_path / "runs" / "servers" / f"{NAME}.cpus").read_text(encoding="utf-8")
        assert (record, "Warning" in result.stderr) == (f"{cpu_list_text(SERVER_CPUS)} 19\n", True)
