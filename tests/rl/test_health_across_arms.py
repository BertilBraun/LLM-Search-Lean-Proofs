"""Health measurements that mean the same in every arm: from the phase's trees, whatever trains the policy."""

import dataclasses
from collections.abc import Sequence

import pytest
import torch
from loop_fakes import solved_tree, zero

from lean_search.data import Problem, Split
from lean_search.monitoring.families import BudgetPhase, HealthCheck, HealthMeasurements, HealthThresholds, PhaseHealth
from lean_search.rl.advantages import CreditMode
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.health_checks import HeldOutRates, measurements, phase_health
from lean_search.rl.loop_config import HealthConfig
from lean_search.rl.policy_data import UpdateSize
from lean_search.rl.policy_trainer import GrpoStepRecord, parameter_snapshot, update_size
from lean_search.rl.training_phase import PhaseOutcome, PolicyOutcome, policy_update_text
from lean_search.rl.tree_store import TreeEntry
from lean_search.rl.tree_summary import (
    BlockHabits,
    TreeSummary,
    ends_in_unproved_claim_after_proof_graph,
    explanation_token_count,
    explanation_token_habits,
    fails_after_proof_graph,
    tree_summary,
)
from lean_search.search import Accounting, SearchResult, StopReason, TreeRecord, tree_record
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome
from lean_search.search.texts import ExpansionTexts, SampledCompletion, SampledTokens

PROOF_GRAPH, FAILING, MASKED = TacticLabel.PROOF_GRAPH, TacticLabel.FAILING, TacticLabel.MASKED
OFF_GRAPH, UNPROVED_CLAIM = TacticLabel.OFF_GRAPH, TacticLabel.UNPROVED_CLAIM
VOCABULARY = ("Idea", ".\n\n", "```", "lean\n", "simp", "\n", "<|im_end|>", "x", "é")


class VocabularyDecoder:
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(VOCABULARY[token] for token in token_ids)


def completion(pieces: Sequence[str], text: str | None = None) -> SampledCompletion:
    tokens = SampledTokens(tuple(VOCABULARY.index(piece) for piece in pieces))
    return SampledCompletion(0, "".join(pieces) if text is None else text, (), tokens=tokens)


@pytest.mark.parametrize(
    ("pieces", "text", "count"),
    [
        (("Idea", ".\n\n", "```", "lean\n", "simp", "\n", "```"), None, 2),
        (("```", "lean\n", "simp", "\n", "```"), None, 0),
        (("Idea", ".\n\n", "x", "é"), None, 4),
        (("Idea", "x", "<|im_end|>"), "Ideax", 2),
    ],
    ids=["before the fence", "no explanation", "no fence", "an end of turn the text omits"],
)
def test_the_explanation_tokens_run_up_to_the_opening_fence(
    pieces: tuple[str, ...], text: str | None, count: int
) -> None:
    assert explanation_token_count(VocabularyDecoder(), completion(pieces, text)) == count


def test_without_a_decoder_no_explanation_tokens_are_counted() -> None:
    assert explanation_token_habits(None, [completion(("Idea", "```"))]).explanation_token_samples == 0


def test_samples_recorded_without_tokens_are_left_out_of_the_explanation_tokens() -> None:
    habits = explanation_token_habits(VocabularyDecoder(), [completion(("Idea", "```")), SampledCompletion(0, "x", ())])
    assert habits.explanation_token_samples == 1


def outcomes(*labels: TacticLabel) -> tuple[TacticOutcome, ...]:
    return tuple(TacticOutcome(label) for label in labels)


@pytest.mark.parametrize(
    ("labels", "failing"),
    [
        ((PROOF_GRAPH, FAILING), True),
        ((PROOF_GRAPH, OFF_GRAPH, FAILING, MASKED), True),
        ((FAILING,), False),
        ((OFF_GRAPH, FAILING), False),
        ((PROOF_GRAPH,), False),
    ],
    ids=["right after", "after an off-graph step", "first tactic fails", "never on the graph", "no failure"],
)
def test_a_failing_tactic_after_the_proof_graph(labels: tuple[TacticLabel, ...], failing: bool) -> None:
    assert fails_after_proof_graph(outcomes(*labels)) == failing


@pytest.mark.parametrize(
    ("labels", "unproved"),
    [
        ((PROOF_GRAPH, UNPROVED_CLAIM), True),
        ((PROOF_GRAPH, UNPROVED_CLAIM, FAILING, MASKED), True),
        ((UNPROVED_CLAIM,), False),
        ((PROOF_GRAPH, UNPROVED_CLAIM, OFF_GRAPH), False),
        ((PROOF_GRAPH, PROOF_GRAPH), False),
    ],
    ids=["ends in the claim", "the claim before a failure", "never on the graph", "goes on after it", "no claim"],
)
def test_a_block_ending_in_an_unproved_claim_after_the_proof_graph(
    labels: tuple[TacticLabel, ...], unproved: bool
) -> None:
    assert ends_in_unproved_claim_after_proof_graph(outcomes(*labels)) == unproved


