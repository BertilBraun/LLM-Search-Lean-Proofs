"""Starting and stopping the vLLM servers: a failed start tried again with its log kept, stop_model.sh signalling only
a process its pid file is trusted for, and the loop's check of the servers on the restart path."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from server_process_fakes import fake_server_process

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.rl.loop_services import START_RETRIES, ServerStart, VllmServers, start_server

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]


def flaky_start(directory: Path, failures: int, name: str) -> str:
    """A start command that fails `failures` times (writing the server's log each time), then succeeds."""
    counter = directory / "attempts"
    log = directory / "servers" / f"{name}.log"
    return (
        f"n=$(cat {counter} 2>/dev/null || echo 0); echo $((n + 1)) > {counter}; echo attempt $n > {log}; "
        f"[ $n -ge {failures} ]"
    )


def start_flaky(directory: Path, failures: int) -> list[str]:
    name = f"test-start-{uuid.uuid4().hex[:8]}"
    (directory / "servers").mkdir()
    messages: list[str] = []
    start = ServerStart(ServerEndpoint(name, 0, "http://127.0.0.1:1/v1"), flaky_start(directory, failures, name))
    asyncio.run(start_server(start, directory / "servers", messages.append))
    return messages


def test_a_start_that_fails_once_is_tried_again(tmp_path: Path) -> None:
    start_flaky(tmp_path, 1)
    assert (tmp_path / "attempts").read_text(encoding="utf-8").strip() == "2"


def test_a_failed_starts_log_is_kept(tmp_path: Path) -> None:
    start_flaky(tmp_path, 1)
    (kept,) = (tmp_path / "servers").glob("*.failed-1.*.log")
    assert kept.read_text(encoding="utf-8").strip() == "attempt 0"


def test_a_failed_start_is_logged(tmp_path: Path) -> None:
    assert len(start_flaky(tmp_path, 2)) == 2


def test_a_start_failing_every_time_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="failed 3 times"):
        start_flaky(tmp_path, START_RETRIES + 1)


def stop_model(runs: Path, name: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "LEAN_SEARCH_RUNS": str(runs)}
    return subprocess.run(  # noqa: S603
        ["bash", str(REPOSITORY_DIRECTORY / "deployment" / "stop_model.sh"), name],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )


def test_stop_model_stops_a_server_its_pid_file_is_trusted_for(tmp_path: Path) -> None:
    with fake_server_process(tmp_path / "servers", "policy-gpu0", tmp_path / "merge") as process_id:
        stop_model(tmp_path, "policy-gpu0")
        assert not Path(f"/proc/{process_id}").exists() or "Z" in Path(f"/proc/{process_id}/stat").read_text()


def test_stop_model_never_signals_the_process_of_a_stale_pid_file(tmp_path: Path) -> None:
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])  # noqa: S603
    try:
        (tmp_path / "servers").mkdir()
        (tmp_path / "servers" / "policy-gpu0.pid").write_text(f"{sleeper.pid}\n", encoding="utf-8")
        stop_model(tmp_path, "policy-gpu0")
        assert sleeper.poll() is None
    finally:
        sleeper.kill()
        sleeper.wait()


def test_stop_model_removes_a_stale_pid_file(tmp_path: Path) -> None:
    (tmp_path / "servers").mkdir()
    (tmp_path / "servers" / "policy-gpu0.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    stop_model(tmp_path, "policy-gpu0")
    assert not (tmp_path / "servers" / "policy-gpu0.pid").exists()


def nowhere_servers(tmp_path: Path, swap: SwapMethod) -> VllmServers:
    serving = ServingConfig(
        "policy-base", "value-base", (ServerEndpoint("policy-gpu0", 0, "http://127.0.0.1:9/v1"),), (), swap=swap
    )
    publisher = MergedPublisher(serving, tmp_path / "weights", lambda base, adapter, output: None)
    return VllmServers(serving, serving.servers, publisher, tmp_path / "servers", print)


def test_on_the_restart_path_a_server_down_does_not_refuse_the_loops_start(tmp_path: Path) -> None:
    asyncio.run(nowhere_servers(tmp_path, SwapMethod.RESTART).check())


def test_in_place_a_server_down_refuses_the_loops_start(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not answering"):
        asyncio.run(nowhere_servers(tmp_path, SwapMethod.IN_PLACE).check())
