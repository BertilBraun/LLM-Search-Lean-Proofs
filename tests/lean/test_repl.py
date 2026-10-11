import asyncio
import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.lean import LeanError, LeanRepl, LeanReplConfig, LeanReplPool, LeanTimeout, ProofState
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by\n"
CONJUNCTION_STATEMENT = "theorem test_and (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a = 2 ∧ b = 3 := by\n"
SLOW_TACTIC = "exact?"  # builds its lemma index on first use, which takes far longer than the test timeout

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig(tactic_timeout_seconds=30.0)) as lean_repl:
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


async def test_start_proof_returns_the_statement_goal(initial_state: ProofState) -> None:
    assert initial_state.goals == ("a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5",)


async def test_invalid_statement_is_an_error(repl: LeanRepl) -> None:
    result = await repl.start_proof('theorem broken (x : ℕ) : x = "text" := by\n', HEADER)
    assert isinstance(result.outcome, LeanError)


async def test_valid_tactic_changes_the_goal(substituted_state: ProofState) -> None:
    assert substituted_state.goals[0].endswith("⊢ 2 + b = 5")


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
    "tactic", ["sorry", "admit", "native_decide", "set_option maxHeartbeats 0 in omega", "exact sorryAx _ false"]
)
async def test_forbidden_tactic_is_rejected(repl: LeanRepl, initial_state: ProofState, tactic: str) -> None:
    result = await repl.apply_tactic(initial_state, tactic)
    assert isinstance(result.outcome, LeanError) and result.outcome.message.startswith("Forbidden tokens")


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


async def test_block_keeps_the_longest_valid_prefix(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, "subst h₀\nexact undefined_lemma\nomega")
    assert (result.applied_tactics, type(result.failure)) == (("subst h₀",), LeanError)


async def test_block_stops_once_the_theorem_is_proved(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, "omega\nsimp")
    assert (result.applied_tactics, result.state.is_proved, result.failure) == (("omega",), True, None)


async def test_block_applies_bullets_as_single_steps(repl: LeanRepl) -> None:
    start = await repl.start_proof(CONJUNCTION_STATEMENT, HEADER)
    assert isinstance(start.outcome, ProofState)
    result = await repl.apply_block(start.outcome, "constructor\n· exact h₀\n· exact h₁")
    assert (result.applied_tactics, result.state.is_proved) == (("constructor", "· exact h₀", "· exact h₁"), True)


async def test_verification_accepts_a_complete_proof(repl: LeanRepl) -> None:
    result = await repl.verify_proof(STATEMENT, "subst h₀\nsubst h₁\nrfl", HEADER)
    assert result.verified, result.problems


@pytest.mark.parametrize("proof", ["sorry", "native_decide", "exact undefined_lemma", "subst h₀", "omega\n#exit"])
async def test_verification_rejects_an_invalid_proof(repl: LeanRepl, proof: str) -> None:
    result = await repl.verify_proof(STATEMENT, proof, HEADER)
    assert not result.verified


async def test_memory_usage_reports_the_resident_set(repl: LeanRepl) -> None:
    await repl.start()
    usage = repl.memory_usage()
    assert usage.resident_bytes > usage.anonymous_bytes > 0


async def test_pool_serves_concurrent_proofs() -> None:
    async def prove(pool: LeanReplPool) -> bool:
        async with pool.acquire() as repl:
            start = await repl.start_proof(STATEMENT, HEADER)
            assert isinstance(start.outcome, ProofState)
            result = await repl.apply_tactic(start.outcome, "omega")
            return isinstance(result.outcome, ProofState) and result.outcome.is_proved

    async with LeanReplPool(2) as pool:
        proved = await asyncio.gather(*(prove(pool) for _ in range(4)))
    assert all(proved)


async def test_wall_clock_timeout_restarts_the_process_before_returning(
    repl: LeanRepl, initial_state: ProofState
) -> None:
    await repl.apply_tactic(initial_state, SLOW_TACTIC, heartbeats=0, timeout_seconds=2.0)
    assert repl.process_id is not None


async def test_pool_restarts_a_process_past_its_limits_on_release() -> None:
    async with LeanReplPool(1, LeanReplConfig(max_proof_states=2), restart_fraction=0.5) as pool:
        async with pool.acquire() as repl:
            await repl.start_proof(STATEMENT, HEADER)
        async with pool.acquire() as repl:
            restart_count = repl.restart_count
    assert restart_count == 1
