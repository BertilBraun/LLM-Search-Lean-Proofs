from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from lean_search.corpora.records import DataSplit, TracedStep
from lean_search.lean import ProofState
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.evaluation import read_search_progress
from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig
from lean_search.rl.single_step import (
    GenerationWatch,
    StatesProgress,
    reference_labels,
    sample_success,
    single_step_groups,
    state_problem,
)
from lean_search.search import (
    Accounting,
    Candidate,
    CandidateBatch,
    CandidateBatches,
    EdgeOutcome,
    Failure,
    FailureKind,
    Node,
    SearchContext,
    SearchResult,
    SearchTree,
    StepSource,
    StopReason,
    TreeRecord,
    tree_record,
)
from lean_search.search.graph_labels import GoalKey, goal_key
from lean_search.search.tactic_labels import TacticLabel

STATEMENT = "theorem t (a b : ℕ) (h₀ : a = b) : a + 0 = b := by"
ROOT = "a b : ℕ\nh₀ : a = b\n⊢ a + 0 = b"
REFERENCE_NEXT = "a b : ℕ\nh₀ : a = b\n⊢ a = b"
REFERENCE_STEPS = {goal_key((REFERENCE_NEXT,)): 1, (): 0}
REFERENCE_KEYS = frozenset(REFERENCE_STEPS)
REWARDS = RewardConfig()


def state(*goals: str) -> ProofState:
    return ProofState("", STATEMENT, ("intro",), goals, 0, 0)


def single_step_tree(closing: bool) -> TreeRecord:
    """The root's samples: one to the reference proof's next state, one to an unknown state, one failing, and
    optionally one closing the goal."""
    tree = SearchTree("t", state(ROOT), 0.0)
    root = tree.root
    root.expansion_index = 0
    children = [("simp only [Nat.add_zero]", REFERENCE_NEXT), ("rw [h₀]", "a b : ℕ\nh₀ : a = b\n⊢ b + 0 = b")]
    for text, goals in children:
        edge = tree.add_edge(
            root,
            text=text,
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.CHILD,
            target_id=tree.next_node_id(),
            applied_tactics=1,
            total_tactics=1,
            tactic_goals=((goals,),),
        )
        tree.add_child(root, edge.edge_id, text, StepSource.POLICY, -1.0, state(goals), 0.0, 0.0)
    tree.add_edge(
        root,
        text="linarith",
        source=StepSource.POLICY,
        log_probability=-1.0,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.FAILED,
        total_tactics=1,
        failure=Failure(FailureKind.ERROR, "linarith failed"),
    )
    proved = None
    if closing:
        edge = tree.add_edge(
            root,
            text="simpa using h₀",
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.CHILD,
            target_id=tree.next_node_id(),
            applied_tactics=1,
            total_tactics=1,
            tactic_goals=((),),
        )
        proved = tree.add_child(root, edge.edge_id, "simpa using h₀", StepSource.POLICY, -1.0, state(), 0.0, 0.0)
        tree.mark_proof_path(proved)
    tree.settle_statuses()
    result = SearchResult("t", closing, StopReason.EXPANSION_BUDGET, None, (), (), Accounting(expansions=1), None, 0, 1)
    return tree_record(tree, STATEMENT, result)


def labels_of(record: TreeRecord) -> list[TacticLabel]:
    _, tactics = reference_labels(record, REFERENCE_STEPS, REWARDS.off_graph_min_expanded_nodes)
    return [tactics[edge_id][0].label for edge_id in sorted(tactics)]


def test_a_sample_reaching_the_reference_proof_is_on_the_proof_graph() -> None:
    assert labels_of(single_step_tree(closing=False))[0] == TacticLabel.PROOF_GRAPH


def test_a_sample_reaching_another_new_state_is_unknown() -> None:
    assert labels_of(single_step_tree(closing=False))[1] == TacticLabel.UNKNOWN


def root_groups(record: TreeRecord, reference_steps: Mapping[GoalKey, int]) -> list[PolicyGroup]:
    labels, tactics = reference_labels(record, reference_steps, REWARDS.off_graph_min_expanded_nodes)
    return list(single_step_groups(record, labels, tactics, REWARDS).groups)


def test_a_state_no_sample_closes_still_forms_a_group() -> None:
    assert len(root_groups(single_step_tree(closing=False), REFERENCE_STEPS)) == 1


