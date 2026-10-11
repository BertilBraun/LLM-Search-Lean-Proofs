import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool, ProofState, ReplFailure, ReplFailureKind
from lean_search.lean.repl import (
    CommandResponse,
    ReplErrorResponse,
    ReplMessage,
    ReplSorry,
    Severity,
    TacticResponse,
    parse_axioms,
    parse_command_response,
    parse_tactic_response,
)

UNSTARTABLE = LeanReplConfig(project_directory=Path(__file__).parent / "missing_lean_project")
STATE = ProofState("", "theorem t : True := by\n", (), ("⊢ True",), repl_proof_state=0, session=0)


def test_session_ids_differ_across_processes() -> None:
    command = [sys.executable, "-c", "from lean_search.lean.repl import new_session_id; print(new_session_id())"]
    sessions = {subprocess.run(command, capture_output=True, text=True, check=True).stdout for _ in range(2)}
    assert len(sessions) == 2


async def test_repl_that_cannot_start_reports_a_restart_failure() -> None:
    result = await LeanRepl(UNSTARTABLE).apply_tactic(STATE, "trivial")
    assert isinstance(result.outcome, ReplFailure) and result.outcome.kind is ReplFailureKind.RESTART_FAILED


async def test_pool_slot_returns_after_failed_restarts() -> None:
    pool = LeanReplPool(1, UNSTARTABLE, restart_attempts=2, restart_backoff_seconds=0.01)
    with pytest.raises(RuntimeError):
        async with pool.acquire():
            raise RuntimeError("the search failed")
    async with asyncio.timeout(30), pool.acquire() as repl:
        acquired = repl
    await pool.close()
    assert acquired is pool.repls[0]


def test_command_response_is_parsed_into_typed_messages() -> None:
    payload = {
        "env": 3,
        "messages": [{"severity": "warning", "pos": {"line": 1, "column": 0}, "data": "unused variable"}],
        "sorries": [{"goal": "⊢ True", "proofState": 7}],
    }
    assert parse_command_response(payload) == CommandResponse(
        3, (ReplMessage(Severity.WARNING, "unused variable"),), (ReplSorry("⊢ True", 7),)
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"proofState": 4, "goals": []}, TacticResponse(4, (), (), ())),
        ({"message": "Lean error:\nunknown tactic"}, ReplErrorResponse("Lean error:\nunknown tactic")),
    ],
)
def test_tactic_response_is_parsed(payload: dict[str, object], expected: TacticResponse | ReplErrorResponse) -> None:
    assert parse_tactic_response(payload) == expected


def test_unexpected_response_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_tactic_response({"goals": []})


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ((ReplMessage(Severity.INFO, "'t' depends on axioms: [propext, Quot.sound]"),), ("propext", "Quot.sound")),
        ((ReplMessage(Severity.INFO, "'t' does not depend on any axioms"),), ()),
        ((ReplMessage(Severity.INFO, "'other' does not depend on any axioms"),), None),
        ((ReplMessage(Severity.ERROR, "unknown constant 't'"),), None),
        (
            (
                ReplMessage(Severity.INFO, "'t' does not depend on any axioms"),
                ReplMessage(Severity.INFO, "'t' depends on axioms: [sorryAx]"),
            ),
            None,
        ),
    ],
)
def test_axioms_are_read_only_from_a_single_matching_report(
    messages: tuple[ReplMessage, ...], expected: tuple[str, ...] | None
) -> None:
    assert parse_axioms(CommandResponse(0, messages, ()), "t") == expected
