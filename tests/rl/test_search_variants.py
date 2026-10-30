import dataclasses
from pathlib import Path

import pytest
from test_prompt_groups import REFERENCE_STEPS, REPAIRED, REPAIRS, add_sample, feedback_tree, record_of, root_tree

from lean_search.data import Problem, Split
from lean_search.lean import ProofState
from lean_search.policy.config import FeedbackConfig
from lean_search.rl.loop import LoopProgress, PhaseStage
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_variants import (
    ErrorCategory,
    ErrorCounts,
    RequestedSamples,
    SampleOutcomes,
    SearchVariant,
    SearchVariantsConfig,
    ServedVersion,
    StateResult,
    VariantResults,
    compare_variants,
    comparison_text,
    error_category,
    feedback_report,
    holm_corrected,
    interleaved_chunks,
    load_search_variants_config,
    paired_metrics,
    pairings,
    parse_search_variants_config,
    served_version,
    state_result,
    variant_run_config,
)
from lean_search.rl.single_step import StateProblem, sample_success
from lean_search.search import ExpanderKind, Failure, FailureKind, RunConfig, StepSource, load_run_config

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY / "experiments" / "configs" / "grpo" / "search_variants.toml"
TARGET = EvaluationTarget(max_expansions=1, max_wall_seconds=120.0, concurrency=40)
SHIPPED = [
    "baseline",
    "baseline_2",
    "feedback_always",
    "feedback_blind",
    "sweep_first",
    "tried_context",
    "name_repair",
    "temperature_0.6",
    "temperature_0.7",
    "temperature_1.0",
]
REQUESTED = RequestedSamples(first_round=3, feedback=2)
REFERENCE_KEYS = frozenset(REFERENCE_STEPS)


def template() -> RunConfig:
    return load_run_config(REPOSITORY / "experiments" / "configs" / "grpo" / "search" / "visible_student_v2.toml")


def shipped(name: str) -> RunConfig:
    return variant_run_config(template(), load_search_variants_config(CONFIG).variant(name), TARGET)


def test_shipped_config_has_the_variants_and_controls() -> None:
    assert [variant.name for variant in load_search_variants_config(CONFIG).variants] == SHIPPED


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_variants_make_valid_run_configs(name: str) -> None:
    assert shipped(name).search.max_expansions == 1


def test_baseline_is_the_loop_s_held_out_evaluation() -> None:
    config = variant_run_config(template(), SearchVariant("baseline"), TARGET)
    assert (config.expander.kind, config.policy.temperature, config.search.max_wall_seconds) == (
        ExpanderKind.POLICY,
        0.8,
        120.0,
    )


def test_baseline_turns_off_options_the_template_enables() -> None:
    enabled = dataclasses.replace(template().policy, feedback=FeedbackConfig(enabled=True))
    config = variant_run_config(dataclasses.replace(template(), policy=enabled), SearchVariant("baseline"), TARGET)
    assert not config.policy.feedback.enabled


def test_temperature_variant_overrides_the_template_s() -> None:
    assert shipped("temperature_1.0").policy.temperature == 1.0


def test_tried_context_runs_the_sweep_first() -> None:
    config = shipped("tried_context")
    assert (config.expander.kind, config.expander.overlap, config.search.harvest.enabled) == (
        ExpanderKind.AUTOMATION_THEN_POLICY,
        False,
        True,
    )


def test_sweep_first_runs_the_sweep_without_the_prompt_line() -> None:
    config = shipped("sweep_first")
    assert (config.expander.kind, config.expander.overlap, config.policy.failed_automation_in_prompt) == (
        ExpanderKind.AUTOMATION_THEN_POLICY,
        False,
        False,
    )


def test_blind_feedback_hides_the_attempts() -> None:
    assert shipped("feedback_blind").policy.feedback.show_attempts is False


def test_always_feedback_fires_whatever_the_first_round_reached() -> None:
    assert shipped("feedback_always").policy.feedback.min_children > shipped("feedback_always").policy.sample_count


