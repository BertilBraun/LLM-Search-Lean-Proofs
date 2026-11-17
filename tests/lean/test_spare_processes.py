import asyncio
import dataclasses
import os
import signal
from pathlib import Path

import pytest
from fake_repl_project import HEADER, STATEMENT, FakeReplProject, fake_repl_project, needs_linux

from lean_search.lean import LeanReplPool, LeanTimeout, ProofState
from lean_search.lean.pool import SpareProcesses
from lean_search.lean.repl import REPL_BINARY

pytestmark = needs_linux
IMPORT_SECONDS = 1.5
TIMEOUT_SECONDS = 0.5


async def spares_ready(pool: LeanReplPool, count: int) -> None:
    assert pool.spares is not None
    async with asyncio.timeout(30):
        while pool.spares.ready < count:
            await asyncio.sleep(0.05)


async def killed_once(
    project: FakeReplProject, spare_processes: int, wait_for_spare: bool
) -> tuple[LeanReplPool, float]:
    """A one-process pool runs a statement and a hanging tactic; returns the pool (open) and the hang's seconds."""
    pool = LeanReplPool(1, project.config, spare_processes=spare_processes)
    await pool.start([HEADER])
    if wait_for_spare:
        await spares_ready(pool, spare_processes)
    async with pool.acquire() as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        hang = await repl.apply_block(start.outcome, "hang")
        assert isinstance(hang.failure, LeanTimeout) and hang.failure.wall_clock
    return pool, hang.elapsed_seconds


async def test_a_killed_process_is_swapped_for_a_ready_spare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
    pool, _ = await killed_once(project, spare_processes=1, wait_for_spare=True)
    await pool.close()
    assert (pool.repls[0].spare_swaps, pool.repls[0].spare_misses) == (1, 0)


async def test_a_swap_does_not_wait_for_an_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
    pool, seconds = await killed_once(project, spare_processes=1, wait_for_spare=True)
    await pool.close()
    assert seconds < TIMEOUT_SECONDS + IMPORT_SECONDS / 2


async def test_without_spares_a_kill_waits_for_the_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
    pool, seconds = await killed_once(project, spare_processes=0, wait_for_spare=False)
    await pool.close()
    assert seconds >= TIMEOUT_SECONDS + IMPORT_SECONDS


async def test_a_spare_not_ready_yet_leaves_the_repl_to_start_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
    pool, _ = await killed_once(project, spare_processes=1, wait_for_spare=False)
    await pool.close()
    assert (pool.repls[0].spare_swaps, pool.repls[0].spare_misses) == (0, 1)


async def test_the_repl_keeps_working_after_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS, timeout_seconds=TIMEOUT_SECONDS)
    pool, _ = await killed_once(project, spare_processes=1, wait_for_spare=False)
    async with pool.acquire() as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        result = await repl.apply_block(start.outcome, "done")
    await pool.close()
    assert result.state.is_proved


async def test_a_state_of_the_killed_process_continues_on_the_spare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=TIMEOUT_SECONDS)
    pool = LeanReplPool(1, project.config, spare_processes=1)
    await pool.start([HEADER])
    await spares_ready(pool, 1)
    async with pool.acquire() as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        stepped = await repl.apply_block(start.outcome, "step")
        await repl.apply_block(stepped.state, "hang")
        result = await repl.apply_block(stepped.state, "done")
    await pool.close()
    assert (result.state.is_proved, repl.spare_swaps) == (True, 1)


async def test_a_taken_spare_is_replaced_in_the_background(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=TIMEOUT_SECONDS)
    pool, _ = await killed_once(project, spare_processes=1, wait_for_spare=True)
    await spares_ready(pool, 1)
    assert pool.spares is not None
    refilled = pool.spares.ready_process_ids()
    in_use = pool.repls[0].process_id
    await pool.close()
    assert len(refilled) == 1 and refilled[0] != in_use


async def test_a_dead_ready_spare_is_not_handed_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=TIMEOUT_SECONDS)
    pool = LeanReplPool(1, project.config, spare_processes=1)
    await pool.start([HEADER])
    await spares_ready(pool, 1)
    assert pool.spares is not None
    os.kill(pool.spares.ready_process_ids()[0], signal.SIGKILL)
    async with asyncio.timeout(30):
        while pool.spares.ready_process_ids():
            await asyncio.sleep(0.05)
    async with pool.acquire() as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        await repl.apply_block(start.outcome, "hang")
        after = await repl.apply_block(start.outcome, "done")
    await pool.close()
    assert (repl.spare_swaps, repl.spare_misses, after.state.is_proved) == (0, 1, True)


async def test_a_failed_spare_start_is_tried_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    binary = project.config.project_directory / REPL_BINARY
    hidden = binary.with_name("repl.hidden")
    binary.rename(hidden)
    spares = SpareProcesses(1, project.config, lambda: [HEADER], retry_seconds=0.2)
    spares.fill()
    await asyncio.sleep(0.5)
    hidden.rename(binary)
    async with asyncio.timeout(30):
        while spares.ready < 1:
            await asyncio.sleep(0.05)
    await spares.close()


async def test_a_repl_past_its_proof_state_limit_takes_a_spare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    config = dataclasses.replace(project.config, max_proof_states=4)
    pool = LeanReplPool(1, config, spare_processes=1)
    await pool.start([HEADER])
    await spares_ready(pool, 1)
    async with pool.acquire() as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        for _ in range(4):
            await repl.apply_block(start.outcome, "step")
    await pool.close()
    assert repl.spare_swaps >= 1


async def test_the_spare_has_the_pools_headers_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    spares = SpareProcesses(1, project.config, lambda: [HEADER])
    spares.fill()
    async with asyncio.timeout(30):
        while spares.ready < 1:
            await asyncio.sleep(0.05)
    await spares.close()
    assert project.requests("cmd").count(HEADER.strip()) == 1


async def test_closing_the_pool_stops_its_spares(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    pool = LeanReplPool(1, project.config, spare_processes=2)
    await pool.start([HEADER])
    await spares_ready(pool, 2)
    await pool.close()
    assert not [process_id for process_id in project.process_ids() if Path(f"/proc/{process_id}").exists()]


async def test_closing_the_pool_while_spares_start_leaves_no_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, import_seconds=IMPORT_SECONDS)
    pool = LeanReplPool(1, project.config, spare_processes=2)
    await pool.start([HEADER])
    await pool.close()
    assert asyncio.all_tasks() == {asyncio.current_task()}
