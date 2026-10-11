import asyncio
import contextlib
import dataclasses
import shutil
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from lean_search.lean import (
    FORBIDDEN_TOKENS,
    BlockResult,
    LeanError,
    LeanRepl,
    LeanReplConfig,
    LeanReplPool,
    LeanTimeout,
    ProofState,
    ReplFailure,
    ReplFailureKind,
)
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY, lake_environment

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by\n"
CONJUNCTION_STATEMENT = "theorem test_and (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a = 2 ∧ b = 3 := by\n"
FALSE_STATEMENT = "theorem false_claim : ∀ n : ℕ, n ≠ 777777 := by\n"
CLOSED_STATEMENT = "theorem two_plus_three : 2 + 3 = 5 := by\n"
SLOW_TACTIC = "sleep 60000"
SLEEPING_PROOF = "sleep 1500\nomega"
SLEEP_ALLOWED = LeanReplConfig(tactic_timeout_seconds=30.0, forbidden_tokens=FORBIDDEN_TOKENS - {"sleep"})
UNCHECKED = LeanReplConfig(forbidden_tokens=frozenset(), max_data_bytes=2 << 30)
OUT_OF_MEMORY_TACTIC = 'run_tac do\n  let array := Array.mkArray 500000000 (0 : Nat)\n  Lean.logInfo m!"{array.size}"'

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(SLEEP_ALLOWED) as lean_repl:
        yield lean_repl


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def unchecked_repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(UNCHECKED) as lean_repl:
        yield lean_repl


@pytest_asyncio.fixture(loop_scope="module")
async def initial_state(repl: LeanRepl) -> ProofState:
    result = await repl.start_proof(STATEMENT, HEADER)
    assert isinstance(result.outcome, ProofState), result.outcome
    return result.outcome


@pytest_asyncio.fixture(loop_scope="module")
async def substituted_state(repl: LeanRepl, initial_state: ProofState) -> ProofState:
    result = await repl.apply_tactic(initial_state, "subst h₀")
    assert isinstance(result.outcome, ProofState), result.outcome
    return result.outcome


@pytest_asyncio.fixture(loop_scope="module")
async def limited_state(repl: LeanRepl, initial_state: ProofState) -> ProofState:
    result = await repl.apply_tactic(initial_state, "try simp [h₀, h₁]", heartbeats=10)
    assert isinstance(result.outcome, ProofState) and result.outcome.goals == initial_state.goals, result.outcome
    return result.outcome


@pytest_asyncio.fixture(loop_scope="module")
async def limited_proof(repl: LeanRepl, limited_state: ProofState) -> ProofState:
    result = await repl.apply_tactic(limited_state, "omega")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved, result.outcome
    return result.outcome


@pytest_asyncio.fixture(loop_scope="module")
async def proving_block(repl: LeanRepl, initial_state: ProofState) -> BlockResult:
    return await repl.apply_block(initial_state, "omega\nsimp")


async def start(repl: LeanRepl, statement: str) -> ProofState:
    result = await repl.start_proof(statement, HEADER)
    assert isinstance(result.outcome, ProofState), result.outcome
    return result.outcome


async def test_start_proof_returns_the_statement_goal(initial_state: ProofState) -> None:
    assert initial_state.goals == ("a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5",)


async def test_invalid_statement_is_an_error(repl: LeanRepl) -> None:
    result = await repl.start_proof('theorem broken (x : ℕ) : x = "text" := by\n', HEADER)
    assert isinstance(result.outcome, LeanError)


async def test_valid_tactic_changes_the_goal(substituted_state: ProofState) -> None:
    assert substituted_state.goals[0].endswith("⊢ 2 + b = 5")


async def test_applied_tactic_records_its_heartbeat_limit(substituted_state: ProofState) -> None:
    assert substituted_state.tactic_heartbeats == (SLEEP_ALLOWED.tactic_heartbeats,)


async def test_failing_tactic_is_an_error(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "exact h₀")
    assert isinstance(result.outcome, LeanError)


async def test_logged_elaboration_error_is_an_error(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "exact undefined_lemma")
    assert isinstance(result.outcome, LeanError)


async def test_unparsable_tactic_is_an_error(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "simp [")
    assert isinstance(result.outcome, LeanError)