def test_a_state_no_sample_reaches_the_proof_graph_forms_no_group() -> None:
    assert root_groups(single_step_tree(closing=False), {}) == []


def test_reaching_the_reference_proof_earns_one_step_of_progress() -> None:
    (root,) = root_groups(single_step_tree(closing=False), REFERENCE_STEPS)
    reward = root.samples[0].tactics[0].parts
    assert reward is not None and reward.total == pytest.approx(0.85 + 0.2)


def test_a_found_proof_shorter_than_the_reference_sets_the_state_s_remaining_steps() -> None:
    (root,) = root_groups(single_step_tree(closing=True), REFERENCE_STEPS)
    reward = root.samples[0].tactics[0].parts
    assert reward is not None and reward.total == pytest.approx(0.85)


def test_success_counts_closing_and_reference_samples() -> None:
    success = sample_success(single_step_tree(closing=True), REFERENCE_KEYS)
    assert (success.successes, success.samples) == (2, 4)


def test_a_traced_state_starts_after_its_earlier_steps() -> None:
    step = TracedStep(
        "s",
        "s/1",
        "s",
        DataSplit.VALIDATION,
        "",
        STATEMENT,
        1,
        3,
        2,
        (ROOT,),
        "simp",
        (REFERENCE_NEXT,),
        ("intro",),
        0,
        0,
    )
    problem = state_problem(ReasoningState("s/1#1", step, ((),), False))
    assert problem.start.tactics == ("intro",)


def test_a_traced_state_knows_the_later_states_of_its_proof() -> None:
    step = TracedStep(
        "s",
        "s/1",
        "s",
        DataSplit.VALIDATION,
        "",
        STATEMENT,
        1,
        3,
        2,
        (ROOT,),
        "simp",
        (REFERENCE_NEXT,),
        ("intro",),
        0,
        0,
    )
    problem = state_problem(ReasoningState("s/1#1", step, ((),), False))
    assert problem.reference_steps == REFERENCE_STEPS


class Batches:
    def __init__(self, *batches: CandidateBatch) -> None:
        self.batches = batches

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        for batch in self.batches:
            yield batch


def policy_batch(feedback: bool = False) -> CandidateBatch:
    candidate = Candidate("simp", StepSource.POLICY, -1.0, feedback=feedback)
    return CandidateBatch((candidate,), prompt="prompt", feedback=feedback)


AUTOMATION_BATCH = CandidateBatch((Candidate("omega", StepSource.AUTOMATION),))


async def generated_after(batches: Batches, feedback: bool) -> list[int]:
    """For each batch the expander yields, the generation reports made by then."""
    reports: list[int] = []
    seen: list[int] = []
    watch = GenerationWatch(batches, feedback, lambda: reports.append(1))
    async for _ in watch.expand(cast(Node, None), cast(SearchContext, None)):
        seen.append(len(reports))
    return seen


async def test_a_state_is_generated_with_its_first_rounds_batch() -> None:
    assert await generated_after(Batches(policy_batch()), feedback=False) == [1]


async def test_automation_batches_generate_nothing() -> None:
    assert await generated_after(Batches(AUTOMATION_BATCH, policy_batch()), feedback=False) == [0, 1]


async def test_with_the_feedback_round_on_a_state_is_generated_with_its_feedback_batch() -> None:
    batches = Batches(policy_batch(), policy_batch(feedback=True))
    assert await generated_after(batches, feedback=True) == [0, 1]


def test_the_progress_reports_generation_unfinished_while_a_state_awaits_its_samples(tmp_path: Path) -> None:
    progress = StatesProgress(tmp_path / "progress.json", ["a", "b"], 4)
    progress.sampled("a")
    report = read_search_progress(tmp_path / "progress.json")
    assert report is not None and not report.generation_finished


def test_the_progress_reports_generation_finished_once_every_state_sampled(tmp_path: Path) -> None:
    progress = StatesProgress(tmp_path / "progress.json", ["a", "b"], 4)
    progress.sampled("a")
    progress.finished("b")
    report = read_search_progress(tmp_path / "progress.json")
    assert report is not None and report.generation_finished


def test_the_progress_counts_the_states_left_in_flight(tmp_path: Path) -> None:
    progress = StatesProgress(tmp_path / "progress.json", ["a", "b", "c"], 4)
    progress.finished("a")
    assert progress.progress.searches_in_flight == 2
