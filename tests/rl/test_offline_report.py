import dataclasses

import pytest

pytest.importorskip("numpy")

from lean_search.rl.arm_comparison import Arm, ArmRun, RunSettings, SearchEnd, StatementOutcome  # noqa: E402
from lean_search.rl.offline_report import (  # noqa: E402
    PairedDifference,
    gate_report,
    paired_difference,
    passes_gate,
    within_budget,
)

SETTINGS = RunSettings("probe", 16, 7200.0, None, 64, 112, "config")
STRATA = ("0-499", "500-999")


def outcome(index: int, expansions: int | None) -> StatementOutcome:
    proved = expansions is not None
    end = SearchEnd.PROVED if proved else SearchEnd.EXPANSIONS
    return StatementOutcome(f"p{index}", STRATA[index % 2], proved, expansions, end, 100)


def run(name: str, expansions: list[int | None], settings: RunSettings = SETTINGS) -> ArmRun:
    return ArmRun(name, name, settings, tuple(outcome(index, found) for index, found in enumerate(expansions)))


def arm(label: str, expansions: list[int | None], settings: RunSettings = SETTINGS) -> Arm:
    return Arm(label, (run(label, expansions, settings),))


def paired(x: Arm, y: Arm) -> PairedDifference:
    return paired_difference(x, y, 16, 0, len(x.runs[0].outcomes))


def test_a_proof_found_after_the_budget_counts_unsolved() -> None:
    assert [found.proved for found in within_budget(run("r", [3, 40, None]), 16).outcomes] == [True, False, False]


def test_a_proof_cut_by_the_budget_ends_on_the_expansions() -> None:
    assert within_budget(run("r", [40]), 16).outcomes[0].end == SearchEnd.EXPANSIONS


def test_a_proof_within_the_budget_keeps_its_expansions() -> None:
    assert within_budget(run("r", [16]), 16).outcomes[0].expansions_to_proof == 16


def test_the_paired_difference_is_the_difference_of_solved_shares() -> None:
    found = paired(arm("x", [1] * 8 + [None] * 2), arm("y", [1] * 5 + [None] * 5))
    assert found.overall.difference == pytest.approx(0.3)


def test_the_difference_counts_the_other_runs_late_proofs_as_unsolved() -> None:
    found = paired(arm("x", [1] * 10), arm("y", [1] * 5 + [30] * 5))
    assert found.overall.difference == pytest.approx(0.5)


def test_runs_of_other_search_settings_compare() -> None:
    other = dataclasses.replace(SETTINGS, max_wall_seconds=14400.0, run_config_sha256="other")
    assert paired(arm("x", [1] * 10, other), arm("y", [1] * 10)).overall.difference == 0.0


def test_runs_of_another_probe_set_are_refused() -> None:
    other = dataclasses.replace(SETTINGS, probe_set_sha256="another probe")
    with pytest.raises(ValueError, match="probe set"):
        paired(arm("x", [1] * 10, other), arm("y", [1] * 10))


def test_runs_missing_statements_are_refused() -> None:
    with pytest.raises(ValueError, match="not all 10"):
        paired_difference(arm("x", [1] * 9), arm("y", [1] * 10), 16, 0, 10)


def test_an_arm_solving_far_more_passes_the_gate() -> None:
    assert passes_gate(paired(arm("x", [1] * 200), arm("y", [1] * 100 + [None] * 100)))


def test_equal_arms_do_not_pass_the_gate() -> None:
    expansions: list[int | None] = [1, None] * 100
    assert not passes_gate(paired(arm("x", expansions), arm("y", list(reversed(expansions)))))


def test_the_difference_is_given_per_band() -> None:
    found = paired(arm("x", [1] * 10), arm("y", [1] * 10))
    assert [stratum for stratum, _ in found.strata] == list(STRATA)


def test_the_report_names_the_gates_outcome() -> None:
    gate = paired(arm("x", [1] * 200), arm("y", [1] * 100 + [None] * 100))
    noise = paired(arm("a", [1] * 200), arm("b", [1] * 200))
    assert "PASSES" in gate_report(gate, noise, [])


def test_the_report_shows_the_noise_floor_beside_the_gate() -> None:
    gate = paired(arm("x", [1] * 200), arm("y", [1] * 100 + [None] * 100))
    noise = paired(arm("anchor 1", [1] * 200), arm("anchor 2", [1] * 200))
    assert "## Noise floor: anchor 1 against anchor 2" in gate_report(gate, noise, [])
