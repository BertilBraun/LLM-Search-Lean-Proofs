import dataclasses
import shutil
from collections.abc import AsyncIterator, Sequence

import pytest
import pytest_asyncio

from lean_search.data import Problem, Split
from lean_search.lean import FORBIDDEN_TOKENS, LeanRepl, LeanReplConfig, LeanReplPool
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.policy.prompts import normalized_block
from lean_search.search import (
    AutomationConfig,
    AutomationExpander,
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    CompositeExpander,
    DepthPlusGoals,
    EdgeOutcome,
    Expander,
    FailureKind,
    Node,
    NodeStatus,
    PriorityFunction,
    Scores,
    SearchConfig,
    SearchContext,
    SearchTree,
    StepSource,
    StopReason,
    search_problems,
    search_theorem,
)
from lean_search.search.texts import GeneratedText, UnparsedSample

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
    """One request per expansion that proposes `steps` (none: all its samples failed) at the given cost."""

    def __init__(self, steps: Sequence[str], generated_tokens: int = 10, prompt_tokens: int = 0) -> None:
        self.steps = tuple(steps)
        self.generated_tokens = generated_tokens
        self.prompt_tokens = prompt_tokens
        self.calls = 0

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        self.calls += 1
        candidates = tuple(Candidate(step, StepSource.POLICY, log_probability=-0.5) for step in self.steps)
        yield CandidateBatch(candidates, self.prompt_tokens, self.generated_tokens)


class ValueLikePriority:
    """Depth plus open goals, charging `prompt_tokens` per scored node like a value model's requests."""

    def __init__(self, prompt_tokens: int = 100) -> None:
        self.prompt_tokens = prompt_tokens

    async def score(self, nodes: Sequence[Node], tree: SearchTree) -> Scores:
        priorities = tuple(float(node.depth + len(node.goals)) for node in nodes)
        return Scores(priorities, priorities, self.prompt_tokens * len(nodes))


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
    repl: LeanRepl,
    statement: str,
    expander: Expander | None = None,
    priority_function: PriorityFunction | None = None,
    **config_fields: object,
) -> CompletedSearch:
    config = dataclasses.replace(SearchConfig(max_expansions=8, tactic_timeout_seconds=20.0), **config_fields)
    return await search_theorem(
        problem(statement), repl, expander or automation(), priority_function or DepthPlusGoals(), config
    )


async def test_automation_solves_a_trivial_theorem(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL)
    assert completed.result.proved


async def test_solve_is_recorded_with_the_accounting_at_that_moment(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL)
    assert completed.result.solved_at is not None and completed.result.solved_at.expansions == 1


async def test_structural_step_then_automation_finds_a_two_step_proof(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, automation("rfl", "intros"))
    assert completed.result.proof_steps == ("intros\nrename_i n_1", "rfl")


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
    completed = await search(repl, NEEDS_INTRO, FixedPolicy(["intros\nexact (1 : ℕ)"]), max_expansions=1)
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


async def test_request_whose_samples_all_failed_is_charged(repl: LeanRepl) -> None:
    policy = FixedPolicy([], generated_tokens=40, prompt_tokens=100)
    completed = await search(repl, ARITHMETIC, policy, max_expansions=1)
    accounting = completed.result.accounting
    assert (accounting.prompt_tokens, accounting.generated_tokens) == (100, 40)


async def test_candidates_left_unexecuted_by_a_proof_are_charged(repl: LeanRepl) -> None:
    completed = await search(repl, TRIVIAL, FixedPolicy(["norm_num", "simp", "decide"], generated_tokens=30))
    assert completed.result.solved_at is not None and completed.result.solved_at.generated_tokens == 30


async def test_composite_charges_each_expander(repl: LeanRepl) -> None:
    first = FixedPolicy(["intros"], generated_tokens=10, prompt_tokens=5)
    second = FixedPolicy(["skip"], generated_tokens=20, prompt_tokens=7)
    completed = await search(repl, NEEDS_INTRO, CompositeExpander([first, second]), max_expansions=1)
    accounting = completed.result.accounting
    assert (accounting.prompt_tokens, accounting.generated_tokens) == (12, 30)


async def test_expansion_records_what_its_batches_cost(repl: LeanRepl) -> None:
    expander = CompositeExpander([FixedPolicy(["intros"], generated_tokens=10), FixedPolicy([], generated_tokens=20)])
    completed = await search(repl, NEEDS_INTRO, expander, max_expansions=1)
    assert completed.tree is not None and completed.tree.root.expansion_generated_tokens == 30


async def test_token_budget_counts_requests_without_candidates(repl: LeanRepl) -> None:
    expander = CompositeExpander([FixedPolicy([ALWAYS_PROGRESSES], generated_tokens=0), FixedPolicy([])])
    completed = await search(repl, ARITHMETIC, expander, max_expansions=100, max_generated_tokens=25)
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


async def test_overlapped_request_is_charged_when_automation_closes_the_goal(repl: LeanRepl) -> None:
    policy = FixedPolicy(["norm_num"], generated_tokens=30, prompt_tokens=7)
    completed = await search(repl, TRIVIAL, CompositeExpander([automation("decide"), policy], overlap=True))
    accounting = completed.result.accounting
    assert (completed.result.proof_steps, accounting.prompt_tokens, accounting.generated_tokens) == (("decide",), 7, 30)


async def test_solve_pays_for_the_request_overlapping_its_proving_sweep(repl: LeanRepl) -> None:
    policy = FixedPolicy(["norm_num"], generated_tokens=30)
    completed = await search(repl, TRIVIAL, CompositeExpander([automation("decide"), policy], overlap=True))
    assert completed.result.solved_at is not None and completed.result.solved_at.generated_tokens == 30


