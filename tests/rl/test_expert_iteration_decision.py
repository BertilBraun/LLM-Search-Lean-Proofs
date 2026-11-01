import dataclasses

import pytest

pytest.importorskip("numpy")

from lean_search.rl.expert_iteration_decision import (  # noqa: E402
    HeldOutRun,
    RoundEvidence,
    StateValidity,
    against_verdict,
    held_out_checks,
    round_checks,
)
from lean_search.rl.health_checks import HeldOutRates  # noqa: E402
from lean_search.rl.loop_config import HealthConfig  # noqa: E402
from lean_search.rl.probe_rating import DifferenceInterval, PairedComparison  # noqa: E402
from lean_search.rl.tree_summary import BlockHabits, SearchHabits  # noqa: E402

STATES = 512


def paired(difference: float, lower: float) -> PairedComparison:
    interval = DifferenceInterval(500, difference, lower, difference + 0.03)
    return PairedComparison(interval, interval, (), 0, 0, ())


def habits(distinct_blocks_per_expansion: float, explanation_bin: int, expansions: int = 100) -> SearchHabits:
    """Every explanation in one 10-character bin."""
    bins = tuple(100 if index == explanation_bin else 0 for index in range(explanation_bin + 1))
    distinct = round(expansions * distinct_blocks_per_expansion)
    return SearchHabits(10, 0, expansions, distinct, BlockHabits(block_samples=800, explanation_character_bins=bins))


def held_out(valid_rate: float, success: float, changes: tuple[int, ...] = (0,)) -> HeldOutRun:
    """512 states of 8 samples, 6 of them valid plus `changes` in turn per state."""
    states = tuple(StateValidity(f"s{index}", 8, 6 + changes[index % len(changes)]) for index in range(STATES))
    return HeldOutRun(HeldOutRates(valid_rate, success), states)


PASSING = RoundEvidence(
    version_zero=held_out(0.8, 0.4),
    reference_held_out=held_out(0.8, 0.42),
    candidate_held_out=held_out(0.8, 0.45),
    paired=paired(0.02, 0.0),
    reference_habits=habits(3.0, 15),
    candidate_habits=habits(3.0, 15),
)


def failed_checks(evidence: RoundEvidence) -> set[str]:
    return {check.name for check in round_checks(evidence, HealthConfig()) if not check.passed}


def test_a_round_passing_every_check_is_kept() -> None:
    assert failed_checks(PASSING) == set()


@pytest.mark.parametrize(
    ("evidence", "failed"),
    [
        pytest.param(
            dataclasses.replace(PASSING, candidate_held_out=held_out(0.8, 0.3)),
            "held-out success against version 0",
            id="success",
        ),
        pytest.param(
            dataclasses.replace(PASSING, candidate_held_out=held_out(0.8, 0.45, (-1, 0, 0, 0))),
            "held-out valid Lean against the reference, paired per state",
            id="a valid sample lost on every fourth state",
        ),
        pytest.param(
            dataclasses.replace(PASSING, paired=paired(0.01, -0.03)), "probe paired solve difference", id="lower bound"
        ),
        pytest.param(
            dataclasses.replace(PASSING, paired=paired(-0.005, 0.01)), "probe paired solve difference", id="difference"
        ),
        pytest.param(
            dataclasses.replace(PASSING, candidate_habits=habits(2.0, 15)),
            "distinct blocks per expansion",
            id="diversity",
        ),
        pytest.param(
            dataclasses.replace(PASSING, candidate_habits=habits(3.0, 9)),
            "median explanation characters",
            id="explanations",
        ),
    ],
)
def test_a_round_failing_one_check_fails_only_that_check(evidence: RoundEvidence, failed: str) -> None:
    assert failed_checks(evidence) == {failed}


def test_per_state_noise_around_the_references_validity_passes_the_paired_check() -> None:
    candidate = held_out(0.8, 0.45, (1, -1))
    checks = held_out_checks(PASSING.version_zero, PASSING.reference_held_out, candidate, HealthConfig())
    assert all(check.passed for check in checks)


def test_the_diversity_checks_fail_without_reference_trees() -> None:
    evidence = dataclasses.replace(PASSING, reference_habits=habits(0.0, 0, expansions=0))
    assert failed_checks(evidence) == {"distinct blocks per expansion", "median explanation characters"}


@pytest.mark.parametrize(
    ("beats", "rule"),
    [
        pytest.param(True, "keep 28 if it passes its own compare;", id="beats"),
        pytest.param(False, "keep 28 only if it passes its own compare and 27 fails its own;", id="does not beat"),
    ],
)
def test_the_head_to_head_verdict_states_the_winner_rule(beats: bool, rule: str) -> None:
    assert rule in against_verdict(28, 27, beats, 26)
