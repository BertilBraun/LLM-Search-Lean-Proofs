import dataclasses
from pathlib import Path

import pytest
from loop_fakes import solved_tree, zero

from lean_search.data import Problem, Split
from lean_search.monitoring.families import (
    BudgetPhase,
    HealthCheck,
    HealthMeasurements,
    HealthSeverity,
    HealthThresholds,
    PhaseHealth,
)
from lean_search.rl.advantages import CreditMode
from lean_search.rl.budget_signals import budget_phase_record, is_late_solve
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.health_checks import (
    HeldOutRates,
    append_health,
    clear_health_stop,
    health_alerts,
    health_thresholds,
    healthy_versions,
    held_out_rates,
    measurements,
    phase_health,
    read_health_history,
    reference_measurements,
    write_health_stop,
)
from lean_search.rl.loop_config import HealthConfig
from lean_search.rl.training_phase import PhaseOutcome, PolicyOutcome
from lean_search.rl.tree_store import TreeEntry
from lean_search.rl.tree_summary import TreeSummary, tree_summary
from lean_search.search import Accounting, SearchResult, StopReason, TreeRecord, tree_record
from lean_search.search.texts import (
    CharacterSpan,
    ExpansionTexts,
    InsertedSpan,
    SampledCompletion,
    SampledTokens,
    TokenSpan,
)
from lean_search.search.tree import Failure, FailureKind

PROBLEM = Problem("test.t0", Split.VALID, "", "theorem t0 : True := by", "", "")
LOOP = "This line repeats itself again and again.\n"
CONFIG = HealthConfig()


def record(proved: bool = True, solved_at: int | None = 3) -> TreeRecord:
    first_proof = None if solved_at is None else Accounting(expansions=solved_at)
    result = SearchResult(
        PROBLEM.name, proved, StopReason.PROVED, None, (), (), Accounting(expansions=5), first_proof, 0, 1
    )
    return tree_record(solved_tree(PROBLEM), PROBLEM.formal_statement, result)


def completion(text: str, cut_off: bool = False) -> SampledCompletion:
    inserted = (InsertedSpan(CharacterSpan(len(text), len(text)), TokenSpan(0, 0)),) if cut_off else ()
    return SampledCompletion(0, text, (), tokens=SampledTokens(inserted=inserted))


def with_completions(tree: TreeRecord, *completions: SampledCompletion) -> TreeRecord:
    return dataclasses.replace(tree, expansions=(ExpansionTexts(tree.problem_name, 0, "prompt", completions),))


def summary_of(tree: TreeRecord) -> TreeSummary:
    return tree_summary(tree, RewardConfig(), CreditMode.PER_TACTIC, 32)


def test_a_solved_tree_counts_its_trainable_group() -> None:
    assert summary_of(record()).trainable_groups == 1


def test_an_unsolved_tree_has_no_trainable_groups() -> None:
    assert summary_of(record(proved=False, solved_at=None)).trainable_groups == 0


def test_a_solved_tree_records_its_shortest_proof() -> None:
    assert summary_of(record()).proof_steps == 1


def test_a_solved_tree_records_its_first_proofs_expansion() -> None:
    assert summary_of(record(solved_at=7)).solved_at_expansion == 7


def test_each_block_of_an_expansion_counts_once() -> None:
    assert (summary_of(record()).policy_expansions, summary_of(record()).distinct_blocks) == (1, 2)


def test_the_blocks_lean_judged_leave_out_infrastructure_failures() -> None:
    tree = record()
    failed = dataclasses.replace(tree.edges[0], failure=Failure(FailureKind.REPL_FAILURE, "crashed"))
    assert summary_of(dataclasses.replace(tree, edges=(failed, tree.edges[1]))).judged_blocks == 1


def test_a_block_that_ran_completely_is_valid() -> None:
    assert (summary_of(record()).judged_blocks, summary_of(record()).valid_blocks) == (2, 1)


def test_policy_samples_count_the_merged_samples() -> None:
    tree = record()
    merged = dataclasses.replace(tree, edges=(tree.edges[0], dataclasses.replace(tree.edges[1], sample_count=3)))
    assert summary_of(merged).policy_samples == 4


def test_identical_texts_count_once() -> None:
    tree = with_completions(record(), completion("a"), completion("a"), completion("b"))
    assert summary_of(tree).distinct_texts == 2