@pytest.mark.parametrize(
    "text",
    [
        'name = "x"\n[[variants]]\nname = "a"\n',
        'name = "x"\n[[variants]]\nname = "baseline"\n[[variants]]\nname = "baseline"\n',
        'name = "x"\n[[variants]]\nname = "baseline"\n[[variants]]\nname = "../b"\n',
        'name = "x"\nsecond_baseline = "b2"\n[[variants]]\nname = "baseline"\n[[variants]]\nname = "b2"\n'
        "temperature = 0.6\n",
        'name = "x"\n[[variants]]\nname = "baseline"\ncompared_with = ["missing"]\n',
    ],
)
def test_invalid_variants_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_search_variants_config(text)


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (Failure(FailureKind.ERROR, "linarith failed to find a contradiction\ncase a"), ErrorCategory.LINARITH),
        (Failure(FailureKind.ERROR, "simp made no progress"), ErrorCategory.SIMP_NO_PROGRESS),
        (Failure(FailureKind.ERROR, "simp_all made no progress"), ErrorCategory.SIMP_NO_PROGRESS),
        (
            Failure(FailureKind.ERROR, "tactic 'rewrite' failed, did not find instance of the pattern"),
            ErrorCategory.REWRITE_PATTERN,
        ),
        (Failure(FailureKind.ERROR, "type mismatch\n  h"), ErrorCategory.TYPE_MISMATCH),
        (Failure(FailureKind.ERROR, "omega could not prove the goal"), ErrorCategory.OMEGA),
        (Failure(FailureKind.ERROR, "<input>:1:5: unexpected token ']'"), ErrorCategory.SYNTAX),
        (Failure(FailureKind.ERROR, "unknown identifier 'Nat.foo'"), ErrorCategory.UNKNOWN_IDENTIFIER),
        (Failure(FailureKind.UNKNOWN_IDENTIFIER, "unknown identifier 'h₂'"), ErrorCategory.UNKNOWN_IDENTIFIER),
        (Failure(FailureKind.ERROR, "unsolved goals\n⊢ x"), ErrorCategory.UNSOLVED_GOALS),
        (Failure(FailureKind.HEARTBEAT_TIMEOUT, "deterministic timeout"), ErrorCategory.TIMEOUT),
        (Failure(FailureKind.ERROR, "positivity failed"), ErrorCategory.OTHER),
    ],
)
def test_errors_fall_into_their_category(failure: Failure, category: ErrorCategory) -> None:
    assert error_category(failure) == category


def feedback_state(requested: RequestedSamples = REQUESTED) -> StateResult:
    return state_result("t", feedback_tree(), REFERENCE_KEYS, requested)


def test_state_result_counts_every_policy_sample() -> None:
    assert (feedback_state().samples, feedback_state().successes) == (5, 2)


def test_state_result_counts_the_first_round_apart() -> None:
    state = feedback_state()
    assert (state.first_round_samples, state.first_round_successes) == (3, 1)


def test_state_result_counts_the_feedback_round_apart() -> None:
    state = feedback_state()
    assert (state.feedback_fired, state.feedback_samples, state.feedback_successes) == (True, 2, 1)


def test_state_result_counts_distinct_new_states() -> None:
    assert (feedback_state().children, feedback_state().successful_children) == (1, 1)


def test_state_result_counts_the_repair_apart() -> None:
    assert (feedback_state().repaired_samples, feedback_state().repaired_successes) == (1, 1)


def test_samples_never_run_count_as_failures() -> None:
    state = feedback_state(RequestedSamples(first_round=8, feedback=2))
    assert (state.cut_off_samples, state.denominator) == (5, 10)


def test_state_result_sorts_samples_by_outcome() -> None:
    assert feedback_state().outcomes == SampleOutcomes(new_state=1, existing_state=1, lean_error=3)


def test_state_result_categorizes_the_errors() -> None:
    assert feedback_state().errors == ErrorCounts(unknown_identifier=1, linarith=2)


def repair_only_state() -> StateResult:
    tree = root_tree()
    add_sample(tree, "rw [Nat.add_zeroo, h₀]", False)
    add_sample(tree, REPAIRED, True, repairs=REPAIRS, source=StepSource.REPAIR)
    return state_result("t", record_of(tree), REFERENCE_KEYS, RequestedSamples(1, 0))


def test_state_solved_only_by_a_repair_is_not_solved_by_the_policy() -> None:
    assert (repair_only_state().solved, repair_only_state().solved_with_repairs) == (False, True)


def test_older_repaired_policy_edge_counts_as_a_failed_sample() -> None:
    tree = root_tree()
    add_sample(tree, REPAIRED, True, repairs=REPAIRS)
    state = state_result("t", record_of(tree), REFERENCE_KEYS, RequestedSamples(1, 0))
    assert (state.successes, state.repaired_successes, state.errors.unknown_identifier) == (0, 1, 1)


def test_held_out_success_judges_a_repaired_sample_by_its_own_run() -> None:
    assert sample_success(feedback_tree(), REFERENCE_KEYS).successes == 2


def result(
    name: str, solved: bool, *, first_round_solved: bool | None = None, children: int = 1, tokens: int = 100
) -> StateResult:
    first = solved if first_round_solved is None else first_round_solved
    return StateResult(
        name=name,
        samples=8,
        cut_off_samples=0,
        successes=int(solved),
        valid=8,
        solved=solved,
        children=children,
        successful_children=int(solved),
        first_round_samples=8,
        first_round_cut_off=0,
        first_round_successes=int(first),
        first_round_solved=first,
        first_round_children=children,
        first_round_successful_children=int(first),
        feedback_fired=solved != first,
        feedback_samples=0,
        feedback_successes=0,
        feedback_generated_tokens=0,
        repaired_samples=0,
        repaired_successes=0,
        solved_with_repairs=solved,
        outcomes=SampleOutcomes(),
        errors=ErrorCounts(),
        prompt_tokens=10,
        generated_tokens=tokens,
        lean_seconds=1.0,
        sweep_lean_seconds=0.0,
        wall_seconds=2.0,
    )


