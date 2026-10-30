import asyncio
import contextlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.rl.loop import GrpoLoopPaths
from lean_search.rl.loop_config import LoopTrainingConfig, load_loop_config
from lean_search.rl.loop_services import (
    JOB_MARKER_VARIABLE,
    ChildProcess,
    SubprocessTrainer,
    evaluation_repls,
    host_memory_text,
    live_children,
    run_logged,
    running_start_ticks,
)
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="process groups and /proc are POSIX")

SLEEPER = "import time; time.sleep(60)"
# Writes the process id of a sleeping child of its own to argv[1], then sleeps.
PARENT_OF_A_SLEEPER = (
    "import subprocess, sys, time; "
    f"child = subprocess.Popen([sys.executable, '-c', {SLEEPER!r}]); "
    "open(sys.argv[1], 'w').write(str(child.pid)); time.sleep(60)"
)
# The same with the child in a session of its own, as torchrun starts its workers.
PARENT_OF_A_SESSION_LEADER = (
    "import subprocess, sys, time; "
    f"child = subprocess.Popen([sys.executable, '-c', {SLEEPER!r}], start_new_session=True); "
    "open(sys.argv[1], 'w').write(str(child.pid)); time.sleep(60)"
)
# Starts a sleeper in a session of its own, writes its process id to argv[1] and exits at once.
ORPHANING_PARENT = (
    "import subprocess, sys; "
    f"child = subprocess.Popen([sys.executable, '-c', {SLEEPER!r}], start_new_session=True); "
    "open(sys.argv[1], 'w').write(str(child.pid))"
)


@dataclass
class RunningJob:
    task: asyncio.Task[None]
    child: ChildProcess


async def start_job(root: Path, arguments: list[str]) -> RunningJob:
    record = root / "children" / "job.pid"
    task = asyncio.create_task(run_logged(arguments, root / "job.log", dict(os.environ), record))
    while not record.exists():
        await asyncio.sleep(0.01)
    return RunningJob(task, from_json_object(ChildProcess, json.loads(record.read_text())))


async def cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def ends_within(process_id: int, seconds: float) -> bool:
    """Killed processes outside our own children are reaped by init, a moment later."""
    for _ in range(int(seconds / 0.05)):
        if running_start_ticks(process_id) is None:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_cancelling_a_job_stops_its_process(tmp_path: Path) -> None:
    job = await start_job(tmp_path, [sys.executable, "-c", SLEEPER])
    await cancel(job.task)
    assert running_start_ticks(job.child.process_id) is None


async def test_cancelling_a_job_stops_the_processes_it_started(tmp_path: Path) -> None:
    grandchild_file = tmp_path / "grandchild"
    job = await start_job(tmp_path, [sys.executable, "-c", PARENT_OF_A_SLEEPER, str(grandchild_file)])
    while not grandchild_file.exists() or not grandchild_file.read_text():
        await asyncio.sleep(0.01)
    await cancel(job.task)
    assert await ends_within(int(grandchild_file.read_text()), seconds=5.0)


async def test_cancelling_a_job_stops_the_processes_it_started_in_sessions_of_their_own(tmp_path: Path) -> None:
    worker_file = tmp_path / "worker"
    job = await start_job(tmp_path, [sys.executable, "-c", PARENT_OF_A_SESSION_LEADER, str(worker_file)])
    while not worker_file.exists() or not worker_file.read_text():
        await asyncio.sleep(0.01)
    await cancel(job.task)
    assert await ends_within(int(worker_file.read_text()), seconds=5.0)


async def test_a_job_that_ended_leaves_no_worker_running(tmp_path: Path) -> None:
    worker_file = tmp_path / "worker"
    arguments = [sys.executable, "-c", ORPHANING_PARENT, str(worker_file)]
    await run_logged(arguments, tmp_path / "job.log", dict(os.environ), tmp_path / "children" / "job.pid")
    assert await ends_within(int(worker_file.read_text()), seconds=5.0)


@contextlib.contextmanager
def marked_sleeper(marker: str) -> Iterator[subprocess.Popen[bytes]]:
    environment = os.environ | {JOB_MARKER_VARIABLE: marker}
    sleeper = subprocess.Popen([sys.executable, "-c", SLEEPER], env=environment, start_new_session=True)
    try:
        yield sleeper
    finally:
        sleeper.kill()
        sleeper.wait()


def test_a_job_whose_launcher_ended_still_runs_while_a_worker_does(tmp_path: Path) -> None:
    write_json_atomically(tmp_path / "training.pid", ChildProcess(os.getpid(), own_start_ticks() + 1, "torchrun", "m"))
    with marked_sleeper("m") as worker:
        assert [job.process_ids for job in live_children(tmp_path)] == [(worker.pid,)]


async def test_a_finished_job_removes_its_record(tmp_path: Path) -> None:
    record = tmp_path / "children" / "job.pid"
    await run_logged([sys.executable, "-c", "pass"], tmp_path / "job.log", dict(os.environ), record)
    assert not record.exists()


def own_start_ticks() -> int:
    start_ticks = running_start_ticks(os.getpid())
    assert start_ticks is not None
    return start_ticks


async def test_a_job_does_not_start_while_an_earlier_loops_job_runs(tmp_path: Path) -> None:
    earlier = ChildProcess(os.getpid(), own_start_ticks(), "earlier")
    write_json_atomically(tmp_path / "children" / "training.pid", earlier)
    with pytest.raises(RuntimeError):
        await run_logged([sys.executable, "-c", "pass"], tmp_path / "job.log", {}, tmp_path / "children" / "job.pid")


def test_the_host_memory_text_reports_what_is_available() -> None:
    assert "GiB available" in host_memory_text()


def test_beside_sampling_the_evaluation_repls_stay_within_the_sampling_concurrency() -> None:
    config = load_loop_config(REPOSITORY_DIRECTORY / "experiments/configs/grpo/loop.toml")
    assert evaluation_repls(config) == config.sampling.concurrency


def test_an_evaluation_job_left_by_an_earlier_loop_is_reported(tmp_path: Path) -> None:
    paths = GrpoLoopPaths(tmp_path, tmp_path, tmp_path, "loop")
    record = paths.children / "evaluations" / "probe_slot0000_v0000" / "evaluation.pid"
    write_json_atomically(record, ChildProcess(os.getpid(), own_start_ticks(), "earlier"))
    assert SubprocessTrainer(paths, LoopTrainingConfig("unused.toml")).earlier_jobs() is not None


async def test_concurrent_evaluation_jobs_do_not_refuse_each_other(tmp_path: Path) -> None:
    children = tmp_path / "children" / "evaluations"
    sleeper = asyncio.create_task(
        run_logged([sys.executable, "-c", SLEEPER], tmp_path / "a.log", dict(os.environ), children / "a" / "e.pid")
    )
    while not (children / "a" / "e.pid").exists():
        await asyncio.sleep(0.01)
    await run_logged([sys.executable, "-c", "pass"], tmp_path / "b.log", dict(os.environ), children / "b" / "e.pid")
    sleeper.cancel()
    await asyncio.gather(sleeper, return_exceptions=True)
    assert not (children / "b" / "e.pid").exists()


def test_a_record_whose_process_id_was_reused_is_not_a_live_job(tmp_path: Path) -> None:
    write_json_atomically(tmp_path / "training.pid", ChildProcess(os.getpid(), own_start_ticks() + 1, "earlier"))
    assert live_children(tmp_path) == []