def test_samples_cut_off_at_the_token_cap_are_counted() -> None:
    tree = with_completions(record(), completion("x", cut_off=True), completion("y"))
    assert summary_of(tree).cut_off_samples == 1


def test_repetition_loops_are_counted_among_the_cut_off_samples() -> None:
    tree = with_completions(record(), completion(LOOP * 3, cut_off=True), completion(LOOP * 3))
    assert summary_of(tree).repetition_loops == 1


def with_feedback_round(tree: TreeRecord) -> TreeRecord:
    """A feedback round at the root: 4 samples of one failed block, cut off at the token cap."""
    edge = dataclasses.replace(tree.edges[0], edge_id=len(tree.edges), feedback=True, sample_count=4)
    texts = ExpansionTexts(tree.problem_name, 0, "feedback prompt", (completion("x", cut_off=True),), feedback=True)
    return dataclasses.replace(tree, edges=(*tree.edges, edge), expansions=(*tree.expansions, texts))


@pytest.mark.parametrize(
    "field",
    [
        "policy_expansions",
        "policy_samples",
        "distinct_blocks",
        "distinct_texts",
        "cut_off_samples",
        "judged_blocks",
        "valid_blocks",
    ],
)
def test_the_feedback_rounds_samples_stay_out_of_the_health_fields(field: str) -> None:
    tree = with_completions(record(), completion("a"))
    assert getattr(summary_of(with_feedback_round(tree)), field) == getattr(summary_of(tree), field)


def test_the_feedback_rounds_samples_are_counted_apart() -> None:
    summary = summary_of(with_feedback_round(record()))
    assert (summary.feedback_expansions, summary.feedback_samples) == (1, 4)


def test_a_solved_tree_records_its_tokens_up_to_the_first_proof() -> None:
    tree = record()
    result = dataclasses.replace(tree.result, solved_at=Accounting(expansions=3, generated_tokens=700))
    assert summary_of(dataclasses.replace(tree, result=result)).generated_tokens_to_first_proof == 700


def test_an_unsolved_tree_spends_all_its_tokens_before_a_first_proof() -> None:
    tree = record(proved=False, solved_at=None)
    result = dataclasses.replace(tree.result, accounting=Accounting(expansions=5, generated_tokens=900))
    assert summary_of(dataclasses.replace(tree, result=result)).generated_tokens_to_first_proof == 900


def entry(
    phase: int = 1,
    solved_at: int | None = None,
    budget: int = 32,
    proof_steps: int | None = None,
    groups: int = 0,
    difficulty: float | None = None,
) -> TreeEntry:
    proved = solved_at is not None
    summary = TreeSummary(budget, solved_at, proof_steps, groups)
    return TreeEntry(0, "p", phase, "f", proved, int(proved), 1, 0, difficulty, 0.0, 0.0, summary)


def budget_record(entries: list[TreeEntry], phase: int = 1) -> BudgetPhase:
    return budget_phase_record(entries, phase, CONFIG.late_solve_phases, CONFIG.max_late_solve_share)


@pytest.mark.parametrize(
    ("solved_at", "budget", "late"), [(25, 32, True), (24, 32, False), (49, 64, True), (48, 64, False)]
)
def test_a_solve_in_the_last_quarter_of_the_budget_is_late(solved_at: int, budget: int, late: bool) -> None:
    assert is_late_solve(entry(solved_at=solved_at, budget=budget)) == late


def test_the_late_solve_share_counts_solved_trees_only() -> None:
    assert budget_record([entry(solved_at=30), entry(solved_at=2), entry()]).late_solve_share == 0.5


def test_the_late_solve_share_is_pooled_over_the_last_phases() -> None:
    entries = [entry(phase=1, solved_at=30), *(entry(phase=phase, solved_at=2) for phase in (2, 3, 4))]
    assert budget_record(entries, phase=3).recent_late_solve_share == pytest.approx(1 / 3)


@pytest.mark.parametrize(("solved_at", "bucket"), [(1, "1"), (3, "3-4"), (25, "25-32"), (70, "65+")])
def test_expansions_to_solve_are_bucketed(solved_at: int, bucket: str) -> None:
    assert budget_record([entry(solved_at=solved_at)]).expansions_to_solve[bucket] == 1


