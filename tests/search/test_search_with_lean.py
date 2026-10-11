import dataclasses
import shutil
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.lean import FORBIDDEN_TOKENS, LeanRepl, LeanReplConfig, LeanReplPool
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.search import (
    AutomationConfig,
    AutomationExpander,
    Candidate,
    CandidateBatches,
    CompletedSearch,
    CompositeExpander,
    DepthPlusGoals,
    EdgeOutcome,
    Expander,
    FailureKind,
    Node,
    NodeStatus,
    SearchConfig,
    SearchContext,
    StepSource,
    StopReason,
    search_problems,
    search_theorem,
)

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
TRIVIAL = "theorem trivial_sum : (2 : ℕ) + 2 = 4 := by\n"
NEEDS_INTRO = "theorem needs_intro : ∀ n : ℕ, n + 0 = n := by\n"
FALSE = "theorem false_statement : (1 : ℕ) = 2 := by\n"
ARITHMETIC = "theorem squares (a b : ℕ) (h : a = b) : a * a = b * b := by\n"
# Every application adds another hypothesis, so the search never runs out of new states.
ALWAYS_PROGRESSES = "have : (1 : ℕ) = 1 := rfl"
SLEEP = "sleep 60000"

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


class FixedPolicy:
    def __init__(self, steps: Sequence[str], generated_tokens: int = 10) -> None:
        self.steps = tuple(steps)
        self.generated_tokens = generated_tokens
        self.calls = 0

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        self.calls += 1
        yield [
            Candidate(step, StepSource.POLICY, log_probability=-0.5, generated_tokens=self.generated_tokens)
            for step in self.steps
        ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig()) as lean_repl:
        await lean_repl.load_header(HEADER)
        yield lean_repl


def problem(statement: str) -> Problem:
    name = statement.split()[1]
    return Problem(name, Split.VALID, HEADER, statement, informal_prefix="", goal="")


def automation(*tactics: str, heartbeats: int | None = None) -> AutomationExpander:
    return AutomationExpander(
        AutomationConfig(tactics=tactics, heartbeats=heartbeats) if tactics else AutomationConfig()
    )


async def search(
    repl: LeanRepl, statement: str, expander: Expander | None = None, **config_fields: object
) -> CompletedSearch:
    config = dataclasses.replace(SearchConfig(max_expansions=8, tactic_timeout_seconds=20.0), **config_fields)
    return await search_theorem(problem(statement), repl, expander or automation(), DepthPlusGoals(), config)


async def test_automation_solves_a_trivial_theorem(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL)
    assert completed.result.proved


async def test_solve_is_recorded_with_the_accounting_at_that_moment(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL)
    assert completed.result.solved_at is not None and completed.result.solved_at.expansions == 1


async def test_structural_step_then_automation_finds_a_two_step_proof(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, automation("rfl", "intros"))
    assert completed.result.proof_steps == ("intros", "rfl")


async def test_proof_path_nodes_are_marked_proved(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, automation("rfl", "intros"))
    assert completed.tree is not None
    assert [node.node_id for node in completed.tree.nodes if node.status == NodeStatus.PROVED] == [0, 1, 2]


async def test_false_statement_is_not_proved(repl: LeanRepl) -> None:
    completed = await search(repl, FALSE, max_expansions=16)
    assert (completed.result.proved, completed.result.stop_reason) == (False, StopReason.FRONTIER_EXHAUSTED)


async def test_false_statement_root_is_marked_failed(repl: LeanRepl) -> None:
    completed = await search(repl, FALSE, max_expansions=16)
    assert completed.tree is not None and completed.tree.root.status == NodeStatus.FAILED


async def test_errors_are_recorded_as_failed_edges(repl: LeanRepl) -> None:
    completed = await search(repl, FALSE)
    assert completed.tree is not None
    decide = next(edge for edge in completed.tree.edges if edge.text == "decide")
    assert (decide.outcome, decide.failure and decide.failure.kind) == (EdgeOutcome.FAILED, FailureKind.ERROR)


async def test_heartbeat_timeouts_are_recorded_as_failed_edges(repl: LeanRepl) -> None:
    expander = automation("nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]", heartbeats=1)
    completed = await search(repl, ARITHMETIC, expander)
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.outcome, edge.failure and edge.failure.kind) == (EdgeOutcome.FAILED, FailureKind.HEARTBEAT_TIMEOUT)


async def test_unchanged_state_is_a_duplicate_of_its_parent(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, automation("skip"))
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.outcome, edge.target_id) == (EdgeOutcome.DUPLICATE, 0)


