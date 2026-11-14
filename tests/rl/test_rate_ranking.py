from collections.abc import Mapping

import pytest

pytest.importorskip("numpy")

from lean_search.rl.arm_comparison import Arm, ArmRun, RunSettings, SearchEnd, StatementOutcome  # noqa: E402
from lean_search.rl.rate_ranking import HeldOutStates, Variant, against_v0, choose_rate  # noqa: E402
from lean_search.rl.single_step import SampleSuccess  # noqa: E402

STATES = [f"state_{index:03d}" for index in range(512)]
GATE = [f"gate_{index:03d}" for index in range(402)]
SETTINGS = RunSettings("gate digest", 16, 7200.0, None, 16, 84, "search digest")


def held_out(label: str, extra_successes: int = 0, changes: Mapping[int, int] | None = None) -> HeldOutStates:
    """Eight samples per state, (index mod 5) of them successful, plus `extra_successes` on every state and
    `changes[index]` on some."""
    changes = changes or {}
    return HeldOutStates(
        label,
        {
            name: SampleSuccess(1, 8, min(8, index % 5 + extra_successes + changes.get(index, 0)), index % 5 + 3)
            for index, name in enumerate(STATES)
        },
    )


def gate(label: str, solved: int, first: int = 0) -> Arm:
    """Statements first .. first + solved - 1 proved."""
    outcomes = tuple(
        StatementOutcome(name, "easy", first <= index < first + solved, 2, SearchEnd.EXPANSIONS, 100)
        for index, name in enumerate(GATE)
    )
    return Arm(label, (ArmRun(f"probe_{label}", label, SETTINGS, outcomes),))


def variant(
    rate: float,
    extra_successes: int = 0,
    gate_solved: int | None = None,
    gate_first: int = 0,
    changes: Mapping[int, int] | None = None,
) -> Variant:
    label = f"A_{rate:g}"
    found = None if gate_solved is None else gate(label, gate_solved, gate_first)
    return Variant(label, rate, held_out(label, extra_successes, changes), found)


def test_a_clear_held_out_winner_is_chosen() -> None:
    choice = choose_rate([variant(2e-5), variant(5e-5, extra_successes=2), variant(1e-4)])
    assert (choice.chosen, choice.reason) == ("A_5e-05", "the held-out states decide")


def test_among_held_out_ties_a_gate_set_leader_apart_from_the_others_wins() -> None:
    choice = choose_rate(
        [variant(2e-5, gate_solved=150), variant(5e-5, gate_solved=170), variant(1e-4, gate_solved=160)]
    )
    assert (choice.chosen, choice.reason) == ("A_5e-05", "tied on the held-out states; the gate set decides")


def test_a_gate_set_lead_within_its_interval_is_a_tie_and_goes_to_the_lower_rate() -> None:
    """1e-4 solves 6 more of the gate set, but 13 statements against 7 apart: within noise."""
    choice = choose_rate([variant(1e-4, gate_solved=166, gate_first=7), variant(5e-5, gate_solved=160)])
    assert (choice.chosen, choice.reason) == (
        "A_5e-05",
        "tied on the held-out states and on the gate set; the lower rate",
    )


def test_held_out_and_gate_ties_go_to_the_lower_rate() -> None:
    choice = choose_rate([variant(1e-4, gate_solved=160), variant(5e-5, gate_solved=160)])
    assert choice.chosen == "A_5e-05"


def test_without_gate_runs_a_held_out_tie_goes_to_the_lower_rate() -> None:
    choice = choose_rate([variant(1e-4), variant(2e-5), variant(5e-5)])
    assert (choice.chosen, len(choice.tied)) == ("A_2e-05", 3)


def test_a_gate_set_contradicting_a_clear_held_out_difference_flags_both_rates_for_a_probe_run() -> None:
    choice = choose_rate([variant(2e-5, gate_solved=220), variant(5e-5, extra_successes=2, gate_solved=150)])
    assert choice.probe_runs == (("A_5e-05", "A_2e-05"),)


def test_a_held_out_lean_within_its_interval_flags_nothing() -> None:
    """2e-5 leans ahead on the held-out states (+1 success on 10 states, -1 on 8) inside its interval; 5e-5 wins the
    gate set clearly."""
    leaning = {index: 1 for index in range(0, 50, 5)} | {index: -1 for index in range(2, 42, 5)}
    choice = choose_rate([variant(2e-5, gate_solved=150, changes=leaning), variant(5e-5, gate_solved=220)])
    assert (choice.chosen, choice.probe_runs) == ("A_5e-05", ())


def test_a_gate_set_agreeing_with_the_held_out_states_flags_nothing() -> None:
    choice = choose_rate([variant(2e-5, gate_solved=150), variant(5e-5, extra_successes=2, gate_solved=220)])
    assert choice.probe_runs == ()


def test_a_held_out_run_missing_states_is_refused() -> None:
    partial = HeldOutStates("A_5e-05", dict(list(held_out("A_5e-05").states.items())[:300]))
    with pytest.raises(ValueError, match="212 missing"):
        against_v0([Variant("A_5e-05", 5e-5, partial)], held_out("v0"), None)


def test_every_variant_is_reported_against_v0_paired_per_state() -> None:
    (report,) = against_v0([variant(5e-5, extra_successes=1)], held_out("v0"), None)
    assert report.success.difference == pytest.approx(1 / 8)


def test_the_gate_set_is_reported_against_v0_when_both_ran_it() -> None:
    (report,) = against_v0([variant(5e-5, gate_solved=201)], held_out("v0"), gate("v0", 161))
    assert report.gate is not None and report.gate.difference == pytest.approx(40 / 402)
