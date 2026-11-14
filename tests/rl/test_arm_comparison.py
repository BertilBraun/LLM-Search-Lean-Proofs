import dataclasses

import pytest

pytest.importorskip("numpy")

import numpy as np  # noqa: E402

from lean_search.rl.arm_comparison import (  # noqa: E402
    Arm,
    ArmRun,
    RunSettings,
    SearchEnd,
    StatementOutcome,
    VerdictKind,
    against_reference,
    compare_arms,
    confirm_with_seeds,
    mcnemar_p_value,
    search_end,
    stratified_interval,
)
from lean_search.search import SearchResult, StopReason  # noqa: E402
from lean_search.search.search import Accounting  # noqa: E402

STRATA = ["0-499", "500-999", "1000-1499", "1500-1999"]
PROBLEMS = [f"problem_{index:03d}" for index in range(400)]
STRATUM_OF = {problem: STRATA[index // 100] for index, problem in enumerate(PROBLEMS)}
SETTINGS = RunSettings("probe digest", 16, 7200.0, "search digest")


def run(name: str, solved: set[str], identity: str = "", settings: RunSettings = SETTINGS) -> ArmRun:
    outcomes = tuple(
        StatementOutcome(
            problem,
            STRATUM_OF[problem],
            problem in solved,
            3 if problem in solved else None,
            SearchEnd.PROVED if problem in solved else SearchEnd.EXPANSIONS,
            1000,
        )
        for problem in PROBLEMS
    )
    return ArmRun(name, identity or name.rsplit("_", 1)[0], settings, outcomes)


def arm(label: str, *solved_sets: set[str]) -> Arm:
    return Arm(label, tuple(run(f"{label}_{index}", solved) for index, solved in enumerate(solved_sets)))


def every_fourth(offset: int, count: int) -> set[str]:
    """`count` statements spread over every stratum."""
    return set(PROBLEMS[offset::4][:count])


BASE = every_fourth(0, 100) | every_fourth(1, 60)


def test_a_clear_difference_differs_with_the_better_arm_ahead() -> None:
    comparison = compare_arms(arm("A", BASE | every_fourth(2, 40)), arm("B", BASE))
    assert (comparison.verdict.kind, comparison.verdict.ahead) == (VerdictKind.DIFFER, "A")


def test_arms_with_the_same_outcomes_show_no_difference() -> None:
    assert compare_arms(arm("A", BASE), arm("B", BASE)).verdict.kind == VerdictKind.NO_DIFFERENCE


def test_noisy_arms_without_a_shift_show_no_difference() -> None:
    first = BASE | every_fourth(2, 20)
    second = BASE | set(sorted(every_fourth(3, 100))[:20])
    assert compare_arms(arm("A", first), arm("B", second)).verdict.kind == VerdictKind.NO_DIFFERENCE


def test_a_difference_under_three_points_with_an_interval_excluding_zero_shows_no_difference() -> None:
    comparison = compare_arms(arm("A", BASE | every_fourth(2, 8)), arm("B", BASE))
    assert (comparison.overall.lower > 0, comparison.verdict.kind) == (True, VerdictKind.NO_DIFFERENCE)


def test_two_runs_of_an_arm_pool_per_statement_as_the_mean_outcome() -> None:
    comparison = compare_arms(arm("A", BASE, BASE | every_fourth(2, 40)), arm("B", BASE))
    assert comparison.overall.difference == pytest.approx(20 / 400)


def test_every_pair_of_single_runs_gets_its_mcnemar() -> None:
    comparison = compare_arms(arm("A", BASE, BASE), arm("B", BASE, BASE))
    assert len(comparison.mcnemar) == 4


def test_mcnemar_is_the_exact_binomial_test_of_the_discordant_statements() -> None:
    assert mcnemar_p_value(10, 0) == pytest.approx(2 / 1024)


def test_mcnemar_without_discordant_statements_is_one() -> None:
    assert mcnemar_p_value(0, 0) == 1.0


def test_the_solved_within_curve_counts_proofs_found_within_each_budget() -> None:
    comparison = compare_arms(arm("A", BASE), arm("B", BASE))
    assert [point.x_solved for point in comparison.within] == [0.0, 0.0, 160 / 400, 160 / 400, 160 / 400]


def test_the_bootstrap_is_reproducible_by_seed() -> None:
    differences = np.array([1.0, 0.0, -1.0, 0.5] * 50)
    strata = np.array(["a", "b"] * 100)
    assert stratified_interval(differences, strata, 7) == stratified_interval(differences, strata, 7)


def test_the_bootstrap_resamples_within_each_stratum() -> None:
    """Constant within each stratum, so a stratified draw always has the same mean."""
    differences = np.array([1.0] * 50 + [0.0] * 150)
    strata = np.array(["a"] * 50 + ["b"] * 150)
    assert stratified_interval(differences, strata, 0) == pytest.approx((0.25, 0.25))


@pytest.mark.parametrize(
    "other",
    [
        dataclasses.replace(SETTINGS, probe_set_sha256="another probe"),
        dataclasses.replace(SETTINGS, max_expansions=32),
        dataclasses.replace(SETTINGS, max_wall_seconds=14400.0),
        dataclasses.replace(SETTINGS, run_config_sha256="another search"),
    ],
)
def test_runs_searched_otherwise_are_refused(other: RunSettings) -> None:
    with pytest.raises(ValueError, match="differ"):
        compare_arms(arm("A", BASE), Arm("B", (run("B_0", BASE, settings=other),)))


def test_another_search_config_is_compared_across_search_modes() -> None:
    other = dataclasses.replace(SETTINGS, run_config_sha256="no reasoning")
    comparison = compare_arms(arm("A", BASE), Arm("B", (run("B_0", BASE, settings=other),)), across_search_modes=True)
    assert comparison.overall.difference == 0.0


@pytest.mark.parametrize(
    "other",
    [
        dataclasses.replace(SETTINGS, probe_set_sha256="another probe"),
        dataclasses.replace(SETTINGS, max_expansions=32),
        dataclasses.replace(SETTINGS, max_wall_seconds=14400.0),
    ],
)
def test_across_search_modes_the_probe_budget_and_wall_cap_must_still_match(other: RunSettings) -> None:
    with pytest.raises(ValueError, match="differ"):
        compare_arms(arm("A", BASE), Arm("B", (run("B_0", BASE, settings=other),)), across_search_modes=True)


def test_an_arm_pooling_two_checkpoints_is_refused() -> None:
    mixed = Arm("A", (run("A_0", BASE, identity="A phase 16"), run("A_1", BASE, identity="A phase 8")))
    with pytest.raises(ValueError, match="identities"):
        compare_arms(mixed, arm("B", BASE))


def seed_arms(label: str, first: set[str], second: set[str]) -> tuple[Arm, Arm]:
    return arm(f"{label}1", first), arm(f"{label}2", second)


def test_seeds_that_agree_on_a_large_difference_confirm_it() -> None:
    ahead = BASE | every_fourth(2, 60)
    confirmation = confirm_with_seeds(seed_arms("A", ahead, ahead), seed_arms("B", BASE, BASE))
    assert (confirmation.confirmed, confirmation.ahead) == (True, "A1")


def test_seeds_that_disagree_are_not_confirmed() -> None:
    ahead = BASE | every_fourth(2, 60)
    behind = set(sorted(BASE)[:100])
    confirmation = confirm_with_seeds(seed_arms("A", ahead, behind), seed_arms("B", BASE, BASE))
    assert not confirmation.confirmed


def test_a_seed_gap_over_a_third_of_the_difference_is_not_confirmed() -> None:
    """Both of A's seeds lead B's, but by 15 and 5 points: a gap of 10 against a claimed 10."""
    first, second = BASE | every_fourth(2, 60), BASE | every_fourth(2, 20)
    confirmation = confirm_with_seeds(seed_arms("A", first, second), seed_arms("B", BASE, BASE))
    assert (confirmation.confirmed, confirmation.x_seed_gap) == (False, pytest.approx(0.1))


def test_a_variant_under_three_points_from_v0_is_a_step_too_small() -> None:
    (row,) = against_reference(arm("v0", BASE, BASE), [arm("A", BASE | every_fourth(2, 4))])
    assert row.verdict.startswith("step too small")


def test_a_variant_far_ahead_of_v0_differs() -> None:
    (row,) = against_reference(arm("v0", BASE, BASE), [arm("A", BASE | every_fourth(2, 60))])
    assert row.verdict == "differ (provisional, one seed): A ahead"


def result(stop_reason: StopReason, max_depth_reached: int) -> SearchResult:
    return SearchResult("p", False, stop_reason, None, (), (), Accounting(), None, 0, max_depth_reached)


@pytest.mark.parametrize(
    ("stop_reason", "max_depth_reached", "end"),
    [
        (StopReason.TOKEN_BUDGET, 10, SearchEnd.TOKENS),
        (StopReason.EXPANSION_BUDGET, 10, SearchEnd.EXPANSIONS),
        (StopReason.WALL_CLOCK_BUDGET, 10, SearchEnd.WALL_CLOCK),
        (StopReason.FRONTIER_EXHAUSTED, 64, SearchEnd.DEPTH),
        (StopReason.FRONTIER_EXHAUSTED, 10, SearchEnd.FRONTIER),
    ],
)
def test_each_search_names_the_limit_that_ended_it(
    stop_reason: StopReason, max_depth_reached: int, end: SearchEnd
) -> None:
    assert search_end(result(stop_reason, max_depth_reached), 64) == end
