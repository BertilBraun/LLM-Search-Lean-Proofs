import pytest

from lean_search.search import Accounting, SearchConfig, SearchResult, StepSource, StepStatistics, StopReason
from lean_search.search.summary import (
    CostMetric,
    RunMetadata,
    anytime_curve,
    category,
    expansion_budgets,
    render_markdown,
    seconds_budgets,
    summarize,
)

METADATA = RunMetadata("test", "valid", "abc", False, "config.toml", "2026-10-11T00:00:00+00:00", 1.0, 4, 0.5)


def result(
    name: str, solved_expansions: int | None, proof_steps: tuple[str, ...] = ("simp",), lean_seconds: float = 1.0
) -> SearchResult:
    solved = solved_expansions is not None
    at_solve = Accounting(expansions=solved_expansions or 0, lean_seconds=lean_seconds) if solved else None
    return SearchResult(
        problem_name=name,
        proved=solved,
        stop_reason=StopReason.PROVED if solved else StopReason.EXPANSION_BUDGET,
        proof="\n".join(proof_steps) if solved else None,
        proof_steps=proof_steps if solved else (),
        proof_sources=(StepSource.AUTOMATION,) * len(proof_steps) if solved else (),
        accounting=Accounting(expansions=solved_expansions or 16, lean_seconds=lean_seconds),
        solved_at=at_solve,
        verification_failures=0,
        max_depth_reached=len(proof_steps),
        step_statistics=(StepStatistics("simp", attempts=4, lean_seconds=lean_seconds, children=2, proofs=1),),
    )


RESULTS = [
    result("mathd_algebra_1", 1),
    result("mathd_algebra_2", 3, ("intros", "simp")),
    result("amc12a_2000_p1", 10, ("constructor", "simp", "simp")),
    result("imo_1959_p1", None),
]


def test_anytime_curve_counts_solves_within_each_budget() -> None:
    curve = anytime_curve(RESULTS, CostMetric.EXPANSIONS, [1, 2, 4, 8, 16])
    assert [point.solved for point in curve.points] == [1, 1, 2, 2, 3]


def test_anytime_solve_rate_counts_unsolved_theorems_in_the_denominator() -> None:
    curve = anytime_curve(RESULTS, CostMetric.EXPANSIONS, [16])
    assert curve.points[0].solve_rate == 0.75


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mathd_algebra_13", "mathd_algebra"),
        ("mathd_numbertheory_543", "mathd_numbertheory"),
        ("amc12a_2019_p21", "amc12"),
        ("amc12_2001_p2", "amc12"),
        ("aimeII_2001_p3", "aime"),
        ("aime_1984_p15", "aime"),
        ("imo_1966_p5", "imo"),
        ("algebra_sqineq_at2malt1", "algebra"),
        ("numbertheory_4x3m7y3neq2003", "numbertheory"),
        ("induction_12dvd4expnp1p20", "induction"),
        ("unknown_problem", "other"),
    ],
)
def test_category_is_the_name_prefix(name: str, expected: str) -> None:
    assert category(name) == expected


@pytest.mark.parametrize(
    ("max_expansions", "expected"),
    [(256, (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0)), (100, (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 100.0))],
)
def test_expansion_budgets_double_up_to_the_maximum(max_expansions: int, expected: tuple[float, ...]) -> None:
    assert expansion_budgets(max_expansions) == expected


def test_seconds_budgets_end_at_the_maximum() -> None:
    assert seconds_budgets(45.0) == (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0)


def test_summary_counts_solves_with_two_or_more_steps() -> None:
    summary = summarize(RESULTS, METADATA, SearchConfig(max_expansions=16))
    assert summary.solved_at_depth_two_or_more == 2


def test_summary_reports_category_solve_rates() -> None:
    summary = summarize(RESULTS, METADATA, SearchConfig(max_expansions=16))
    assert [(entry.category, entry.solved, entry.problems) for entry in summary.categories] == [
        ("mathd_algebra", 2, 2),
        ("amc12", 1, 1),
        ("imo", 0, 1),
    ]


def test_summary_counts_steps_on_proof_paths() -> None:
    summary = summarize(RESULTS, METADATA, SearchConfig(max_expansions=16))
    assert {cost.step: cost.on_proof_paths for cost in summary.steps} == {"simp": 4}


def test_markdown_states_the_solve_rate() -> None:
    summary = summarize(RESULTS, METADATA, SearchConfig(max_expansions=16))
    assert "**Solved 3/4 (75.0%).**" in render_markdown(summary, "Test")
