import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.monitoring.families import ProbeRatings  # noqa: E402
from lean_search.rl.probe_rating import (  # noqa: E402
    FinishedRuns,
    LoopMarkers,
    ProbeOutcome,
    ProbeRun,
    finished_probe_runs,
    paired_solve_difference,
    probe_ratings,
    rating_budgets,
    read_markers,
    solved_within,
)

PROBLEMS = [f"problem_{index:02d}" for index in range(60)]
PARTS = [PROBLEMS[part::3] for part in range(3)]


def run(
    version: int,
    solved: set[str],
    problems: list[str] = PROBLEMS,
    part: int | None = None,
    order: int = 0,
    budget: int = 16,
) -> ProbeRun:
    return ProbeRun(
        name=f"probe_slot{order:04d}_v{version:04d}",
        policy_version=version,
        value_version=version,
        part=part,
        finished_at=f"2026-10-31T{order:02d}:00:00",
        expansion_budget=budget,
        wall_clock_stops=0,
        outcomes=tuple(ProbeOutcome(name, name in solved, 3 if name in solved else None) for name in problems),
    )


NO_MARKERS = LoopMarkers()


def ratings(*runs: ProbeRun, markers: LoopMarkers = NO_MARKERS) -> ProbeRatings:
    return probe_ratings(FinishedRuns(tuple(runs), 0), markers)


def by_version(*runs: ProbeRun) -> dict[int, float]:
    return {rated.policy_version: rated.rating for rated in ratings(*runs).versions}


def test_version_zero_is_the_anchor() -> None:
    assert by_version(run(0, set(PROBLEMS[:30])), run(1, set(PROBLEMS[:40])))[0] == 0.0


def test_a_version_proving_more_of_the_same_problems_rates_higher() -> None:
    assert by_version(run(0, set(PROBLEMS[:20])), run(1, set(PROBLEMS[:40])))[1] > 0.5


def test_a_version_proving_the_same_problems_rates_near_version_zero() -> None:
    assert by_version(run(0, set(PROBLEMS[:30])), run(1, set(PROBLEMS[:30])))[1] == pytest.approx(0.0, abs=1e-6)


def test_a_version_on_hard_problems_rates_above_one_on_easy_problems_with_the_same_solve_rate() -> None:
    """Versions 0 and 1 searched everything: the first half is easy, the second hard. Version 2 proves half of the
    easy half, version 3 half of the hard half; the fit credits version 3 for the difficulty."""
    easy, hard = PROBLEMS[:30], PROBLEMS[30:]
    rated = by_version(
        run(0, set(easy[:25]) | set(hard[:3])),
        run(1, set(easy[:25]) | set(hard[3:6])),
        run(2, set(easy[:15]), easy),
        run(3, set(hard[:15]), hard),
    )
    assert rated[3] > rated[2] + 1.0


def test_the_interval_holds_the_estimate() -> None:
    rated = ratings(run(0, set(PROBLEMS[:20])), run(1, set(PROBLEMS[:35]))).versions[1]
    assert rated.lower <= rated.rating <= rated.upper


@pytest.mark.parametrize(("budget", "share"), [(2, 0.0), (4, 0.5)])
def test_solved_within_counts_proofs_by_their_first_expansion(budget: int, share: float) -> None:
    outcomes = [ProbeOutcome("a", True, 3), ProbeOutcome("b", False, None)]
    assert solved_within(outcomes, budget) == share


def test_the_baseline_reads_the_anchor_on_the_versions_own_problems() -> None:
    zero = run(0, set(PROBLEMS[:30]))
    later = run(1, set(PROBLEMS[:10]), PROBLEMS[:10])
    assert ratings(zero, later).versions[1].baseline_solved_within[-1] == 1.0


def test_a_version_sharing_no_problem_with_the_anchor_has_no_baseline() -> None:
    zero = run(0, set(PROBLEMS[:10]), PROBLEMS[:30])
    later = run(1, set(PROBLEMS[30:40]), PROBLEMS[30:])
    assert ratings(zero, later).versions[1].baseline_solved_within is None


def test_without_version_zero_the_lowest_version_is_the_named_anchor() -> None:
    assert ratings(run(3, set(PROBLEMS[:30])), run(5, set(PROBLEMS[:40]))).anchor_version == 3


def test_runs_at_another_budget_are_left_out() -> None:
    rated = ratings(run(0, set(PROBLEMS[:30])), run(1, set(PROBLEMS[:40])), run(2, set(PROBLEMS), budget=64))
    assert [version.policy_version for version in rated.versions] == [0, 1]


def test_the_budgets_double_up_to_the_probe_budget() -> None:
    assert rating_budgets(16) == (1, 2, 4, 8, 16)


def baseline_runs() -> list[ProbeRun]:
    return [run(0, set(PARTS[part][:8]), PARTS[part], part, order=part) for part in range(3)]


def pass_runs(version: int, solved_per_part: int, order: int) -> list[ProbeRun]:
    return [
        run(version + part, set(PARTS[part][:solved_per_part]), PARTS[part], part, order=order + part)
        for part in range(3)
    ]


def test_the_latest_pass_pools_the_last_run_of_every_third() -> None:
    rated = ratings(*baseline_runs(), *pass_runs(1, 10, 3), *pass_runs(4, 16, 6))
    assert rated.latest_pass.policy_versions == (4, 5, 6)


def test_a_stronger_pass_is_ahead_of_the_previous_one() -> None:
    rated = ratings(*baseline_runs(), *pass_runs(1, 8, 3), *pass_runs(4, 17, 6))
    assert rated.against_previous.lower > 0


def test_without_a_run_on_every_third_there_is_no_pass() -> None:
    assert ratings(*baseline_runs(), *pass_runs(1, 10, 3)[:2]).latest_pass is None