def test_proof_lengths_are_bucketed() -> None:
    assert budget_record([entry(solved_at=1, proof_steps=5)]).proof_steps["4-5"] == 1


def test_the_difficulty_of_the_solved_statements_leaves_out_the_unsolved() -> None:
    entries = [entry(solved_at=1, difficulty=1.0), entry(solved_at=1, difficulty=3.0), entry(difficulty=5.0)]
    assert budget_record(entries).mean_difficulty_solved == 2.0


def test_the_budget_line_sums_the_trainable_groups() -> None:
    assert budget_record([entry(solved_at=1, groups=3), entry(solved_at=2, groups=4)]).trainable_groups == 7


def summarized(
    policy_expansions: int, samples: int, distinct_blocks: int, cut_off: int, valid_blocks: int = 0
) -> TreeEntry:
    summary = TreeSummary(
        policy_expansions=policy_expansions,
        policy_samples=samples,
        distinct_blocks=distinct_blocks,
        cut_off_samples=cut_off,
        judged_blocks=distinct_blocks,
        valid_blocks=valid_blocks,
    )
    return dataclasses.replace(entry(), summary=summary)


def test_distinct_samples_are_averaged_over_the_phases_expansions() -> None:
    entries = [summarized(2, 16, 10, 0), summarized(2, 16, 6, 0)]
    assert measurements(None, entries, None).distinct_samples_per_expansion == 4.0


def test_the_valid_block_rate_is_per_judged_block() -> None:
    entries = [summarized(2, 16, 10, 0, valid_blocks=8), summarized(2, 16, 10, 0, valid_blocks=6)]
    assert measurements(None, entries, None).valid_block_rate == 0.7


def test_the_cut_off_share_is_per_policy_sample() -> None:
    entries = [summarized(10, 100, 50, 3), summarized(10, 100, 50, 1)]
    assert measurements(None, entries, None).cut_off_share == 0.02


def trained_outcome(sequences: int, **result: float) -> PhaseOutcome:
    policy = zero(PolicyOutcome)
    policy = dataclasses.replace(
        policy,
        data=dataclasses.replace(policy.data, sequences=sequences),
        result=dataclasses.replace(policy.result, final_kl_to_reference=0.01, final_clip_fraction=0.2, **result),
    )
    return PhaseOutcome(trees=1, groups=1, policy=policy, value=None)


@pytest.mark.parametrize(
    ("field", "result", "value"),
    [
        ("kl_to_starting_policy", {"final_first_round_kl_to_reference": 0.003}, 0.003),
        ("clip_fraction", {"final_first_round_clip_fraction": 0.05}, 0.05),
        ("clip_fraction", {}, 0.2),
    ],
    ids=["first-round kl", "first-round clip", "older outcome: every sequence"],
)
def test_the_kl_and_clip_health_fields_count_the_first_rounds_sequences(
    field: str, result: dict[str, float], value: float
) -> None:
    assert getattr(measurements(trained_outcome(5, **result), [], None), field) == value


def test_the_kl_to_the_starting_policy_comes_from_the_trained_policy() -> None:
    assert measurements(trained_outcome(5), [], None).kl_to_starting_policy == 0.01


def test_a_phase_without_trained_sequences_measures_no_kl() -> None:
    assert measurements(trained_outcome(0), [], None).kl_to_starting_policy is None


def test_held_out_rates_are_per_sample() -> None:
    summary = dataclasses.replace(
        zero(EvaluationSummary), kind=EvaluationKind.HELD_OUT_STATES, samples=1000, valid_samples=700, solved=400
    )
    assert held_out_rates(summary) == HeldOutRates(0.7, 0.4)


def health_record(
    phase: int,
    distinct: float = 6.0,
    cut_off: float = 0.002,
    held_out_valid_rate: float | None = None,
    rolled_back_to: int | None = None,
) -> PhaseHealth:
    measured = HealthMeasurements(
        distinct_samples_per_expansion=distinct,
        cut_off_share=cut_off,
        held_out_valid_rate=held_out_valid_rate,
        valid_block_rate=0.8,
    )
    return PhaseHealth(phase, phase, measured, HealthThresholds(0.02, 0.1), rolled_back_to=rolled_back_to)


