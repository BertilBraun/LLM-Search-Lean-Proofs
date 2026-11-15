"""Starting and stopping the vLLM servers: a failed start tried again with its log kept, stop_model.sh signalling only
a process its pid file is trusted for, the processes of a group that count as the server's (server_pid.sh), and the
loop's check of the servers on the restart path."""

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from server_process_fakes import fake_server_process

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.policy.server_processes import boot_time, process_start_time
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
    assert sum(message.startswith("Starting") for message in start_flaky(tmp_path, 2)) == 2


def test_a_started_server_logs_the_cpus_it_runs_on(tmp_path: Path) -> None:
    (tmp_path / "servers").mkdir()
    name = "policy-gpu0"
    (tmp_path / "servers" / f"{name}.cpus").write_text("0-47,96-143 0\n", encoding="utf-8")
    messages: list[str] = []
    start = ServerStart(ServerEndpoint(name, 0, "http://127.0.0.1:1/v1"), "true")
    asyncio.run(start_server(start, tmp_path / "servers", messages.append))
    assert messages == [f"{name} runs on CPUs 0-47,96-143 at niceness 0"]


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


def run_stop_model(runs: Path, name: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "LEAN_SEARCH_RUNS": str(runs)}
    return subprocess.run(  # noqa: S603
        ["bash", str(REPOSITORY_DIRECTORY / "deployment" / "stop_model.sh"), name],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_stop_model_never_signals_a_server_whose_pid_file_is_older_than_the_boot(tmp_path: Path) -> None:
    with fake_server_process(tmp_path / "servers", "policy-gpu0", tmp_path / "merge") as process_id:
        pid_file = tmp_path / "servers" / "policy-gpu0.pid"
        os.utime(pid_file, (boot_time() - 100, boot_time() - 100))
        run_stop_model(tmp_path, "policy-gpu0")
        assert Path(f"/proc/{process_id}/cmdline").read_bytes()


@contextlib.contextmanager
def leaderless_group(command: str, environment: dict[str, str]) -> Iterator[tuple[int, int]]:
    """A process group whose leader (a shell) exited, leaving `command` running: (group, member)."""
    leader = subprocess.Popen(  # noqa: S603
        ["bash", "-c", f"{command} & echo $!; exit 0"],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
        env=environment,
    )
    assert leader.stdout is not None
    member = int(leader.stdout.readline())
    leader.wait()
    try:
        yield leader.pid, member
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(member, signal.SIGKILL)


def test_stop_model_never_signals_an_unrecorded_engine_a_dead_api_server_left(tmp_path: Path) -> None:
    (tmp_path / "servers").mkdir()
    with leaderless_group(ENGINE, dict(os.environ)) as (group, member):
        (tmp_path / "servers" / "policy-gpu0.pid").write_text(f"{group}\n", encoding="utf-8")
        cmdline = Path(f"/proc/{member}/cmdline")
        while not cmdline.read_bytes().startswith(b"VLLM::"):
            time.sleep(0.05)
        run_stop_model(tmp_path, "policy-gpu0")
        assert cmdline.read_bytes().startswith(b"VLLM::")


def test_stop_model_never_signals_a_leaderless_group_whose_member_is_not_the_servers(tmp_path: Path) -> None:
    (tmp_path / "servers").mkdir()
    with leaderless_group("sleep 600", dict(os.environ)) as (group, member):
        (tmp_path / "servers" / "policy-gpu0.pid").write_text(f"{group}\n", encoding="utf-8")
        run_stop_model(tmp_path, "policy-gpu0")
        assert "sleep" in Path(f"/proc/{member}/cmdline").read_text()


ENGINE = (
    f"{sys.executable} -c 'import setproctitle, time; setproctitle.setproctitle(\"VLLM::EngineCore\"); time.sleep(600)'"
)


def test_stop_model_stops_the_engine_a_dead_api_server_left(tmp_path: Path) -> None:
    (tmp_path / "servers").mkdir()
    with leaderless_group(ENGINE, dict(os.environ)) as (group, member):
        (tmp_path / "servers" / "policy-gpu0.pid").write_text(f"{group}\n", encoding="utf-8")
        cmdline = Path(f"/proc/{member}/cmdline")
        while not cmdline.read_bytes().startswith(b"VLLM::"):
            time.sleep(0.05)
        started = process_start_time(member)
        assert started is not None
        # As serve_model.sh records the server's processes once it answers.
        (tmp_path / "servers" / "policy-gpu0.members").write_text(f"{member} {int(started)}\n", encoding="utf-8")
        run_stop_model(tmp_path, "policy-gpu0")
        assert not cmdline.exists() or " Z " in Path(f"/proc/{member}/stat").read_text()


SERVER_PID_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "server_pid.sh"
TRACKER_CODE = "from multiprocessing.resource_tracker import main;main(57)"


def server_pid_function(function: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    command = f'source "{SERVER_PID_SCRIPT}"; {function} "$@"'
    return subprocess.run(  # noqa: S603
        ["bash", "-c", command, function, *arguments], capture_output=True, text=True, check=False
    )


def started_seconds(process_id: int) -> int:
    started = process_start_time(process_id)
    assert started is not None
    return int(started)


def wait_for_command(process_id: int, last_argument: str) -> None:
    cmdline = Path(f"/proc/{process_id}/cmdline")
    while not cmdline.read_bytes().endswith(f"{last_argument}\0".encode()):
        time.sleep(0.05)


@contextlib.contextmanager
def orphaned_tracker(directory: Path) -> Iterator[tuple[int, int]]:
    """A resource tracker as multiprocessing starts it beside the API process (the group's leader, which then exits):
    (group, tracker). It reads fd 57, a FIFO nobody writes, so it only waits."""
    pipe = directory / "tracker_pipe"
    os.mkfifo(pipe)
    command = f"{sys.executable} -c '{TRACKER_CODE}' 57<>{pipe}"
    with leaderless_group(command, dict(os.environ)) as (group, tracker):
        wait_for_command(tracker, TRACKER_CODE)
        yield group, tracker


def orphaned_group_status(servers: Path, group: int, members: str) -> int:
    servers.mkdir(exist_ok=True)
    (servers / "policy-gpu0.pid").write_text(f"{group}\n", encoding="utf-8")
    (servers / "policy-gpu0.members").write_text(members, encoding="utf-8")
    return server_pid_function("orphaned_server_group", str(servers / "policy-gpu0.pid"), "policy-gpu0").returncode


def test_the_resource_tracker_recorded_as_the_api_processs_child_is_a_member(tmp_path: Path) -> None:
    with orphaned_tracker(tmp_path) as (group, tracker):
        members = f"{tracker} {started_seconds(tracker)} {group}\n"
        assert orphaned_group_status(tmp_path / "servers", group, members) == 0


@pytest.mark.parametrize(
    "recorded",
    ["", "{tracker} {earlier} {group}\n", "{tracker} {started} 1\n", "{tracker} {started}\n"],
    ids=["unrecorded", "another start", "another parent", "no parent recorded"],
)
def test_a_resource_tracker_not_recorded_as_the_api_processs_child_is_refused(tmp_path: Path, recorded: str) -> None:
    with orphaned_tracker(tmp_path) as (group, tracker):
        started = started_seconds(tracker)
        members = recorded.format(tracker=tracker, started=started, earlier=started - 5, group=group)
        assert orphaned_group_status(tmp_path / "servers", group, members) == 2


def test_an_unrelated_python_process_recorded_as_the_api_processs_child_is_refused(tmp_path: Path) -> None:
    with leaderless_group(f"{sys.executable} -c 'import time; time.sleep(600)'", dict(os.environ)) as (group, member):
        wait_for_command(member, "import time; time.sleep(600)")
        members = f"{member} {started_seconds(member)} {group}\n"
        assert orphaned_group_status(tmp_path / "servers", group, members) == 2


@contextlib.contextmanager
def live_leader_group(command: str) -> Iterator[tuple[int, int]]:
    """A process group whose leader (a shell) waits on its child running `command`: (group, child)."""
    leader = subprocess.Popen(  # noqa: S603
        ["bash", "-c", f"{command} & echo $!; wait"], start_new_session=True, stdout=subprocess.PIPE, text=True
    )
    assert leader.stdout is not None
    child = int(leader.stdout.readline())
    try:
        yield leader.pid, child
    finally:
        os.killpg(leader.pid, signal.SIGKILL)
        leader.wait()


def test_a_resource_tracker_whose_parent_is_the_live_api_process_is_a_member(tmp_path: Path) -> None:
    pipe = tmp_path / "tracker_pipe"
    os.mkfifo(pipe)
    with live_leader_group(f"{sys.executable} -c '{TRACKER_CODE}' 57<>{pipe}") as (group, tracker):
        wait_for_command(tracker, TRACKER_CODE)
        members = tmp_path / "policy-gpu0.members"
        members.write_text(f"{tracker} {started_seconds(tracker)}\n", encoding="utf-8")
        written = str(int(time.time()))
        result = server_pid_function("server_member", str(tracker), str(members), written, str(group))
        assert result.returncode == 0


def test_recorded_members_name_their_parent(tmp_path: Path) -> None:
    with live_leader_group("sleep 600") as (group, child):
        members = tmp_path / "policy-gpu0.members"
        server_pid_function("record_server_members", str(group), str(members))
        recorded = {line.split()[0]: line.split()[2] for line in members.read_text(encoding="utf-8").splitlines()}
        assert recorded[str(child)] == str(group)
