import dataclasses

import pytest

pytest.importorskip("numpy")

from lean_search.rl.expert_iteration_decision import HeldOutRun, RoundEvidence, round_checks  # noqa: E402
from lean_search.rl.health_checks import HeldOutRates  # noqa: E402
from lean_search.rl.loop_config import HealthConfig  # noqa: E402
from lean_search.rl.probe_rating import DifferenceInterval, PairedComparison  # noqa: E402
from lean_search.rl.tree_summary import BlockHabits, SearchHabits  # noqa: E402

SAMPLES = 4096


def paired(difference: float, lower: float) -> PairedComparison:
    interval = DifferenceInterval(500, difference, lower, difference + 0.03)
    return PairedComparison(interval, interval, (), 0, 0, ())


def habits(distinct_blocks_per_expansion: float, explanation_bin: int) -> SearchHabits:
    """100 expansions; every explanation in one 10-character bin."""
    bins = tuple(100 if index == explanation_bin else 0 for index in range(explanation_bin + 1))
    distinct = round(100 * distinct_blocks_per_expansion)
    return SearchHabits(10, 0, 100, distinct, BlockHabits(block_samples=800, explanation_character_bins=bins))


def held_out(valid_rate: float, success: float) -> HeldOutRun:
    return HeldOutRun(HeldOutRates(valid_rate, success), SAMPLES)


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
            dataclasses.replace(PASSING, candidate_held_out=held_out(0.75, 0.45)),
            "held-out valid Lean against the reference",
            id="valid Lean 2 SE below the reference",
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