def reference(*records: PhaseHealth) -> HealthMeasurements | None:
    return reference_measurements(records, CONFIG.reference_phases)


def test_relative_thresholds_wait_for_the_reference_phases() -> None:
    assert health_thresholds(CONFIG, reference(health_record(1)), None).min_distinct_samples_per_expansion is None


def test_the_distinct_samples_threshold_is_a_fraction_of_the_first_phases() -> None:
    thresholds = health_thresholds(CONFIG, reference(health_record(1, 6.0), health_record(2, 8.0)), None)
    assert thresholds.min_distinct_samples_per_expansion == 5.25


def test_the_cut_off_threshold_rises_at_least_by_its_minimum() -> None:
    thresholds = health_thresholds(CONFIG, reference(health_record(1), health_record(2)), None)
    assert thresholds.max_cut_off_share == pytest.approx(0.012)


def test_the_valid_block_threshold_is_a_fraction_of_the_first_phases() -> None:
    thresholds = health_thresholds(CONFIG, reference(health_record(1), health_record(2)), None)
    assert thresholds.min_valid_block_rate == pytest.approx(0.68)


def test_the_stop_threshold_is_a_fraction_of_version_zeros_valid_lean_rate() -> None:
    assert health_thresholds(CONFIG, None, HeldOutRates(0.8, 0.4)).stop_held_out_valid_rate == pytest.approx(0.56)


THRESHOLDS = HealthThresholds(0.02, 0.1, 5.0, 60.0, 240.0, 0.02, 0.72, 0.56, 0.36, 0.68)
HEALTHY = HealthMeasurements(0.001, 0.05, 6.0, 8.0, 120.0, 0.01, 0.005, 0.78, 0.4, 0.8)
QUIET_BUDGET = BudgetPhase(100, 50, 200, 32, 1, 0.02, 0.02, 3, 0.1)


def checks(measured: HealthMeasurements, budget: BudgetPhase = QUIET_BUDGET) -> list[HealthCheck]:
    return [alert.check for alert in health_alerts(measured, THRESHOLDS, budget, CONFIG)]


def test_a_healthy_phase_has_no_alerts() -> None:
    assert checks(HEALTHY) == []


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"kl_to_starting_policy": 0.03}, HealthCheck.KL_TO_STARTING_POLICY),
        ({"clip_fraction": 0.2}, HealthCheck.CLIP_FRACTION),
        ({"distinct_samples_per_expansion": 4.0}, HealthCheck.DISTINCT_SAMPLES),
        ({"mean_explanation_tokens": 40.0}, HealthCheck.EXPLANATION_LENGTH),
        ({"mean_explanation_tokens": 300.0}, HealthCheck.EXPLANATION_LENGTH),
        ({"cut_off_share": 0.05}, HealthCheck.CUT_OFF_SAMPLES),
        ({"held_out_valid_rate": 0.6}, HealthCheck.HELD_OUT_VALID_LEAN),
        ({"held_out_valid_rate": 0.5}, HealthCheck.HELD_OUT_VALID_LEAN),
        ({"held_out_success": 0.3}, HealthCheck.HELD_OUT_SUCCESS),
        ({"valid_block_rate": 0.6}, HealthCheck.VALID_BLOCKS),
    ],
)
def test_a_signal_beyond_its_threshold_alerts(change: dict[str, float], check: HealthCheck) -> None:
    assert checks(dataclasses.replace(HEALTHY, **change)) == [check]


@pytest.mark.parametrize(("valid_rate", "severity"), [(0.6, HealthSeverity.WARNING), (0.5, HealthSeverity.STOP)])
def test_a_held_out_valid_lean_drop_stops_the_loop_only_below_the_stop_threshold(
    valid_rate: float, severity: HealthSeverity
) -> None:
    alerts = health_alerts(
        dataclasses.replace(HEALTHY, held_out_valid_rate=valid_rate), THRESHOLDS, QUIET_BUDGET, CONFIG
    )
    assert [alert.severity for alert in alerts] == [severity]


def test_solves_crowding_into_the_last_quarter_suggest_a_larger_budget() -> None:
    budget = dataclasses.replace(QUIET_BUDGET, recent_late_solve_share=0.15)
    assert checks(HEALTHY, budget) == [HealthCheck.SEARCH_BUDGET]


