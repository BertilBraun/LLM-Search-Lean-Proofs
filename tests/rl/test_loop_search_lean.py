import shutil
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.data_rewrite.naming import NameChange, NameSource
from lean_search.data_rewrite.statement_renaming import StatementRenaming
from lean_search.lean import LeanRepl, LeanReplConfig, ProofState
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.rl.renaming import StatementRenamings, search_problem
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    DepthPlusGoals,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_theorem,
)

HEADER = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 400000\n\nopen BigOperators Real Nat Topology Rat\n\n"
)
STATEMENT = "theorem renamed_sum (a b : ℕ) (h₀ : a = b) : a + 0 = b := by"
RENAMED = "theorem renamed_sum (a b : ℕ) (hab : a = b) : a + 0 = b := by"
# Not the original proposition: a proof of it must fail the check against the original statement.
WRONG = "theorem renamed_sum (a b : ℕ) (hab : a = b) : True := by"
CONFIG = SearchConfig(max_expansions=2, tactic_timeout_seconds=20.0, check_identifiers=False)
CHANGES = (NameChange("h₀", "hab", NameSource.RULES),)

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


class FixedPolicy:
    """The policy server's side: proposes the same steps at every expansion."""

    def __init__(self, steps: Sequence[str]) -> None:
        self.steps = tuple(steps)

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(
            tuple(Candidate(step, StepSource.POLICY, log_probability=-0.5) for step in self.steps), 0, 1
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig()) as lean_repl:
        await lean_repl.load_header(HEADER)
        yield lean_repl


def problem() -> Problem:
    return Problem("test.renamed_sum", Split.VALID, HEADER, STATEMENT, "", "")


def renamings(statement: str) -> StatementRenamings:
    return StatementRenamings({problem().name: StatementRenaming(STATEMENT, statement, CHANGES)})


async def test_a_search_starts_from_a_state_inside_the_proof(repl: LeanRepl) -> None:
    goals = ("a b : ℕ\nh₀ : a = b\n⊢ a = b",)
    start = ProofState(HEADER, STATEMENT, ("simp only [Nat.add_zero]",), goals, -1, 0, (200_000,))
    completed = await search_theorem(problem(), repl, FixedPolicy(["exact h₀"]), DepthPlusGoals(), CONFIG, start)
    assert completed.result.proved


async def test_a_proof_of_the_renamed_statement_verifies_against_the_original(repl: LeanRepl) -> None:
    completed = await search_problem(
        problem(), repl, FixedPolicy(["simpa using hab"]), DepthPlusGoals(), CONFIG, renamings(RENAMED)
    )
    assert completed.result.original_verified


async def test_a_proof_that_fails_the_original_statement_counts_as_unsolved(repl: LeanRepl) -> None:
    completed = await search_problem(
        problem(), repl, FixedPolicy(["exact True.intro"]), DepthPlusGoals(), CONFIG, renamings(WRONG)
    )
    assert (completed.result.proved, completed.tree) == (False, None)
