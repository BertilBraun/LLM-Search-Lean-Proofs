"""The offline arm's walk in real Lean (run on the node; skipped without the Lean REPL)."""

import random
import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.rl.offline_walk import WalkSettings, WalkStatus, walk_proof

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
PROBLEM = Problem(
    "test.sum", Split.VALID, HEADER, "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by", "", ""
)
NESTED = "have h : a + b = 2 + 3 := by\n  rw [h₀, h₁]\nsubst h₀\nsubst h₁\nnorm_num"
SETTINGS = WalkSettings(
    heartbeats=50_000,
    timeout_seconds=60.0,
    flatten=True,
    name_hypotheses=True,
    check_identifiers=True,
    environment_names_directory="",
    forbidden_steps=("exact?",),
    forbidden_tokens=FORBIDDEN_TOKENS | {"exact?"},
    max_block_tactics=5,
)

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl() as lean_repl:
        yield lean_repl


def always(block: str) -> bool:
    return True


async def test_a_proof_with_a_nested_have_walks_to_the_end(repl: LeanRepl) -> None:
    found = await walk_proof(repl, PROBLEM, NESTED, SETTINGS, random.Random(0), always)
    assert found.status == WalkStatus.COMPLETE


async def test_the_nested_proof_is_walked_flat(repl: LeanRepl) -> None:
    found = await walk_proof(repl, PROBLEM, NESTED, SETTINGS, random.Random(0), always)
    assert "\n".join(block.block for block in found.blocks).startswith("have h : a + b = 2 + 3\nrw [h₀, h₁]")


async def test_the_first_block_is_prompted_with_the_root_state(repl: LeanRepl) -> None:
    found = await walk_proof(repl, PROBLEM, NESTED, SETTINGS, random.Random(0), always)
    assert found.blocks[0].goals == ("a b : ℕ\nh₀ : a = 2\nh₁ : b = 3\n⊢ a + b = 5",)


async def test_a_proof_that_does_not_close_the_goal_leaves_goals(repl: LeanRepl) -> None:
    found = await walk_proof(repl, PROBLEM, "subst h₀", SETTINGS, random.Random(0), always)
    assert found.status == WalkStatus.GOALS_REMAIN


async def test_a_wrong_step_fails_the_walk(repl: LeanRepl) -> None:
    found = await walk_proof(repl, PROBLEM, "subst h₀\nexact h₁", SETTINGS, random.Random(0), always)
    assert found.status == WalkStatus.BLOCK_FAILED
