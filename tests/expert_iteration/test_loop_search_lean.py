import shutil
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_config import HarvestConfig
from lean_search.expert_iteration.loop_search import LoopSearch, PauseGate
from lean_search.expert_iteration.proofs import found_proofs
from lean_search.lean import LeanRepl, LeanReplConfig
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.search import (
    AStar,
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    Node,
    NodeStatus,
    SearchConfig,
    SearchContext,
    StepSource,
    ValueEstimates,
    tree_record,
)

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
STATEMENT = "theorem add_zero_both : ∀ n m : ℕ, n + 0 + m = n + m := by"
PROBLEM = Problem("lean_workbook.add_zero_both", Split.VALID, HEADER, STATEMENT, "", "")

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


class TwoIntroductionsThenSimp:
    """Two ways into the goal at the root, each closed by simp."""

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        steps = ("intro n m", "intro n") if node.depth == 0 else ("simp",)
        yield CandidateBatch(tuple(Candidate(step, StepSource.POLICY, log_probability=-1.0) for step in steps))


class AdjustableEstimator:
    """The same h for every state; changing it stands in for new weights behind the same server."""

    def __init__(self, remaining_steps: float) -> None:
        self.remaining_steps = remaining_steps

    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        return ValueEstimates(tuple(self.remaining_steps for _ in nodes))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig()) as started:
        yield started


async def searched(
    repl: LeanRepl, harvest: HarvestConfig, estimator: AdjustableEstimator, max_expansions: int = 4
) -> tuple[LoopSearch, CompletedSearch]:
    search = LoopSearch(
        PROBLEM,
        repl,
        TwoIntroductionsThenSimp(),
        AStar(estimator, 0.5),
        SearchConfig(max_expansions=max_expansions),
        harvest,
        PauseGate(),
    )
    return search, await search.run()


def proof_step_sequences(completed: CompletedSearch) -> set[tuple[str, ...]]:
    assert completed.tree is not None
    record = tree_record(completed.tree, STATEMENT, completed.result)
    return {tuple(step.step for step in proof.steps) for proof in found_proofs("loop", record)}


@pytest.mark.parametrize(
    ("harvest", "proofs"),
    [
        (HarvestConfig(max_remaining_steps=1.5, max_expansions=8), {("intro n m", "simp"), ("intro n", "simp")}),
        (HarvestConfig(max_remaining_steps=1.5, max_expansions=0), {("intro n m", "simp")}),
        (HarvestConfig(max_remaining_steps=0.5, max_expansions=8), {("intro n m", "simp")}),
    ],
)
async def test_harvesting_proves_the_near_frontier_after_the_first_proof(
    repl: LeanRepl, harvest: HarvestConfig, proofs: set[tuple[str, ...]]
) -> None:
    _, completed = await searched(repl, harvest, AdjustableEstimator(1.0))
    assert proof_step_sequences(completed) == proofs


async def test_harvesting_keeps_the_cost_of_the_first_proof(repl: LeanRepl) -> None:
    _, completed = await searched(
        repl, HarvestConfig(max_remaining_steps=1.5, max_expansions=8), AdjustableEstimator(1.0)
    )
    assert completed.result.solved_at is not None and completed.result.solved_at.expansions == 2


async def test_rescoring_takes_the_new_estimates(repl: LeanRepl) -> None:
    estimator = AdjustableEstimator(1.0)
    search, completed = await searched(repl, HarvestConfig(max_expansions=0), estimator, max_expansions=1)
    estimator.remaining_steps = 4.0
    await search.rescore()
    assert completed.tree is not None
    frontier = [completed.tree.node(node_id) for node_id in search.frontier.node_ids()]
    assert [(node.status, node.value_estimate, node.priority) for node in frontier] == [
        (NodeStatus.OPEN, 4.0, 3.0),
        (NodeStatus.OPEN, 4.0, 3.0),
    ]
