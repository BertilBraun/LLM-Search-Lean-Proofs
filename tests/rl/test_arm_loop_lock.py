"""deployment/arm_loop.sh's run lock (review BC B1), the real script beside stand-ins for what it calls: one start of a
run at a time, the detached loop holding the lock for its whole life, the servers never holding it."""

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="no flock")

REPOSITORY = Path(__file__).resolve().parents[2]
NAME = "followup_X"

ENVIRONMENT = """export LEAN_SEARCH_RUNS="${STUB_ROOT}/runs"
export BACKGROUND_CPU_LIST=48-95
export PATH="${STUB_ROOT}/bin:${PATH}"
"""
SERVER_PID = "trusted_server_pid() { return 1; }\n"
# init and servers take STUB_SECONDS; servers leave a detached stand-in server behind (its pid in server.pid); loop
# starts a detached stand-in loop of STUB_LOOP_SECONDS, its pid in loop.pid.
GRPO_LOOP = """#!/usr/bin/env bash
run="${LEAN_SEARCH_RUNS}/followup_X"
case "$1" in
    init) sleep "${STUB_SECONDS:-0}" ;;
    servers)
        sleep "${STUB_SECONDS:-0}"
        nohup sleep 30 > /dev/null 2>&1 &
        echo $! > "${STUB_ROOT}/server.pid"
        ;;
    loop)
        mkdir -p "${run}"
        nohup sleep "${STUB_LOOP_SECONDS:-3}" > /dev/null 2>&1 &
        echo $! > "${run}/loop.pid"
        ;;
esac
"""
PYTHON = """#!/usr/bin/env bash
case "$1" in
    experiments/followup_arm.py) echo "${STUB_ROOT}/loop.toml" ;;
    experiments/node_checks.py) exit 0 ;;
    -c) exec python3 "$@" ;;
    *) exit 2 ;;
esac
"""


def write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    deployment = tmp_path / "deployment"
    deployment.mkdir()
    shutil.copyfile(REPOSITORY / "deployment" / "arm_loop.sh", deployment / "arm_loop.sh")
    write(deployment / "environment.sh", ENVIRONMENT)
    write(deployment / "server_pid.sh", SERVER_PID)
    write(deployment / "grpo_loop.sh", GRPO_LOOP, executable=True)
    write(tmp_path / "bin" / "python", PYTHON, executable=True)
    write(tmp_path / "loop.toml", f'name = "{NAME}"\n')
    (tmp_path / "runs").mkdir()
    (tmp_path / "mode.toml").touch()
    return tmp_path


def command(root: Path) -> list[str]:
    return ["bash", str(root / "deployment" / "arm_loop.sh"), "--mode", str(root / "mode.toml"), "overlay.toml"]


def environment(root: Path, extra: dict[str, str]) -> dict[str, str]:
    return os.environ | {"STUB_ROOT": str(root), "ARM_LOOP_START_SECONDS": "0"} | extra


def start(root: Path, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        command(root), env=environment(root, extra or {}), capture_output=True, text=True, timeout=60, check=False
    )


def lock_held(root: Path) -> bool:
    lock = root / "runs" / f"{NAME}.lock"
    return lock.exists() and subprocess.run(["flock", "-n", str(lock), "true"], check=False).returncode != 0  # noqa: S603, S607


def wait_for(condition: Callable[[], bool], seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_a_second_start_while_the_first_is_in_flight_is_refused(root: Path) -> None:
    first = subprocess.Popen(command(root), env=environment(root, {"STUB_SECONDS": "2"}))  # noqa: S603
    wait_for(lambda: lock_held(root))
    second = start(root)
    first.wait()
    assert (second.returncode, "in flight or its loop runs" in second.stderr) == (1, True)


def test_the_detached_loop_holds_the_lock_after_the_start(root: Path) -> None:
    assert (start(root).returncode, lock_held(root)) == (0, True)


def test_a_start_is_refused_while_the_loop_lives(root: Path) -> None:
    start(root)
    assert start(root).returncode == 1


def test_the_lock_is_free_once_the_loop_ended(root: Path) -> None:
    start(root, {"STUB_LOOP_SECONDS": "0.5"})
    wait_for(lambda: not lock_held(root))
    assert start(root, {"STUB_LOOP_SECONDS": "0.5"}).returncode == 0


def test_a_server_the_start_left_running_does_not_hold_the_lock(root: Path) -> None:
    start(root, {"STUB_LOOP_SECONDS": "0.5"})
    server = int((root / "server.pid").read_text(encoding="utf-8"))
    try:
        wait_for(lambda: not lock_held(root))
        assert Path(f"/proc/{server}").exists()
    finally:
        os.kill(server, 9)