async def test_overlap_keeps_automation_candidates_first(repl: LeanRepl) -> None:
    expander = CompositeExpander([automation("rfl"), FixedPolicy(["intros"])], overlap=True)
    completed = await search(repl, NEEDS_INTRO, expander, max_expansions=1)
    assert completed.tree is not None
    assert [edge.source for edge in completed.tree.edges] == [StepSource.AUTOMATION, StepSource.POLICY]


def node_priorities(completed: CompletedSearch) -> list[tuple[int, float | None, float | None]]:
    assert completed.tree is not None
    return [(node.node_id, node.priority, node.value_estimate) for node in completed.tree.nodes]


async def test_early_child_scores_equal_the_scores_after_the_expansion(repl: LeanRepl) -> None:
    expander = automation(ALWAYS_PROGRESSES, "have : (2 : ℕ) = 2 := rfl")
    late = await search(repl, ARITHMETIC, expander, ValueLikePriority(), max_expansions=3)
    early = await search(repl, ARITHMETIC, expander, ValueLikePriority(), max_expansions=3, score_children_early=True)
    assert node_priorities(early) == node_priorities(late)


async def test_early_child_scoring_charges_the_same_value_tokens(repl: LeanRepl) -> None:
    expander = automation(ALWAYS_PROGRESSES, "have : (2 : ℕ) = 2 := rfl")
    late = await search(repl, ARITHMETIC, expander, ValueLikePriority(), max_expansions=3)
    early = await search(repl, ARITHMETIC, expander, ValueLikePriority(), max_expansions=3, score_children_early=True)
    assert early.result.accounting.value_prompt_tokens == late.result.accounting.value_prompt_tokens


async def test_children_scored_before_a_proof_are_charged(repl: LeanRepl) -> None:
    policy = FixedPolicy(["intros", "intro n\nsimp"])
    completed = await search(
        repl, NEEDS_INTRO, policy, ValueLikePriority(), max_expansions=1, score_children_early=True
    )
    assert completed.result.proved and completed.result.accounting.value_prompt_tokens == 200


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


class GeneratingPolicy:
    """One request whose samples explain, then give a block; unparsed samples are passed through."""

    def __init__(self, blocks: Sequence[str], unparsed: Sequence[str] = ()) -> None:
        self.blocks = tuple(blocks)
        self.unparsed = tuple(unparsed)

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        candidates = []
        for block in self.blocks:
            text = f"An explanation.\n\n```lean\n{block}\n```"
            positions = normalized_block(block, text.index(block)).positions
            generated = GeneratedText(text, ended_turn=True, block_positions=positions)
            candidates.append(Candidate(block, StepSource.POLICY, log_probability=-1.0, completions=(generated,)))
        unparsed = tuple(UnparsedSample(text, ended_turn=False, reason="truncated") for text in self.unparsed)
        yield CandidateBatch(tuple(candidates), prompt=PROMPT, unparsed=unparsed)


PROMPT = "<prompt>"
NESTED_BLOCK = "have h₂ : a * a = b * b := by\n  subst h\n  exact undefined_lemma"


async def test_nested_proof_failure_keeps_the_flattened_prefix_as_a_child(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, GeneratingPolicy([NESTED_BLOCK]), max_expansions=1)
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.outcome, edge.applied_tactics, edge.total_tactics, edge.flattened) == (EdgeOutcome.CHILD, 2, 3, True)


async def test_unflattened_nested_proof_failure_is_a_failed_edge(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, GeneratingPolicy([NESTED_BLOCK]), max_expansions=1, flatten_blocks=False)
    assert completed.tree is not None and completed.tree.edges[0].outcome == EdgeOutcome.FAILED


async def test_completion_spans_cover_the_executed_tactics(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, GeneratingPolicy([NESTED_BLOCK]), max_expansions=1)
    assert completed.tree is not None
    (expansion,) = completed.tree.expansion_texts
    (completion,) = expansion.completions
    spans = [completion.text[span.start : span.end] for span in completion.tactic_spans]
    assert spans == ["have h₂ : a * a = b * b := by", "subst h", "exact undefined_lemma"]


async def test_unknown_identifier_is_rejected_before_lean(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, GeneratingPolicy(["subst h\nexact mystery_lemma"]), max_expansions=1)
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.applied_tactics, edge.failure and edge.failure.kind) == (1, FailureKind.UNKNOWN_IDENTIFIER)


async def test_unparsed_samples_are_failed_edges_with_their_texts(repl: LeanRepl) -> None:
    policy = GeneratingPolicy(["subst h"], unparsed=["An explanation that repeats, repeats, repeats"])
    completed = await search(repl, ARITHMETIC, policy, max_expansions=1)
    assert completed.tree is not None
    unparsed = completed.tree.edges[0]
    (expansion,) = completed.tree.expansion_texts
    assert (unparsed.failure and unparsed.failure.kind, expansion.completions[0].edge_id) == (
        FailureKind.UNPARSED,
        unparsed.edge_id,
    )


async def test_expansion_texts_keep_the_prompt(repl: LeanRepl) -> None:
    completed = await search(repl, ARITHMETIC, GeneratingPolicy(["subst h"]), max_expansions=1)
    assert completed.tree is not None and [texts.prompt for texts in completed.tree.expansion_texts] == [PROMPT]


async def test_new_states_get_accessible_hypothesis_names(repl: LeanRepl) -> None:
    completed = await search(repl, NEEDS_INTRO, FixedPolicy(["intros"]), max_expansions=1)
    assert completed.tree is not None and completed.tree.nodes[1].goals == ("n_1 : ℕ\n⊢ n_1 + 0 = n_1",)


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
