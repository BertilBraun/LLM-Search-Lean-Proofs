"""The held-out states' flattened reference steps in real Lean (run on the node; skipped without the Lean REPL)."""

import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.corpora.records import DataSplit, TracedStep
from lean_search.lean import LeanRepl
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.offline_held_out import flat_reference

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by"
ROOT = "a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5"

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


def held_out_state(step: str) -> ReasoningState:
    traced = TracedStep(
        "test", "test/p", "p", DataSplit.TRAIN, HEADER, STATEMENT, 0, 2, 2, (ROOT,), step, (), (), 0, 0.0
    )
    return ReasoningState("test/p#0", traced, ((),), False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl() as lean_repl:
        yield lean_repl


async def test_a_nested_have_gives_the_state_inside_it(repl: LeanRepl) -> None:
    found = await flat_reference(repl, held_out_state("have h : a + b = 2 + 3 := by\n  rw [h₀, h₁]"))
    assert len(found.goal_keys[0]) == 2


async def test_a_step_that_does_not_run_is_recorded_as_failed(repl: LeanRepl) -> None:
    found = await flat_reference(repl, held_out_state("exact h₀"))
    assert (found.goal_keys, bool(found.failure)) == ((), True)