async def test_unsolved_nested_goal_is_an_error(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "have h : a = 3 := by simp")
    assert isinstance(result.outcome, LeanError)


async def test_closing_tactic_proves_the_theorem(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "omega")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def test_multi_line_tactic_is_one_step(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "subst h₀\nsubst h₁\nrfl")
    assert isinstance(result.outcome, ProofState) and result.outcome.tactics == ("subst h₀\nsubst h₁\nrfl",)


@pytest.mark.parametrize(
    "tactic",
    ["sorry", "admit", "native_decide", "set_option maxHeartbeats 0 in omega", "exact sorryAx _ false", "apply?"],
)
async def test_forbidden_tactic_is_rejected(repl: LeanRepl, initial_state: ProofState, tactic: str) -> None:
    result = await repl.apply_tactic(initial_state, tactic)
    assert isinstance(result.outcome, LeanError) and result.outcome.message.startswith("Forbidden tokens")


@pytest.mark.parametrize(
    ("statement", "tactic"),
    [(STATEMENT, "exact sorryAx _ false"), (STATEMENT, "admit"), (FALSE_STATEMENT, "slim_check")],
)
async def test_goal_closed_with_sorry_is_an_error(unchecked_repl: LeanRepl, statement: str, tactic: str) -> None:
    result = await unchecked_repl.apply_tactic(await start(unchecked_repl, statement), tactic)
    assert isinstance(result.outcome, LeanError) and "sorry" in result.outcome.message


async def test_placeholders_left_by_refine_are_open_goals(repl: LeanRepl) -> None:
    result = await repl.apply_tactic(await start(repl, CONJUNCTION_STATEMENT), "refine ⟨?_, ?_⟩")
    assert isinstance(result.outcome, ProofState) and len(result.outcome.goals) == 2


async def test_heartbeat_limit_is_a_deterministic_timeout(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, "nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]", heartbeats=1)
    assert isinstance(result.outcome, LeanTimeout) and not result.outcome.wall_clock