def test_rejected_versions_are_left_out_of_the_passes() -> None:
    rated = ratings(*baseline_runs(), *pass_runs(1, 10, 3), *pass_runs(4, 16, 6), markers=LoopMarkers((6,), None))
    assert rated.latest_pass.policy_versions == (4, 5, 3)


def test_the_pre_fix_comparison_waits_for_a_pass_wholly_after_the_fix() -> None:
    rated = ratings(*baseline_runs(), *pass_runs(1, 10, 3), *pass_runs(4, 16, 6), markers=LoopMarkers((), 6))
    assert rated.against_pre_fix is None


def test_a_pass_wholly_after_the_fix_is_compared_with_the_last_pre_fix_pass() -> None:
    rated = ratings(*baseline_runs(), *pass_runs(1, 10, 3), *pass_runs(4, 16, 6), markers=LoopMarkers((), 4))
    assert rated.against_pre_fix.reference.policy_versions == (1, 2, 3)


RESULT = {
    "problem_name": "a",
    "proved": True,
    "stop_reason": "proved",
    "proof": "simp",
    "proof_steps": ["simp"],
    "proof_sources": ["policy"],
    "accounting": {"expansions": 2},
    "solved_at": {"expansions": 1},
    "verification_failures": 0,
    "max_depth_reached": 1,
}
SUMMARY = {"policy_version": 3, "value_version": 3, "part": 1, "finished_at": "", "expansion_budget": 16}


def write_run(directory: Path, summary: str | None = json.dumps(SUMMARY), results: str | None = None) -> None:
    directory.mkdir(parents=True)
    (directory / "results.jsonl").write_text(
        json.dumps(RESULT) + "\n" if results is None else results, encoding="utf-8"
    )
    if summary is not None:
        (directory / "summary.json").write_text(summary, encoding="utf-8")


def test_only_finished_runs_without_a_value_arm_are_rated(tmp_path: Path) -> None:
    write_run(tmp_path / "probe_slot0001_v0003")
    write_run(tmp_path / "probe_slot0002_v0003", summary=None)
    write_run(tmp_path / "probe_slot0001_v0003_value_arm")
    assert [found.name for found in finished_probe_runs(tmp_path).runs] == ["probe_slot0001_v0003"]


def test_a_finished_runs_proof_counts_at_its_first_expansion(tmp_path: Path) -> None:
    write_run(tmp_path / "probe_slot0001_v0003")
    (found,) = finished_probe_runs(tmp_path).runs
    assert found.outcomes[0].expansions_to_proof == 1


@pytest.mark.parametrize(
    ("summary", "results"),
    [
        ("{", None),
        (json.dumps({"policy_version": 3}), None),
        (json.dumps(SUMMARY), '{"problem_name": "a"}\n'),
        (json.dumps(SUMMARY), ""),
    ],
)
def test_an_unreadable_or_empty_run_is_counted_and_skipped(tmp_path: Path, summary: str, results: str | None) -> None:
    write_run(tmp_path / "probe_slot0001_v0003", summary=summary, results=results)
    assert finished_probe_runs(tmp_path) == FinishedRuns((), 1)


def write_versions(directory: Path, triggers: dict[int, str]) -> None:
    (directory / "models").mkdir()
    lines = [json.dumps({"version": version, "trigger": trigger}) + "\n" for version, trigger in triggers.items()]
    (directory / "models" / "versions.jsonl").write_text("".join(lines), encoding="utf-8")


def test_the_reward_fix_marks_the_version_its_first_phase_published_after_a_rollback(tmp_path: Path) -> None:
    (tmp_path / "reward_fix.json").write_text(json.dumps({"first_phase": 15, "recorded_at": ""}), encoding="utf-8")
    write_versions(tmp_path, {15: "phase 14", 16: "rollback to v4 after phase 14", 17: "phase 15"})
    assert read_markers(tmp_path).reward_fix_version == 17


def test_a_reward_fix_whose_phase_published_nothing_yet_marks_no_version(tmp_path: Path) -> None:
    (tmp_path / "reward_fix.json").write_text(json.dumps({"first_phase": 15, "recorded_at": ""}), encoding="utf-8")
    write_versions(tmp_path, {15: "phase 14"})
    assert read_markers(tmp_path).reward_fix_version is None


def test_an_unreadable_reward_fix_counts_as_absent(tmp_path: Path) -> None:
    (tmp_path / "reward_fix.json").write_text("{", encoding="utf-8")
    assert read_markers(tmp_path) == LoopMarkers()


def test_rejected_versions_are_read_once_each(tmp_path: Path) -> None:
    lines = [{"version": version, "reason": "", "rejected_at": ""} for version in (10, 5, 10)]
    (tmp_path / "rejected_versions.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    assert read_markers(tmp_path).rejected_versions == (5, 10)


def whole_set_after_two_slots() -> tuple[list[ProbeRun], ProbeRun]:
    """Version 1 then version 2 search the first third, version 3 the whole set proving that third."""
    earlier = [run(1, set(), PARTS[0], part=0, order=1), run(2, set(PARTS[0]), PARTS[0], part=0, order=2)]
    return earlier, run(3, set(PARTS[0]), order=3)


def test_the_paired_difference_compares_each_problem_with_its_latest_earlier_run() -> None:
    earlier, whole_set = whole_set_after_two_slots()
    difference = paired_solve_difference([*earlier, whole_set], whole_set, ())
    assert (difference.problems, difference.difference) == (len(PARTS[0]), 0.0)


def test_the_paired_difference_never_compares_with_a_rejected_version() -> None:
    earlier, whole_set = whole_set_after_two_slots()
    assert paired_solve_difference([*earlier, whole_set], whole_set, (2,)).difference == 1.0
