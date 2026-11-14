import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.rl.arm_comparison import Arm, ArmRun, RunSettings, SearchEnd, StatementOutcome  # noqa: E402
from lean_search.rl.rate_ranking import HeldOutStates, Variant, against_v0, choose_rate  # noqa: E402
from lean_search.rl.single_step import SampleSuccess  # noqa: E402

STATES = [f"state_{index:03d}" for index in range(512)]
GATE = [f"gate_{index:03d}" for index in range(402)]
SETTINGS = RunSettings("gate digest", 16, 7200.0, "search digest")


def held_out(label: str, extra_successes: int = 0) -> HeldOutStates:
    """Eight samples per state, (index mod 5) of them successful, plus `extra_successes` on every state."""
    return HeldOutStates(
        label,
        {
            name: SampleSuccess(1, 8, min(8, index % 5 + extra_successes), min(8, index % 5 + 3))
            for index, name in enumerate(STATES)
        },
    )


def gate(label: str, solved: int) -> Arm:
    outcomes = tuple(
        StatementOutcome(name, "easy", index < solved, 2 if index < solved else None, SearchEnd.EXPANSIONS, 100)
        for index, name in enumerate(GATE)
    )
    return Arm(label, (ArmRun(f"probe_{label}", label, SETTINGS, outcomes),))


def variant(rate: float, extra_successes: int = 0, gate_solved: int | None = None) -> Variant:
    label = f"A_{rate:g}"
    return Variant(
        label, rate, held_out(label, extra_successes), None if gate_solved is None else gate(label, gate_solved)
    )


def test_a_clear_held_out_winner_is_chosen() -> None:
    choice = choose_rate([variant(2e-5), variant(5e-5, extra_successes=2), variant(1e-4)])
    assert (choice.chosen, choice.reason) == ("A_5e-05", "the held-out states decide")


def test_among_held_out_ties_the_better_gate_estimate_wins() -> None:
    choice = choose_rate(
        [variant(2e-5, gate_solved=150), variant(5e-5, gate_solved=170), variant(1e-4, gate_solved=160)]
    )
    assert choice.chosen == "A_5e-05"


def test_held_out_and_gate_ties_go_to_the_lower_rate() -> None:
    choice = choose_rate([variant(1e-4, gate_solved=160), variant(5e-5, gate_solved=160)])
    assert choice.chosen == "A_5e-05"


def test_without_gate_runs_a_held_out_tie_goes_to_the_lower_rate() -> None:
    choice = choose_rate([variant(1e-4), variant(2e-5), variant(5e-5)])
    assert (choice.chosen, len(choice.tied)) == ("A_2e-05", 3)


def test_a_gate_set_contradicting_the_held_out_states_flags_both_rates_for_a_probe_run() -> None:
    choice = choose_rate([variant(2e-5, gate_solved=220), variant(5e-5, extra_successes=2, gate_solved=150)])
    assert choice.probe_runs == (("A_5e-05", "A_2e-05"),)


def test_a_gate_set_agreeing_with_the_held_out_states_flags_nothing() -> None:
    choice = choose_rate([variant(2e-5, gate_solved=150), variant(5e-5, extra_successes=2, gate_solved=220)])
    assert choice.probe_runs == ()


def test_every_variant_is_reported_against_v0_paired_per_state() -> None:
    (report,) = against_v0([variant(5e-5, extra_successes=1)], held_out("v0"), None)
    assert report.success.difference == pytest.approx(1 / 8)


def test_the_gate_set_is_reported_against_v0_when_both_ran_it() -> None:
    (report,) = against_v0([variant(5e-5, gate_solved=201)], held_out("v0"), gate("v0", 161))
    assert report.gate is not None and report.gate.difference == pytest.approx(40 / 402)


def test_the_gate_evaluation_is_the_probe_evaluation_on_the_gate_set_in_its_own_output() -> None:
    configs = Path(__file__).resolve().parents[2] / "experiments/configs/grpo/followup"
    gate_config, probe = (
        tomllib.loads((configs / name).read_text(encoding="utf-8"))
        for name in ("gate_evaluation.toml", "probe_evaluation.toml")
    )
    assert {**gate_config, "probe_set": probe["probe_set"], "output": probe["output"]} == probe