async def test_forbidden_step_is_rejected_before_lean_runs(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL, automation("exact?"))
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.outcome, edge.lean_seconds) == (EdgeOutcome.REJECTED, 0.0)


async def test_block_keeps_the_longest_valid_prefix_as_the_child(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, FixedPolicy(["intros\nexact undefined_lemma"]), max_expansions=1)
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.outcome, edge.applied_tactics, edge.total_tactics, edge.failure and edge.failure.kind) == (
        EdgeOutcome.CHILD,
        1,
        2,
        FailureKind.ERROR,
    )


async def test_repeated_candidates_run_once(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, FixedPolicy(["intros", " intros "]), max_expansions=1)
    assert completed.tree is not None
    assert [edge.outcome for edge in completed.tree.edges] == [EdgeOutcome.CHILD, EdgeOutcome.REPEATED]


async def test_expansion_budget_is_respected(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, automation(ALWAYS_PROGRESSES), max_expansions=3)
    assert (completed.result.accounting.expansions, completed.result.stop_reason) == (3, StopReason.EXPANSION_BUDGET)


async def test_depth_budget_bounds_the_tree(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, automation(ALWAYS_PROGRESSES), max_expansions=100, max_depth=2)
    assert (completed.result.max_depth_reached, completed.result.stop_reason) == (2, StopReason.FRONTIER_EXHAUSTED)


async def test_wall_clock_budget_is_respected(repl: LeanRepl) -> None:
    expander = automation(ALWAYS_PROGRESSES)
    completed = await search(repl, ARITHMETIC, expander, max_expansions=10**6, max_depth=10**6, max_wall_seconds=1.0)
    assert completed.result.stop_reason == StopReason.WALL_CLOCK_BUDGET


async def test_wall_clock_budget_stops_within_one_step(repl: LeanRepl) -> None:
    expander = automation(ALWAYS_PROGRESSES)
    completed = await search(repl, ARITHMETIC, expander, max_expansions=10**6, max_depth=10**6, max_wall_seconds=1.0)
    assert completed.result.accounting.wall_seconds < 2.0


async def test_generated_token_budget_is_respected(repl: LeanRepl) -> None:
    policy = FixedPolicy([ALWAYS_PROGRESSES], generated_tokens=10)
    completed = await search(repl, ARITHMETIC, policy, max_expansions=100, max_generated_tokens=25)
    assert (completed.result.accounting.generated_tokens, completed.result.stop_reason) == (
        30,
        StopReason.TOKEN_BUDGET,
    )


async def test_composite_skips_the_second_expander_once_automation_closes_the_goal(repl: LeanRepl) -> None:
    policy = FixedPolicy(["norm_num"])
    await search(repl, TRIVIAL, CompositeExpander([automation("decide"), policy]))
    assert policy.calls == 0


async def test_composite_runs_the_second_expander_after_automation(repl: LeanRepl) -> None:
    policy = FixedPolicy(["intros"])
    completed = await search(repl, NEEDS_INTRO, CompositeExpander([automation("rfl"), policy]), max_expansions=1)
    assert completed.tree is not None
    assert [edge.source for edge in completed.tree.edges] == [StepSource.AUTOMATION, StepSource.POLICY]


async def test_wall_clock_timeout_disables_the_tactic_for_the_rest_of_the_search() -> None:
    sleep_allowed = LeanReplConfig(forbidden_tokens=FORBIDDEN_TOKENS - {"sleep"})
    config = AutomationConfig(tactics=(SLEEP, ALWAYS_PROGRESSES), timeout_seconds=2.0)
    async with LeanRepl(sleep_allowed) as sleep_repl:
        completed = await search(sleep_repl, ARITHMETIC, AutomationExpander(config), max_expansions=2)
    assert completed.tree is not None
    assert [edge.text for edge in completed.tree.edges] == [SLEEP, ALWAYS_PROGRESSES, ALWAYS_PROGRESSES]


async def test_found_proof_also_verifies_without_heartbeat_wrappers(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, automation("rfl", "intros"))
    assert completed.result.plain_verified is True


async def test_concurrent_searches_share_a_pool() -> None:
    problems = [problem(TRIVIAL), problem(NEEDS_INTRO), problem(FALSE)]
    async with LeanReplPool(2) as pool:
        await pool.start([HEADER])

        async def ignore(completed: CompletedSearch) -> None:
            pass

        results = await search_problems(
            problems, pool, automation(), DepthPlusGoals(), SearchConfig(max_expansions=8), 2, ignore
        )
    assert [result.proved for result in results] == [True, True, False]
