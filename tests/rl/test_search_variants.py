from pathlib import Path

import pytest
from test_prompt_groups import REFERENCE_STEPS, feedback_tree

from lean_search.policy.config import FeedbackConfig
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_variants import (
    ErrorCategory,
    ErrorCounts,
    SampleOutcomes,
    SearchVariant,
    StateResult,
    error_category,
    load_search_variants_config,
    paired_comparison,
    parse_search_variants_config,
    state_result,
    variant_run_config,
)
from lean_search.rl.single_step import sample_success
from lean_search.search import ExpanderKind, Failure, FailureKind, RunConfig, load_run_config

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY / "experiments" / "configs" / "grpo" / "search_variants.toml"
TARGET = EvaluationTarget(max_expansions=1, max_wall_seconds=120.0, concurrency=112)


def template() -> RunConfig:
    return load_run_config(REPOSITORY / "experiments" / "configs" / "grpo" / "search" / "visible_student_v2.toml")


def test_shipped_config_has_the_approved_variants() -> None:
    assert [variant.name for variant in load_search_variants_config(CONFIG).variants] == [
        "baseline",
        "feedback",
        "tried_context",
        "name_repair",
        "temperature_0.6",
        "temperature_0.7",
        "combined",
    ]


@pytest.mark.parametrize("name", ["baseline", "feedback", "tried_context", "name_repair", "combined"])
def test_shipped_variants_make_valid_run_configs(name: str) -> None:
    variant = load_search_variants_config(CONFIG).variant(name)
    assert variant_run_config(template(), variant, TARGET).search.max_expansions == 1


def test_baseline_is_the_loop_s_held_out_evaluation() -> None:
    config = variant_run_config(template(), SearchVariant("baseline"), TARGET)
    assert (config.expander.kind, config.policy.temperature, config.search.max_wall_seconds) == (
        ExpanderKind.POLICY,
        0.8,
        120.0,
    )


def test_temperature_variant_overrides_the_template_s() -> None:
    assert variant_run_config(template(), SearchVariant("cool", temperature=0.6), TARGET).policy.temperature == 0.6


def test_failed_automation_variant_runs_the_sweep_first() -> None:
    config = variant_run_config(template(), SearchVariant("tried", failed_automation_in_prompt=True), TARGET)
    assert (config.expander.kind, config.expander.overlap, config.search.harvest.enabled) == (
        ExpanderKind.AUTOMATION_THEN_POLICY,
        False,
        True,
    )


def test_feedback_variant_reaches_the_policy() -> None:
    feedback = FeedbackConfig(enabled=True, sample_count=4)
    assert variant_run_config(template(), SearchVariant("f", feedback=feedback), TARGET).policy.feedback == feedback


@pytest.mark.parametrize(
    "text",
    [
        'name = "x"\n[[variants]]\nname = "a"\n',
        'name = "x"\n[[variants]]\nname = "baseline"\n[[variants]]\nname = "baseline"\n',
        'name = "x"\n[[variants]]\nname = "baseline"\n[[variants]]\nname = "../b"\n',
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


def feedback_state() -> StateResult:
    return state_result("t", feedback_tree(), frozenset(REFERENCE_STEPS))


def test_state_result_counts_every_root_sample() -> None:
    assert (feedback_state().samples, feedback_state().successes) == (5, 3)


def test_state_result_counts_the_feedback_round_apart() -> None:
    assert (feedback_state().feedback_samples, feedback_state().feedback_successes) == (2, 1)


def test_state_result_counts_repaired_samples() -> None:
    assert (feedback_state().repaired_samples, feedback_state().repaired_successes) == (1, 1)


def test_state_result_sorts_samples_by_outcome() -> None:
    assert feedback_state().outcomes == SampleOutcomes(new_state=1, existing_state=2, lean_error=2)


def test_state_result_categorizes_the_errors() -> None:
    assert feedback_state().errors == ErrorCounts(linarith=2)


def result(name: str, successes: int, samples: int = 8) -> StateResult:
    return StateResult(
        name, samples, successes, samples, 0, 0, 0, 0, 1, SampleOutcomes(), ErrorCounts(), 100, 200, 1.0, 2.0
    )


def test_paired_comparison_uses_the_common_states_only() -> None:
    variant = [result("a", 4), result("b", 0), result("c", 8)]
    baseline = [result("a", 2), result("b", 2)]
    comparison = paired_comparison("v", "baseline", variant, baseline, 100, 0.95, 0)
    assert (comparison.states, comparison.difference) == (2, pytest.approx(0.0))


def test_paired_comparison_counts_states_solved_by_one_run_only() -> None:
    variant = [result("a", 4), result("b", 0), result("c", 1)]
    baseline = [result("a", 0), result("b", 2), result("c", 0)]
    comparison = paired_comparison("v", "baseline", variant, baseline, 100, 0.95, 0)
    assert (comparison.states_only_variant, comparison.states_only_baseline) == (2, 1)


def test_paired_interval_contains_the_difference() -> None:
    variant = [result(str(index), index % 5) for index in range(40)]
    baseline = [result(str(index), index % 3) for index in range(40)]
    comparison = paired_comparison("v", "baseline", variant, baseline, 500, 0.95, 0)
    assert comparison.interval_low <= comparison.difference <= comparison.interval_high


def test_held_out_success_counts_a_repaired_sample_as_failed() -> None:
    assert sample_success(feedback_tree(), frozenset(REFERENCE_STEPS)).successes == 2