async def test_wall_clock_limit_is_a_timeout(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_tactic(initial_state, SLOW_TACTIC, heartbeats=0, timeout_seconds=2.0)
    assert isinstance(result.outcome, LeanTimeout) and result.outcome.wall_clock


async def test_state_survives_a_wall_clock_kill(
    repl: LeanRepl, initial_state: ProofState, substituted_state: ProofState
) -> None:
    await repl.apply_tactic(initial_state, SLOW_TACTIC, heartbeats=0, timeout_seconds=2.0)
    result = await repl.apply_tactic(substituted_state, "subst h₁")
    assert isinstance(result.outcome, ProofState) and result.outcome.goals[0].endswith("⊢ 2 + 3 = 5")


async def test_state_survives_a_restart(repl: LeanRepl, substituted_state: ProofState) -> None:
    await repl.restart()
    result = await repl.apply_tactic(substituted_state, "subst h₁\nrfl")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def test_wall_clock_timeout_restarts_the_process_before_returning(
    repl: LeanRepl, initial_state: ProofState
) -> None:
    await repl.apply_tactic(initial_state, SLOW_TACTIC, heartbeats=0, timeout_seconds=2.0)
    assert repl.process_id is not None


async def test_cancelled_tactic_does_not_leak_its_response(repl: LeanRepl, initial_state: ProofState) -> None:
    task = asyncio.create_task(repl.apply_tactic(initial_state, SLEEPING_PROOF))
    await asyncio.sleep(0.5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    result = await repl.apply_tactic(initial_state, "subst h₀")
    assert isinstance(result.outcome, ProofState) and result.outcome.goals[0].endswith("⊢ 2 + b = 5")


async def test_cancelled_verification_does_not_leak_its_response(repl: LeanRepl) -> None:
    await repl.load_header(HEADER)
    task = asyncio.create_task(repl.verify_proof(STATEMENT, SLEEPING_PROOF, HEADER))
    await asyncio.sleep(0.5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    result = await repl.verify_proof(STATEMENT, "subst h₀", HEADER)
    assert not result.verified


async def test_replay_uses_the_recorded_heartbeat_limit(repl: LeanRepl, limited_state: ProofState) -> None:
    await repl.restart()
    result = await repl.apply_tactic(limited_state, "omega")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def test_replay_that_reaches_different_goals_is_a_repl_failure(
    repl: LeanRepl, substituted_state: ProofState
) -> None:
    stale = dataclasses.replace(substituted_state, goals=("⊢ False",), session=0)
    result = await repl.apply_tactic(stale, "simp")
    assert isinstance(result.outcome, ReplFailure) and result.outcome.kind is ReplFailureKind.REPLAY_MISMATCH


async def test_out_of_memory_crash_is_a_repl_failure(unchecked_repl: LeanRepl) -> None:
    result = await unchecked_repl.apply_tactic(await start(unchecked_repl, STATEMENT), OUT_OF_MEMORY_TACTIC)
    assert isinstance(result.outcome, ReplFailure) and result.outcome.kind is ReplFailureKind.CRASHED


async def test_state_survives_an_out_of_memory_crash(unchecked_repl: LeanRepl) -> None:
    state = await start(unchecked_repl, STATEMENT)
    await unchecked_repl.apply_tactic(state, OUT_OF_MEMORY_TACTIC)
    result = await unchecked_repl.apply_tactic(state, "omega")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def test_block_keeps_the_longest_valid_prefix(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, "subst h₀\nexact undefined_lemma\nomega")
    assert (result.applied_tactics, type(result.failure)) == (("subst h₀",), LeanError)


async def test_block_stops_applying_tactics_once_the_theorem_is_proved(proving_block: BlockResult) -> None:
    assert proving_block.applied_tactics == ("omega",)


async def test_block_that_proves_the_theorem_reports_no_failure(proving_block: BlockResult) -> None:
    assert proving_block.failure is None


async def test_block_that_proves_the_theorem_ends_in_a_proved_state(proving_block: BlockResult) -> None:
    assert proving_block.state.is_proved


async def test_block_applies_bullets_as_single_steps(repl: LeanRepl) -> None:
    result = await repl.apply_block(await start(repl, CONJUNCTION_STATEMENT), "constructor\n· exact h₀\n· exact h₁")
    assert (result.applied_tactics, result.state.is_proved) == (("constructor", "· exact h₀", "· exact h₁"), True)


@pytest.mark.parametrize(
    ("statement", "block"),
    [
        (STATEMENT, "/- First substitute\nthen compute -/\nsubst h₀\nsubst h₁\nrfl"),
        (CONJUNCTION_STATEMENT, "constructor <;>\nassumption"),
        (STATEMENT, "nlinarith [sq_nonneg (a - b),\nsq_nonneg (a + b)]"),
        (STATEMENT, "calc a + b = 2 + b := by rw [h₀]\n_ = 5 := by rw [h₁]"),
        (STATEMENT, "nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)\n]"),
        (STATEMENT, "have h : a = 2 ∧\nb = 3 := ⟨h₀, h₁⟩\nomega"),
    ],
)
async def test_block_with_continuation_lines_proves_the_theorem(repl: LeanRepl, statement: str, block: str) -> None:
    result = await repl.apply_block(await start(repl, statement), block)
    assert result.state.is_proved, result.failure


async def test_verification_accepts_a_complete_proof(repl: LeanRepl) -> None:
    result = await repl.verify_proof(STATEMENT, "subst h₀\nsubst h₁\nrfl", HEADER)
    assert result.verified, result.problems


@pytest.mark.parametrize(
    "proof",
    [
        "sorry",
        "native_decide",
        "exact undefined_lemma",
        "subst h₀",
        "omega\n#exit",
        "omega\n\ntheorem extra : True := trivial",
    ],
)
async def test_verification_rejects_an_invalid_proof(repl: LeanRepl, proof: str) -> None:
    result = await repl.verify_proof(STATEMENT, proof, HEADER)
    assert not result.verified


async def test_verification_reports_the_real_axioms_despite_a_spoofed_trace(repl: LeanRepl) -> None:
    result = await repl.verify_proof(STATEMENT, "trace \"'test_sum' does not depend on any axioms\"\nomega", HEADER)
    assert result.axioms == ("propext", "Quot.sound")


async def test_spoofed_axiom_trace_does_not_hide_a_nonstandard_axiom(unchecked_repl: LeanRepl) -> None:
    proof = "trace \"'two_plus_three' does not depend on any axioms\"\nnative_decide"
    result = await unchecked_repl.verify_proof(CLOSED_STATEMENT, proof, HEADER)
    assert not result.verified


async def test_verify_state_accepts_the_proof_as_executed(repl: LeanRepl, limited_proof: ProofState) -> None:
    result = await repl.verify_state(limited_proof)
    assert result.verified, result.problems


async def test_verify_state_reports_that_the_plain_proof_fails(repl: LeanRepl, limited_proof: ProofState) -> None:
    result = await repl.verify_state(limited_proof)
    assert result.plain_verified is False


async def test_wrapped_verification_rejects_a_sorry_step(unchecked_repl: LeanRepl) -> None:
    state = ProofState(HEADER, STATEMENT, ("exact sorryAx _ false",), (), 0, 0, (200_000,))
    result = await unchecked_repl.verify_state(state)
    assert not result.verified


async def test_memory_usage_reports_the_resident_set(repl: LeanRepl) -> None:
    await repl.start()
    usage = repl.memory_usage()
    assert usage.resident_bytes > usage.anonymous_bytes > 0


async def test_concurrent_lake_environment_calls_share_one_result() -> None:
    directory = PROJECT_DIRECTORY / ".lake" / ".."
    environments = await asyncio.gather(*(lake_environment(directory) for _ in range(4)))
    assert all(environment is environments[0] for environment in environments)


async def test_repl_process_dies_with_its_parent() -> None:
    script = (
        "import asyncio\nfrom lean_search.lean import LeanRepl\n"
        "async def main():\n    repl = LeanRepl()\n    await repl.start()\n"
        "    print(repl.process_id, flush=True)\n    await asyncio.sleep(120)\n"
        "asyncio.run(main())"
    )
    parent = await asyncio.create_subprocess_exec(sys.executable, "-c", script, stdout=asyncio.subprocess.PIPE)
    assert parent.stdout is not None
    repl_process_id = int(await parent.stdout.readline())
    parent.kill()
    await parent.wait()
    await asyncio.sleep(2.0)
    status = Path(f"/proc/{repl_process_id}/status")
    assert not status.exists() or "State:\tZ" in status.read_text()


async def test_pool_serves_concurrent_proofs() -> None:
    async def prove(pool: LeanReplPool) -> bool:
        async with pool.acquire() as repl:
            result = await repl.apply_tactic(await start(repl, STATEMENT), "omega")
            return isinstance(result.outcome, ProofState) and result.outcome.is_proved

    async with LeanReplPool(2) as pool:
        proved = await asyncio.gather(*(prove(pool) for _ in range(4)))
    assert all(proved)


async def test_pool_restarts_a_process_past_its_limits_on_release() -> None:
    async with LeanReplPool(1, LeanReplConfig(max_proof_states=2), restart_fraction=0.5) as pool:
        async with pool.acquire() as repl:
            await repl.start_proof(STATEMENT, HEADER)
        async with pool.acquire() as repl:
            restart_count = repl.restart_count
    assert restart_count == 1


async def test_pool_restarts_a_process_whose_user_raised() -> None:
    async with LeanReplPool(1) as pool:
        with pytest.raises(RuntimeError):
            async with pool.acquire():
                raise RuntimeError("the search failed")
        async with pool.acquire() as repl:
            restart_count = repl.restart_count
    assert restart_count == 1


async def test_pool_hands_out_a_synchronized_process_after_a_cancelled_search() -> None:
    in_flight = asyncio.Event()

    async def cancelled_search(pool: LeanReplPool) -> None:
        async with pool.acquire() as repl:
            state = await start(repl, STATEMENT)
            in_flight.set()
            await repl.apply_tactic(state, SLEEPING_PROOF)

    async with LeanReplPool(1, SLEEP_ALLOWED) as pool:
        task = asyncio.create_task(cancelled_search(pool))
        await in_flight.wait()
        await asyncio.sleep(0.3)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        async with pool.acquire() as repl:
            result = await repl.apply_tactic(await start(repl, STATEMENT), "subst h₀")
    assert isinstance(result.outcome, ProofState) and result.outcome.goals[0].endswith("⊢ 2 + b = 5")
