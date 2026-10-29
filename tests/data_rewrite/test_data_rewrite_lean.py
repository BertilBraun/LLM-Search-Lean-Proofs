import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.corpora.records import DataSplit, ProofRecord, TracedStep
from lean_search.data_rewrite.naming import (
    NameChange,
    NameSource,
    NamingConfig,
    NamingSubject,
    Renaming,
    RuleBasedNamer,
    plan_renamings,
)
from lean_search.data_rewrite.records import (
    ExampleStatus,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.data_rewrite.replay import ReplayLimits
from lean_search.data_rewrite.rewrite import ReasoningItem, rewrite_example, rewrite_proof
from lean_search.data_rewrite.statement_renaming import verify_against_original
from lean_search.lean import LeanRepl, ProofState
from lean_search.lean.plans import plan_block
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin

HEADER = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 400000\n\nopen BigOperators Real Nat Topology Rat\n\n"
)
STATEMENT = "theorem test_rewrite (x y : ℝ) (h₀ : 0 < x) (h₁ : x + y = 3) (h₂ : y = 1) : x = 2 := by"
NESTED_PROOF = "have h₃ : x = 3 - y := by\n  linarith\nrw [h₂] at h₃\nlinarith"
CLOSED_EARLY_PROOF = "have h₃ : x = 3 - y := by\n  linarith\n  try simp\nrw [h₂] at h₃\nlinarith"
BLOCK = "have h₄ : x + 1 = 3 := by\n  rw [h₂] at h₁\n  linarith\nlinarith"
REASONING = "From h₁ and h₂, x + 1 = 3, so x = 2."
LIMITS = ReplayLimits(200_000, 60.0)
CONFIG = NamingConfig()

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl() as lean_repl:
        yield lean_repl


def record(proof: str) -> ProofRecord:
    return ProofRecord("test", "test/1", "test", HEADER, STATEMENT, proof, "")


async def renaming_of(statement: str, tactics: tuple[str, ...]) -> Renaming:
    (renaming,) = await plan_renamings([NamingSubject(statement, tactics)], RuleBasedNamer(CONFIG), CONFIG)
    return renaming


async def rewritten(repl: LeanRepl, proof: str, check_original: bool = False) -> RewrittenProof:
    renaming = await renaming_of(STATEMENT, plan_block(proof).texts)
    return await rewrite_proof(repl, record(proof), renaming, LIMITS, check_original)


async def test_renamed_proof_verifies_against_the_original_statement(repl: LeanRepl) -> None:
    changes = (NameChange("h₀", "hx_pos", NameSource.RULES), NameChange("h₂", "hy", NameSource.RULES))
    verification = await verify_against_original(repl, HEADER, STATEMENT, changes, "rw [hy] at h₁\nlinarith [hx_pos]")
    assert verification.verified


async def test_proof_with_unrenamed_names_does_not_verify_against_the_original(repl: LeanRepl) -> None:
    changes = (NameChange("h₂", "hy", NameSource.RULES),)
    verification = await verify_against_original(repl, HEADER, STATEMENT, changes, "rw [h₂] at h₁\nlinarith")
    assert not verification.verified


async def test_nested_have_proof_is_kept_as_flat_tactics(repl: LeanRepl) -> None:
    proof = await rewritten(repl, NESTED_PROOF)
    assert (proof.status, proof.tactics) == (
        ProofStatus.KEPT,
        ("have h₃ : x = 3 - y", "linarith", "rw [h₂] at h₃", "linarith"),
    )


async def test_flat_proof_records_the_goals_before_every_tactic(repl: LeanRepl) -> None:
    proof = await rewritten(repl, NESTED_PROOF)
    assert [len(goals) for goals in proof.goals] == [1, 2, 1, 1, 0]


async def test_named_proof_replays_with_the_renamed_states(repl: LeanRepl) -> None:
    proof = await rewritten(repl, NESTED_PROOF)
    assert (proof.named.status, proof.named.tactics) == (
        NamedStatus.RENAMED,
        ("have hxy_2 : x = 3 - y", "linarith", "rw [hy] at hxy_2", "linarith"),
    )


async def test_named_states_show_the_new_names(repl: LeanRepl) -> None:
    proof = await rewritten(repl, NESTED_PROOF)
    assert proof.named.goals[0] == ("x y : ℝ\nhx_pos : 0 < x\nhxy : x + y = 3\nhy : y = 1\n⊢ x = 2",)


async def test_named_proof_verifies_against_the_original_statement(repl: LeanRepl) -> None:
    proof = await rewritten(repl, NESTED_PROOF, check_original=True)
    assert proof.named.original_verified is True


async def test_nested_proof_closing_early_is_a_behaviour_change(repl: LeanRepl) -> None:
    proof = await rewritten(repl, CLOSED_EARLY_PROOF)
    assert proof.status is ProofStatus.FLATTENING_CHANGED_BEHAVIOUR


async def test_proof_that_fails_as_written_is_dropped(repl: LeanRepl) -> None:
    proof = await rewritten(repl, "exact h₀")
    assert proof.status is ProofStatus.ORIGINAL_FAILS


async def test_have_shadowing_a_hypothesis_is_renamed_with_it(repl: LeanRepl) -> None:
    proof = await rewritten(repl, "have h₂ : y = 1 := h₂\nrw [h₂] at h₁\nlinarith")
    assert (proof.named.status, proof.named.tactics) == (
        NamedStatus.RENAMED,
        ("have hy : y = 1 := hy", "rw [hy] at hxy", "linarith"),
    )


async def root_goals(repl: LeanRepl) -> tuple[str, ...]:
    outcome = (await repl.start_proof(STATEMENT, HEADER)).outcome
    assert isinstance(outcome, ProofState)
    return outcome.goals


def traced_step(goals: tuple[str, ...]) -> TracedStep:
    return TracedStep(
        "test", "test/1", "test", DataSplit.TRAIN, HEADER, STATEMENT, 0, 1, 1, goals, BLOCK, (), (), 200_000, 0.1
    )


async def rewritten_example(repl: LeanRepl, prompt_goals: tuple[str, ...] | None = None) -> RewrittenExample:
    goals = await root_goals(repl)
    example = ReasoningExample(
        "test", "test/1", 0, prompt_goals or goals, BLOCK, REASONING, "", ReasoningOrigin.SAMPLED, True
    )
    renaming = await renaming_of(STATEMENT, plan_block(BLOCK).texts)
    return await rewrite_example(repl, ReasoningItem(example, DataSplit.TRAIN), traced_step(goals), renaming, LIMITS)


async def test_reasoning_example_block_is_flattened(repl: LeanRepl) -> None:
    example = await rewritten_example(repl)
    assert (example.status, example.tactic_block) == (
        ExampleStatus.KEPT,
        "have h₄ : x + 1 = 3\nrw [h₂] at h₁\nlinarith\nlinarith",
    )


async def test_named_reasoning_example_renames_its_explanation(repl: LeanRepl) -> None:
    example = await rewritten_example(repl)
    assert (example.named.status, example.named.reasoning) == (
        NamedStatus.RENAMED,
        "From hxy and hy, x + 1 = 3, so x = 2.",
    )


async def test_example_whose_prompt_is_not_the_rebuilt_state_is_dropped(repl: LeanRepl) -> None:
    example = await rewritten_example(repl, ("x : ℝ\n⊢ x = 2",))
    assert example.status is ExampleStatus.STATE_MISMATCH