def test_the_budget_note_waits_for_its_phases() -> None:
    budget = dataclasses.replace(QUIET_BUDGET, recent_late_solve_share=0.15, recent_phases=2)
    assert checks(HEALTHY, budget) == []


def health_of(
    valid_rate: float | None, history: list[PhaseHealth] | None = None, config: HealthConfig = CONFIG
) -> PhaseHealth:
    measured = dataclasses.replace(HEALTHY, held_out_valid_rate=valid_rate)
    return phase_health(5, 4, measured, history or [], HeldOutRates(0.8, 0.4), QUIET_BUDGET, config)


HEALTHY_PHASE_2 = health_record(2, held_out_valid_rate=0.78)


def test_a_passing_held_out_evaluation_becomes_the_last_good_version() -> None:
    assert health_of(0.78).last_good_version == 4


def test_a_held_out_warning_is_not_a_good_version() -> None:
    assert health_of(0.6, [HEALTHY_PHASE_2]).last_good_version == 2


def test_a_first_held_out_collapse_rolls_back_to_the_last_good_version() -> None:
    assert health_of(0.5, [HEALTHY_PHASE_2]).rolled_back_to == 2


def test_a_first_held_out_collapse_keeps_the_loop_running() -> None:
    assert not health_of(0.5).hard_stop


def test_a_collapse_within_the_window_of_a_rollback_stops_the_loop() -> None:
    assert health_of(0.5, [HEALTHY_PHASE_2, health_record(3, rolled_back_to=2)]).hard_stop


def test_a_collapse_after_the_window_of_a_rollback_rolls_back_again() -> None:
    config = dataclasses.replace(CONFIG, rollback_window_phases=1)
    assert health_of(0.5, [HEALTHY_PHASE_2, health_record(3, rolled_back_to=2)], config).rolled_back_to == 2


def test_without_rollbacks_a_collapse_stops_the_loop() -> None:
    assert health_of(0.5, config=dataclasses.replace(CONFIG, rollback_window_phases=0)).hard_stop


@pytest.mark.parametrize(("rollback_window_phases", "action"), [(4, "rolled back to v0"), (0, "loop stopped")])
def test_a_collapse_alert_names_its_action(rollback_window_phases: int, action: str) -> None:
    health = health_of(0.5, config=dataclasses.replace(CONFIG, rollback_window_phases=rollback_window_phases))
    assert [alert.title for alert in health.alerts] == [f"Held-out valid Lean collapsed: {action}"]


def test_a_held_out_collapse_keeps_the_earlier_last_good_version() -> None:
    assert health_of(0.5, [HEALTHY_PHASE_2]).last_good_version == 2


def test_a_phase_without_a_held_out_evaluation_keeps_the_last_good_version() -> None:
    assert health_of(None, [HEALTHY_PHASE_2]).last_good_version == 2


def test_the_healthy_versions_have_a_held_out_evaluation_without_an_alert() -> None:
    warned = health_of(0.6, [HEALTHY_PHASE_2])
    history = [HEALTHY_PHASE_2, health_record(3), warned, health_record(6, held_out_valid_rate=0.8)]
    assert healthy_versions(history) == [2, 6]


def test_the_health_history_keeps_the_last_record_of_a_phase(tmp_path: Path) -> None:
    path = tmp_path / "health.jsonl"
    append_health(path, health_record(1))
    append_health(path, health_record(1, held_out_valid_rate=0.8))
    assert read_health_history(path) == [health_record(1, held_out_valid_rate=0.8)]


def test_a_cleared_health_stop_is_kept_beside_it(tmp_path: Path) -> None:
    path = tmp_path / "health_stop.json"
    write_health_stop(path, health_of(0.5))
    kept = clear_health_stop(path)
    assert (path.exists(), kept.exists()) == (False, True)


@pytest.mark.parametrize(("field", "count"), [("root_blocks", 2), ("root_judged_blocks", 2), ("root_valid_blocks", 1)])
def test_a_tree_counts_its_roots_first_round_blocks(field: str, count: int) -> None:
    assert getattr(summary_of(record()), field) == count


def test_a_tree_records_the_versions_that_sampled_it() -> None:
    tree = dataclasses.replace(record(), expansions=(ExpansionTexts("test.t0", 0, "prompt", (), policy_version=3),))
    assert summary_of(tree).sampling_versions == (3,)
