import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.rl.probe_rating import (  # noqa: E402
    ProbeOutcome,
    ProbeRun,
    finished_probe_runs,
    probe_ratings,
    rating_budgets,
    solved_within,
)

PROBLEMS = [f"problem_{index}" for index in range(60)]


def run(version: int, solved: set[int], expansions: int = 3) -> ProbeRun:
    return ProbeRun(
        f"probe_v{version:04d}",
        16,
        tuple(
            ProbeOutcome(version, version, name, index in solved, expansions if index in solved else None)
            for index, name in enumerate(PROBLEMS)
        ),
    )


def ratings_by_version(runs: list[ProbeRun]) -> dict[int, float]:
    return {rated.policy_version: rated.rating for rated in probe_ratings(runs).versions}


def test_version_zero_is_the_anchor() -> None:
    assert ratings_by_version([run(0, set(range(30))), run(1, set(range(40)))])[0] == 0.0


def test_a_version_proving_more_of_the_same_problems_rates_higher() -> None:
    assert ratings_by_version([run(0, set(range(20))), run(1, set(range(40)))])[1] > 0.5


def test_a_version_proving_the_same_problems_rates_near_version_zero() -> None:
    assert ratings_by_version([run(0, set(range(30))), run(1, set(range(30)))])[1] == pytest.approx(0.0, abs=1e-6)


def test_a_version_on_harder_problems_rates_above_its_raw_solve_rate() -> None:
    """Version 2 proves half of the hard problems that version 0 and 1 rarely proved: the fit credits the difficulty."""
    hard = set(range(30, 60))
    runs = [run(0, set(range(25)) | {30}), run(1, set(range(25)) | {31}), run(2, set(range(30, 45)))]
    runs[2] = ProbeRun(
        runs[2].name, 16, tuple(outcome for outcome in runs[2].outcomes if int(outcome.problem[8:]) in hard)
    )
    ratings = ratings_by_version(runs)
    assert ratings[2] > ratings[1] + 1.0


def test_the_interval_holds_the_estimate() -> None:
    rated = probe_ratings([run(0, set(range(20))), run(1, set(range(35)))]).versions[1]
    assert rated.lower <= rated.rating <= rated.upper


@pytest.mark.parametrize(("budget", "share"), [(2, 0.0), (4, 0.5)])
def test_solved_within_counts_proofs_by_their_first_expansion(budget: int, share: float) -> None:
    outcomes = [ProbeOutcome(0, 0, "a", True, 3), ProbeOutcome(0, 0, "b", False, None)]
    assert solved_within(outcomes, budget) == share


def test_the_baseline_reads_version_zero_on_the_versions_own_problems() -> None:
    zero = run(0, set(range(30)))
    later = ProbeRun("probe_v0001", 16, tuple(ProbeOutcome(1, 1, name, True, 1) for name in PROBLEMS[:10]))
    assert probe_ratings([zero, later]).versions[1].baseline_solved_within[-1] == 1.0


def test_the_budgets_double_up_to_the_probe_budget() -> None:
    assert rating_budgets(16) == (1, 2, 4, 8, 16)


def write_run(directory: Path, *, summary: bool) -> None:
    directory.mkdir(parents=True)
    result = {
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
    (directory / "results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    if summary:
        fields = {
            "kind": "probe",
            "run_name": directory.name,
            "policy_version": 3,
            "value_version": 3,
            "problems": 1,
            "solved": 1,
            "by_stratum": [],
            "expansion_budget": 16,
            "expansions": 2,
            "generated_tokens": 10,
            "lean_seconds": 1.0,
            "wall_seconds": 1.0,
            "started_at": "",
            "finished_at": "",
        }
        (directory / "summary.json").write_text(json.dumps(fields), encoding="utf-8")


def test_only_finished_runs_without_a_value_arm_are_rated(tmp_path: Path) -> None:
    write_run(tmp_path / "probe_slot0001_v0003", summary=True)
    write_run(tmp_path / "probe_slot0002_v0003", summary=False)
    write_run(tmp_path / "probe_slot0001_v0003_value_arm", summary=True)
    assert [found.name for found in finished_probe_runs(tmp_path)] == ["probe_slot0001_v0003"]


def test_a_finished_runs_proof_counts_at_its_first_expansion(tmp_path: Path) -> None:
    write_run(tmp_path / "probe_slot0001_v0003", summary=True)
    (found,) = finished_probe_runs(tmp_path)
    assert found.outcomes[0].expansions_to_proof == 1
