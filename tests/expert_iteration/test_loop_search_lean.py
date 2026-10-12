import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_config import HarvestConfig
from lean_search.expert_iteration.loop_search import (
    LoopSearch,
    PauseGate,
    SearchControls,
    StageResult,
    ValueClock,
    never_continue,
)
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
    repl: LeanRepl,
    harvest: HarvestConfig,
    estimator: AdjustableEstimator,
    stage_expansions: tuple[int, ...] = (4,),
    continue_search: Callable[[StageResult], Awaitable[bool]] = never_continue,
    controls: SearchControls | None = None,
) -> tuple[LoopSearch, CompletedSearch]:
    search = LoopSearch(
        PROBLEM,
        repl,
        TwoIntroductionsThenSimp(),
        AStar(estimator, 0.5),
        [SearchConfig(max_expansions=expansions) for expansions in stage_expansions],
        0,
        harvest,
        controls or SearchControls(PauseGate(), ValueClock()),
        continue_search,
    )
    return search, await search.run()


async def always_continue(result: StageResult) -> bool:
    return True


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
    search, completed = await searched(repl, HarvestConfig(max_expansions=0), estimator, (1,))
    estimator.remaining_steps = 4.0
    await search.rescore()
    assert completed.tree is not None
    frontier = [completed.tree.node(node_id) for node_id in search.frontier.node_ids()]
    assert [(node.status, node.value_estimate, node.priority) for node in frontier] == [
        (NodeStatus.OPEN, 4.0, 3.0),
        (NodeStatus.OPEN, 4.0, 3.0),
    ]


@pytest.mark.parametrize(
    ("continue_search", "outcome"),
    [
        (never_continue, [("expansion_budget", False)]),
        (always_continue, [("expansion_budget", False), ("proved", True)]),
    ],
    ids=["stops", "escalates"],
)
async def test_a_search_escalates_on_the_same_tree(
    repl: LeanRepl,
    continue_search: Callable[[StageResult], Awaitable[bool]],
    outcome: list[tuple[str, bool]],
) -> None:
    harvest = HarvestConfig(max_expansions=0)
    search, _ = await searched(repl, harvest, AdjustableEstimator(1.0), (1, 4), continue_search)
    assert [(result.stop_reason, result.proved) for result in search.stage_results] == outcome


async def test_a_stage_counts_only_its_own_expansions(repl: LeanRepl) -> None:
    harvest = HarvestConfig(max_expansions=0)
    search, _ = await searched(repl, harvest, AdjustableEstimator(1.0), (1, 4), always_continue)
    assert [result.expansions for result in search.stage_results] == [1, 1]


def publishing_between_stages(
    estimator: AdjustableEstimator, clock: ValueClock
) -> Callable[[StageResult], Awaitable[bool]]:
    """Continues after the first stage as if a new value model, which puts every state 4 steps away, was published."""

    async def publish(result: StageResult) -> bool:
        estimator.remaining_steps = 4.0
        clock.version += 1
        return True

    return publish


@pytest.mark.parametrize(("lazy_rescore_states", "rescored"), [(32, 2), (0, 0)])
async def test_stale_frontier_states_are_rescored_when_they_reach_the_top(
    repl: LeanRepl, lazy_rescore_states: int, rescored: int
) -> None:
    estimator, clock = AdjustableEstimator(1.0), ValueClock()
    controls = SearchControls(PauseGate(), clock, lazy_rescore_states)
    harvest = HarvestConfig(max_expansions=0)
    continue_search = publishing_between_stages(estimator, clock)
    search, _ = await searched(repl, harvest, estimator, (1, 4), continue_search, controls)
    assert search.lazily_rescored == rescored


async def test_a_lazily_rescored_state_carries_the_new_estimate(repl: LeanRepl) -> None:
    estimator, clock = AdjustableEstimator(1.0), ValueClock()
    controls = SearchControls(PauseGate(), clock, 32)
    continue_search = publishing_between_stages(estimator, clock)
    search, completed = await searched(
        repl, HarvestConfig(max_expansions=0), estimator, (1, 4), continue_search, controls
    )
    assert completed.tree is not None
    children = [completed.tree.node(child_id) for child_id in completed.tree.root.child_ids]
    assert [child.value_estimate for child in children] == [4.0, 4.0]