def metric(variant: list[StateResult], baseline: list[StateResult], name: str) -> float:
    (found,) = [entry for entry in paired_metrics("v", "b", variant, baseline, 200, 0.95, 0) if entry.metric == name]
    return found.difference


def test_paired_metrics_use_the_common_states_only() -> None:
    variant = [result("a", True), result("b", False), result("c", True)]
    assert metric(variant, [result("a", True), result("b", False)], "solved") == pytest.approx(0.0)


def test_feedback_that_only_rescues_a_state_shows_a_gain() -> None:
    baseline = [result("easy", True), result("hard", False)]
    variant = [result("easy", True), result("hard", True, first_round_solved=False)]
    assert metric(variant, baseline, "solved") == pytest.approx(0.5)


def test_per_token_metric_divides_by_the_generated_tokens() -> None:
    variant = [result("a", True, tokens=500)]
    assert metric(variant, [result("a", True, tokens=1000)], "solved per 1k tokens") == pytest.approx(1.0)


def test_paired_interval_contains_the_difference() -> None:
    variant = [result(str(index), index % 2 == 0, children=index % 5) for index in range(40)]
    baseline = [result(str(index), index % 3 == 0, children=index % 3) for index in range(40)]
    entries = paired_metrics("v", "b", variant, baseline, 500, 0.95, 0)
    assert all(entry.interval_low <= entry.difference <= entry.interval_high for entry in entries)


def test_holm_scales_the_ordered_p_values_and_keeps_them_monotone() -> None:
    entries = paired_metrics("v", "b", [result("a", True)], [result("a", True)], 10, 0.95, 0)[:3]
    entries = [dataclasses.replace(entry, p_value=p) for entry, p in zip(entries, [0.01, 0.04, 0.03], strict=True)]
    assert [entry.holm_p_value for entry in holm_corrected(entries, 0.05)] == pytest.approx([0.03, 0.06, 0.06])


def variants_config() -> SearchVariantsConfig:
    return load_search_variants_config(CONFIG)


def test_tried_context_is_paired_with_the_baseline_and_sweep_first() -> None:
    assert [pair for pair in pairings(SHIPPED, variants_config()) if pair[0] == "tried_context"] == [
        ("tried_context", "baseline"),
        ("tried_context", "sweep_first"),
    ]


def test_the_a_a_pair_is_outside_the_family() -> None:
    assert all("baseline_2" not in pair for pair in pairings(SHIPPED, variants_config()))


def runs() -> list[VariantResults]:
    states = [result(str(index), index % 2 == 0) for index in range(8)]
    return [VariantResults(name, shipped(name), tuple(states)) for name in ("baseline", "baseline_2", "name_repair")]


def test_second_baseline_gives_the_noise_floor() -> None:
    comparison = compare_variants(runs(), dataclasses.replace(variants_config(), bootstrap_samples=50))
    assert {entry.variant for entry in comparison.noise_floor} == {"baseline_2"}


def test_comparison_text_states_the_correction() -> None:
    text = comparison_text(compare_variants(runs(), dataclasses.replace(variants_config(), bootstrap_samples=50)))
    assert "Holm-corrected over the family of 6 tests" in text


def test_feedback_report_counts_rescued_states_by_first_round_new_states() -> None:
    results = [result("a", True, first_round_solved=False, children=0), result("b", True, children=0)]
    assert feedback_report("f", results).strata[0].rescued == 1


@pytest.mark.parametrize(
    ("stage", "expected"),
    [(PhaseStage.SAMPLING, ServedVersion(4, 3)), (PhaseStage.TRAINING, None), (PhaseStage.PUBLISHING, None)],
)
def test_served_version_is_known_only_while_the_loop_samples(stage: PhaseStage, expected: ServedVersion | None) -> None:
    assert served_version(LoopProgress(phase=4, stage=stage), 3) == expected


def test_states_are_searched_in_chunks() -> None:
    states = [state_problem_of(index) for index in range(130)]
    assert [len(chunk) for chunk in interleaved_chunks(states, 64)] == [64, 64, 2]


def state_problem_of(index: int) -> StateProblem:
    problem = Problem(f"s{index}", Split.VALID, "", "theorem t : True := by", "", "")
    return StateProblem(problem, ProofState("", problem.formal_statement, (), ("⊢ True",), 0, 0), {})
