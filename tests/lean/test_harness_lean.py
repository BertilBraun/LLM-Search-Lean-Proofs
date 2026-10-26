import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from lean_search.lean import LeanError, LeanRepl, ProofState
from lean_search.lean.hypotheses import has_inaccessible_names, renaming_tactic
from lean_search.lean.identifiers import environment_names
from lean_search.lean.plans import NO_GOALS_MESSAGE, UNSOLVED_MESSAGE, Rejection, plain_plan, plan_block
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by\n"
INTROS_STATEMENT = "theorem test_intros : ∀ n m : ℕ, n + m = m + n := by\n"
NESTED_FAILURE = "have h : a + b = 5 := by\n  subst h₀\n  exact undefined_lemma\nexact h"

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl() as lean_repl:
        yield lean_repl


async def start(repl: LeanRepl, statement: str) -> ProofState:
    result = await repl.start_proof(statement, HEADER)
    assert isinstance(result.outcome, ProofState), result.outcome
    return result.outcome


async def apply(repl: LeanRepl, state: ProofState, *steps: str) -> ProofState:
    for step in steps:
        outcome = (await repl.apply_tactic(state, step)).outcome
        assert isinstance(outcome, ProofState), outcome
        state = outcome
    return state


@pytest_asyncio.fixture(loop_scope="module")
async def initial_state(repl: LeanRepl) -> ProofState:
    return await start(repl, STATEMENT)


async def test_have_without_a_proof_makes_its_type_the_first_goal(repl: LeanRepl, initial_state: ProofState) -> None:
    state = await apply(repl, initial_state, "have h : a + b = 5")
    assert state.goals == (
        "case h\na b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5",
        "a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\nh : a + b = 5\n⊢ a + b = 5",
    )


async def test_obtain_without_a_proof_makes_its_type_the_first_goal(repl: LeanRepl, initial_state: ProofState) -> None:
    state = await apply(repl, initial_state, "obtain ⟨c, hc⟩ : ∃ c : ℕ, c = a")
    assert state.goals[0].endswith("⊢ ∃ c, c = a") and state.goals[1].endswith("hc : c = a\n⊢ a + b = 5")


async def test_flattened_block_keeps_the_valid_prefix_inside_a_nested_proof(
    repl: LeanRepl, initial_state: ProofState
) -> None:
    result = await repl.apply_block(initial_state, plan_block(NESTED_FAILURE))
    assert (result.applied_tactics, type(result.failure)) == (("have h : a + b = 5", "subst h₀"), LeanError)


async def test_flattened_block_reports_the_executed_tactics(repl: LeanRepl, initial_state: ProofState) -> None:
    plan = plan_block(NESTED_FAILURE)
    result = await repl.apply_block(initial_state, plan)
    assert (result.tactics, result.flattened) == (plan.tactics, True)


async def test_unflattened_nested_proof_fails_as_a_whole(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, NESTED_FAILURE)
    assert result.applied_tactics == ()


async def test_flattened_proof_verifies(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, plan_block("have h : a + b = 5 := by\n  rw [h₀, h₁]\nexact h"))
    assert result.state.is_proved and (await repl.verify_state(result.state)).verified


async def test_flattened_proof_inside_a_bullet_verifies(repl: LeanRepl) -> None:
    state = await start(repl, "theorem test_and (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a = 2 ∧ b = 3 := by\n")
    plan = plan_block("constructor\n· have h : a = 2 := by\n    exact h₀\n  exact h\n· exact h₁")
    result = await repl.apply_block(state, plan)
    assert result.state.is_proved and (await repl.verify_state(result.state)).verified


async def test_nested_proof_closed_early_fails_at_its_next_tactic(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, plan_block("have h : a = 2 := by\n  exact h₀\n  simp\nomega"))
    assert (result.applied_tactics, result.failure) == (("have h : a = 2", "exact h₀"), LeanError(NO_GOALS_MESSAGE))


async def test_nested_proof_left_open_stops_before_the_outer_tactics(repl: LeanRepl, initial_state: ProofState) -> None:
    result = await repl.apply_block(initial_state, plan_block("have h : a + b = 5 := by\n  subst h₀\nexact h"))
    assert (len(result.state.goals), result.failure) == (2, LeanError(UNSOLVED_MESSAGE))


async def test_nested_proof_left_open_at_the_end_of_the_block_is_no_failure(
    repl: LeanRepl, initial_state: ProofState
) -> None:
    result = await repl.apply_block(initial_state, plan_block("have h : a + b = 5 := by\n  subst h₀"))
    assert (len(result.state.goals), result.failure) == (2, None)


async def test_rejected_tactic_ends_the_block_with_the_rejection(repl: LeanRepl, initial_state: ProofState) -> None:
    rejection = Rejection(1, "unknown identifier 'undefined_lemma'")
    result = await repl.apply_block(initial_state, plain_plan("subst h₀\nexact undefined_lemma").rejecting(rejection))
    assert (result.applied_tactics, result.failure) == (("subst h₀",), rejection)


@pytest.mark.parametrize(
    ("statement", "steps"),
    [
        (INTROS_STATEMENT, ("intros",)),
        (STATEMENT, ("have h₀ : b = 3 := h₁",)),
        ("theorem test_goals : ∀ n m : ℕ, n = n ∧ m = m := by\n", ("intros", "constructor")),
    ],
)
async def test_renaming_tactic_makes_every_hypothesis_accessible(
    repl: LeanRepl, statement: str, steps: tuple[str, ...]
) -> None:
    state = await apply(repl, await start(repl, statement), *steps)
    tactic = renaming_tactic(state.goals)
    assert tactic is not None
    renamed = await apply(repl, state, tactic)
    assert not has_inaccessible_names(renamed.goals)


async def test_renamed_hypotheses_get_the_announced_names(repl: LeanRepl) -> None:
    state = await apply(repl, await start(repl, INTROS_STATEMENT), "intros")
    renamed = await apply(repl, state, renaming_tactic(state.goals) or "")
    assert renamed.goals == ("n_1 m_1 : ℕ\n⊢ n_1 + m_1 = m_1 + n_1",)


async def test_shadowed_hypothesis_is_renamed_in_place(repl: LeanRepl, initial_state: ProofState) -> None:
    state = await apply(repl, initial_state, "have h₀ : b = 3 := h₁")
    renamed = await apply(repl, state, renaming_tactic(state.goals) or "")
    assert renamed.goals == ("a b : ℕ\nh₀_1 : a = 2\nh₁ h₀ : b = 3\n⊢ a + b = 5",)


async def test_environment_names_are_exported_and_cached(repl: LeanRepl, tmp_path: Path) -> None:
    names = await environment_names(repl, HEADER, tmp_path)
    assert {"Nat.succ_le_iff", "Real.sqrt_nonneg"} <= names.constants and {"nlinarith", "π"} <= names.keywords