HABITS = BlockHabits(
    block_samples=200,
    proof_graph_samples=20,
    failing_after_proof_graph=4,
    unproved_claim_after_proof_graph=2,
    explanation_token_samples=4,
    explanation_tokens=60,
)


def tree_entry(habits: BlockHabits = HABITS, below_band: bool = False) -> TreeEntry:
    summary = TreeSummary(habits=habits, below_band=below_band)
    return TreeEntry(0, "p", 1, "f", False, 0, 1, 0, None, 0.0, 0.0, summary)


def grpo_outcome(mean_explanation_tokens: float) -> PhaseOutcome:
    policy = zero(PolicyOutcome)
    data = dataclasses.replace(policy.data, sequences=5, mean_explanation_tokens=mean_explanation_tokens)
    result = dataclasses.replace(policy.result, final_kl_to_reference=0.01, final_clip_fraction=0.2)
    return PhaseOutcome(trees=1, groups=1, policy=dataclasses.replace(policy, data=data, result=result), value=None)


EXPERT_ITERATION_PHASE = PhaseOutcome(trees=1, groups=0, policy=None, value=None)


@pytest.mark.parametrize(
    "outcome", [EXPERT_ITERATION_PHASE, grpo_outcome(999.0), None], ids=["no GRPO update", "GRPO", "no outcome"]
)
def test_the_mean_explanation_tokens_come_from_the_trees_whatever_trained(outcome: PhaseOutcome | None) -> None:
    assert measurements(outcome, [tree_entry(), tree_entry()], None).mean_explanation_tokens == 15.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proof_graph_sample_share", 0.02),
        ("failing_after_proof_graph_share", 0.2),
        ("unproved_claim_after_proof_graph_share", 0.1),
        ("below_band_failing_after_proof_graph_share", 0.2),
        ("below_band_unproved_claim_after_proof_graph_share", 0.1),
    ],
)
def test_the_tails_are_shares_of_the_samples_reaching_the_proof_graph(field: str, value: float) -> None:
    entries = [tree_entry(below_band=True), tree_entry(BlockHabits(block_samples=800))]
    assert getattr(measurements(EXPERT_ITERATION_PHASE, entries, None), field) == pytest.approx(value)


def test_statements_from_below_the_band_without_a_sample_on_the_graph_have_no_tails() -> None:
    entries = [tree_entry(), tree_entry(BlockHabits(block_samples=10), below_band=True)]
    assert measurements(EXPERT_ITERATION_PHASE, entries, None).below_band_failing_after_proof_graph_share is None


@pytest.mark.parametrize("field", ["kl_to_starting_policy", "clip_fraction"])
def test_a_phase_without_a_grpo_update_measures_no_grpo_statistics(field: str) -> None:
    assert getattr(measurements(EXPERT_ITERATION_PHASE, [tree_entry()], None), field) is None


CONFIG = dataclasses.replace(HealthConfig(), reference_phases=1, rollback_window_phases=0)
QUIET_BUDGET = BudgetPhase(100, 50, 200, 32, 1, 0.02, 0.02, 3, 0.1)
# grpo_loop_v1's phase 1 (review AG): of the samples reaching the proof graph, 16.2% then fail, 0.85% end in an
# unproved claim.
REFERENCE = (0.162, 0.0085)


def record(phase: int, failing: float, unproved: float, reached: int = 5000) -> PhaseHealth:
    measured = HealthMeasurements(
        proof_graph_samples=reached,
        failing_after_proof_graph_share=failing,
        unproved_claim_after_proof_graph_share=unproved,
    )
    return PhaseHealth(phase, phase, measured, HealthThresholds(0.5, 0.1))


def health_of(measured: HealthMeasurements, history: Sequence[PhaseHealth] = ()) -> PhaseHealth:
    return phase_health(3, 3, measured, list(history), HeldOutRates(0.8, 0.4), QUIET_BUDGET, CONFIG)


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_failing_after_proof_graph_share", 0.262), ("max_unproved_claim_after_proof_graph_share", 0.0385)],
    ids=["failing: the reference + 10 points", "unproved: the reference + 3 points"],
)
def test_the_tail_thresholds_rise_from_the_first_phase_by_at_least_their_floor(field: str, value: float) -> None:
    thresholds = health_of(HealthMeasurements(), [record(1, *REFERENCE), record(2, 0.5, 0.5)]).thresholds
    assert getattr(thresholds, field) == pytest.approx(value)


def test_a_common_tail_rises_by_its_factor_above_the_floor() -> None:
    thresholds = health_of(HealthMeasurements(), [record(1, 0.4, 0.1)]).thresholds
    assert thresholds.max_failing_after_proof_graph_share == pytest.approx(0.6)


