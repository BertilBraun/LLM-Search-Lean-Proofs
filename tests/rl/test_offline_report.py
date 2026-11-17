import pytest

pytest.importorskip("numpy")

from lean_search.rl.arm_comparison import Arm, ArmRun, RunSettings, SearchEnd, StatementOutcome  # noqa: E402
from lean_search.rl.offline_report import (  # noqa: E402
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


def run(name: str, expansions: list[int | None]) -> ArmRun:
    return ArmRun(name, name, SETTINGS, tuple(outcome(index, found) for index, found in enumerate(expansions)))


def arm(label: str, expansions: list[int | None]) -> Arm:
    return Arm(label, (run(label, expansions),))


def test_a_proof_found_after_the_budget_counts_unsolved() -> None:
    assert [found.proved for found in within_budget(run("r", [3, 40, None]), 16).outcomes] == [True, False, False]


def test_a_proof_within_the_budget_keeps_its_expansions() -> None:
    assert within_budget(run("r", [16]), 16).outcomes[0].expansions_to_proof == 16


def test_the_paired_difference_is_the_difference_of_solved_shares() -> None:
    found = paired_difference(arm("x", [1] * 8 + [None] * 2), arm("y", [1] * 5 + [None] * 5), 16, 0)
    assert found.overall.difference == pytest.approx(0.3)


def test_the_difference_counts_the_other_runs_late_proofs_as_unsolved() -> None:
    found = paired_difference(arm("x", [1] * 10), arm("y", [1] * 5 + [30] * 5), 16, 0)
    assert found.overall.difference == pytest.approx(0.5)


def test_an_arm_solving_far_more_passes_the_gate() -> None:
    found = paired_difference(arm("x", [1] * 200), arm("y", [1] * 100 + [None] * 100), 16, 0)
    assert passes_gate(found)


def test_equal_arms_do_not_pass_the_gate() -> None:
    expansions: list[int | None] = [1, None] * 100
    assert not passes_gate(paired_difference(arm("x", expansions), arm("y", list(reversed(expansions))), 16, 0))


def test_the_difference_is_given_per_band() -> None:
    found = paired_difference(arm("x", [1] * 10), arm("y", [1] * 10), 16, 0)
    assert [stratum for stratum, _ in found.strata] == list(STRATA)


def test_the_report_names_the_gates_outcome() -> None:
    gate = paired_difference(arm("x", [1] * 200), arm("y", [1] * 100 + [None] * 100), 16, 0)
    assert "PASSES" in gate_report(gate, [])
