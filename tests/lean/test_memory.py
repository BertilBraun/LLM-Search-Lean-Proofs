from pathlib import Path

import pytest
from fake_repl_project import HEADER, STATEMENT, FakeReplProject, fake_repl_project, needs_linux

from lean_search.lean import LeanError, LeanRepl, LeanTimeout, Outcome, ProofState, ReplFailure, ReplFailureKind
from lean_search.lean.memory import SearchMemory
from lean_search.lean.repl import Remembered

ROOT = ProofState(HEADER, STATEMENT, (), ("⊢ True",), repl_proof_state=1, session=7)
AFTER_STEP = ProofState(
    HEADER, STATEMENT, ("step",), ("⊢ True",), repl_proof_state=2, session=7, tactic_heartbeats=(5,)
)


@pytest.mark.parametrize(
    "outcome",
    [
        AFTER_STEP,
        LeanError("linarith failed"),
        LeanError("Lean panic: Nat.pow exponent is too big", panic=True),
        LeanTimeout("maximum number of heartbeats", wall_clock=False),
    ],
)
def test_a_deterministic_outcome_is_recalled_for_the_identical_input(outcome: Outcome) -> None:
    memory = SearchMemory(cache_results=True)
    memory.record(ROOT, "step", 5, outcome, 2.5)
    assert memory.recall(ROOT, "step", 5) == Remembered(outcome, 2.5)


@pytest.mark.parametrize(
    "outcome",
    [
        LeanTimeout("The tactic exceeded the wall-clock limit.", wall_clock=True),
        ReplFailure(ReplFailureKind.CRASHED, "The Lean REPL process died"),
    ],
)
def test_a_load_or_process_dependent_outcome_is_not_recalled(outcome: Outcome) -> None:
    memory = SearchMemory(cache_results=True)
    memory.record(ROOT, "nlinarith", 5, outcome, 60.0)
    assert memory.recall(ROOT, "nlinarith", 5) is None


def test_equal_goals_reached_by_another_tactic_path_are_a_different_input() -> None:
    memory = SearchMemory(cache_results=True)
    memory.record(ROOT, "nlinarith", 5, LeanError("linarith failed"), 1.0)
    assert memory.recall(AFTER_STEP, "nlinarith", 5) is None


def test_another_heartbeat_limit_is_a_different_input() -> None:
    memory = SearchMemory(cache_results=True)
    memory.record(ROOT, "nlinarith", 5, LeanError("linarith failed"), 1.0)
    assert memory.recall(ROOT, "nlinarith", 6) is None


def test_another_process_session_of_the_same_path_is_the_same_input() -> None:
    memory = SearchMemory(cache_results=True)
    memory.record(ROOT, "nlinarith", 5, LeanError("linarith failed"), 1.0)
    restarted = ProofState(HEADER, STATEMENT, (), ("⊢ True",), repl_proof_state=4, session=8)
    assert memory.recall(restarted, "nlinarith", 5) is not None


def test_without_the_cache_nothing_is_recalled() -> None:
    memory = SearchMemory(cache_results=False)
    memory.record(ROOT, "nlinarith", 5, LeanError("linarith failed"), 1.0)
    assert memory.recall(ROOT, "nlinarith", 5) is None


async def started(project: FakeReplProject) -> tuple[LeanRepl, ProofState]:
    repl = LeanRepl(project.config)
    start = await repl.start_proof(STATEMENT, HEADER)
    assert isinstance(start.outcome, ProofState)
    return repl, start.outcome


@needs_linux
async def test_a_block_run_again_on_the_same_state_is_answered_without_lean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    repl, root = await started(project)
    memory = SearchMemory(cache_results=True)
    async with repl:
        await repl.apply_block(root, "step\nfail", memory=memory)
        again = await repl.apply_block(root, "step\nfail", memory=memory)
    assert (again.cached_tactics, project.requests("tactic").count("step")) == (2, 1)


@needs_linux
async def test_a_cached_block_has_the_outcome_of_its_first_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch)
    repl, root = await started(project)
    memory = SearchMemory(cache_results=True)
    async with repl:
        first = await repl.apply_block(root, "step\nfail", memory=memory)
        again = await repl.apply_block(root, "step\nfail", memory=memory)
    assert (again.state, again.applied_tactics, again.failure) == (first.state, first.applied_tactics, first.failure)


@needs_linux
async def test_a_wall_clock_stop_runs_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=0.5)
    repl, root = await started(project)
    memory = SearchMemory(cache_results=True)
    async with repl:
        await repl.apply_block(root, "hang", memory=memory)
        await repl.apply_block(root, "hang", memory=memory)
    assert project.requests("tactic").count("hang") == 2


@needs_linux
async def test_a_cached_state_from_a_killed_process_is_replayed_to_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=0.5)
    repl, root = await started(project)
    memory = SearchMemory(cache_results=True)
    async with repl:
        await repl.apply_block(root, "step", memory=memory)
        await repl.apply_block(root, "hang", memory=memory)
        finished = await repl.apply_block(root, "step\ndone", memory=memory)
    assert (finished.state.is_proved, finished.cached_tactics, project.requests("tactic").count("step")) == (True, 1, 2)