@pytest.mark.parametrize(
    ("failing", "unproved", "reached", "checks"),
    [
        (0.25, 0.03, 5000, []),
        (0.27, 0.03, 5000, [HealthCheck.FAILING_AFTER_PROOF_GRAPH]),
        (0.25, 0.04, 5000, [HealthCheck.UNPROVED_CLAIM_AFTER_PROOF_GRAPH]),
        (0.9, 0.9, 999, []),
    ],
    ids=["within the floors", "failing tails rising", "unproved claims rising", "too few samples on the graph"],
)
def test_tails_after_the_proof_graph_alert_against_the_first_phase(
    failing: float, unproved: float, reached: int, checks: list[HealthCheck]
) -> None:
    health = health_of(record(3, failing, unproved, reached).measured, [record(1, *REFERENCE)])
    assert [alert.check for alert in health.alerts] == checks


def test_a_rare_unproved_claim_reference_does_not_alert_on_noise() -> None:
    health = health_of(record(3, 0.1, 0.003).measured, [record(1, 0.1, 0.0008)])
    assert health.alerts == ()


def test_tails_after_the_proof_graph_never_stop_the_loop() -> None:
    health = health_of(record(3, 0.9, 0.9).measured, [record(1, *REFERENCE)])
    assert not health.hard_stop


def test_a_phase_without_grpo_statistics_still_stops_at_a_held_out_collapse() -> None:
    measured = measurements(EXPERT_ITERATION_PHASE, [tree_entry()], HeldOutRates(0.5, 0.3))
    assert health_of(measured, [record(1, *REFERENCE)]).hard_stop


def step(policy_loss: float, kl_penalty: float, replay_nll: float, gradient_norm: float) -> GrpoStepRecord:
    return dataclasses.replace(
        zero(GrpoStepRecord),
        policy_loss=policy_loss,
        kl_penalty=kl_penalty,
        replay_nll=replay_nll,
        gradient_norm=gradient_norm,
    )


def moved_update() -> UpdateSize | None:
    """Parameters (3, 4) moved to (0, 0) over two steps."""
    parameters = [torch.nn.Parameter(torch.tensor([3.0, 4.0]))]
    start = parameter_snapshot(parameters)
    with torch.no_grad():
        parameters[0].zero_()
    records = [step(-0.2, 0.05, 0.5, 1.0), step(0.1, 0.03, 0.3, 3.0)]
    return update_size(records, 0.1, parameters, start)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parameter_change_norm", 5.0),
        ("relative_parameter_change", 1.0),
        ("mean_gradient_norm", 2.0),
        ("mean_absolute_policy_loss", 0.15),
        ("mean_kl_penalty", 0.04),
        ("mean_replay_loss", 0.04),
    ],
)
def test_the_update_size_of_a_phase(field: str, value: float) -> None:
    assert getattr(moved_update(), field) == pytest.approx(value)


def test_an_update_without_steps_has_no_size() -> None:
    assert update_size([], 0.1, [], []) is None


def test_the_update_line_says_when_the_size_is_not_measured() -> None:
    assert "its size not measured" in policy_update_text(1, zero(PolicyOutcome))


PROBLEM = Problem("t", Split.VALID, "", "theorem t : True := by", "", "")


def tree_with_samples(*rounds: tuple[bool, SampledCompletion]) -> TreeRecord:
    """The fake solved tree with one expansion text per (feedback, sample)."""
    result = SearchResult(PROBLEM.name, True, StopReason.PROVED, None, (), (), Accounting(expansions=1), None, 0, 1)
    tree = tree_record(solved_tree(PROBLEM), PROBLEM.formal_statement, result)
    texts = tuple(
        ExpansionTexts(PROBLEM.name, 0, "prompt", (sample,), feedback=feedback) for feedback, sample in rounds
    )
    return dataclasses.replace(tree, expansions=texts)


def test_the_tree_summary_counts_the_first_rounds_explanation_tokens() -> None:
    fenced = completion(("Idea", ".\n\n", "```", "lean\n", "simp", "\n", "```"))
    tree = tree_with_samples((False, fenced), (True, completion(("Idea", "x", "```"))))
    summary = tree_summary(tree, RewardConfig(), CreditMode.PER_TACTIC, 32, decoder=VocabularyDecoder())
    assert (summary.habits.explanation_token_samples, summary.habits.explanation_tokens) == (1, 2)


class FailingDecoder:
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        raise RuntimeError("the tokenizer failed")


def failed_habits_summary() -> TreeSummary:
    tree = tree_with_samples((False, completion(("Idea", "```"))))
    return tree_summary(tree, RewardConfig(), CreditMode.PER_TACTIC, 32, decoder=FailingDecoder())


def test_a_failed_habit_measurement_is_recorded_in_the_summary() -> None:
    assert failed_habits_summary().habits_error == "RuntimeError: the tokenizer failed"


def test_a_failed_habit_measurement_keeps_the_trees_trainable_groups() -> None:
    assert failed_habits_summary().trainable_groups == 1
