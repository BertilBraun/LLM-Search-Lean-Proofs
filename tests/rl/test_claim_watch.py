from pathlib import Path

import pytest

from lean_search.monitoring.families import HealthMeasurements
from lean_search.rl.claim_watch import (
    AdvantageSum,
    Opening,
    PhaseWatch,
    TreeWatch,
    WatchKey,
    opening_of,
    proof_band,
    version_zero_held_out,
    watch_lines,
)
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.health_checks import HeldOutRates
from lean_search.search.records import to_json
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome

OPEN = TacticOutcome(TacticLabel.UNPROVED_CLAIM, leaves_claim_open=True, adds_claim=True)
PROVED_IN_BLOCK = TacticOutcome(TacticLabel.PROOF_GRAPH, remaining_steps=2, adds_claim=True)
FAILED = TacticOutcome(TacticLabel.FAILING)
BARE = "have h : 0 ≤ x ^ 2"


@pytest.mark.parametrize(
    ("text", "outcomes", "expected"),
    [
        ("have h : 0 ≤ x ^ 2 := by\n  positivity", (PROVED_IN_BLOCK,), Opening.PROOF_HAVE),
        ("obtain ⟨y, hy⟩ := h", (FAILED,), Opening.OBTAIN),
        ("suffices h : x = 1 by simp [h]", (FAILED,), Opening.SUFFICES),
        ("replace h : x = 1", (FAILED,), Opening.OTHER_CLAIM),
        ("nlinarith [sq_nonneg x]", (FAILED,), Opening.LINARITH),
        ("simp", (FAILED,), Opening.OTHER),
        (f"{BARE}\npositivity", (PROVED_IN_BLOCK, PROVED_IN_BLOCK), Opening.BARE_CLOSED_IN_BLOCK),
        (BARE, (OPEN,), Opening.BARE_OPEN_ALONE),
        (f"{BARE}\nnlinarith", (OPEN, FAILED), Opening.BARE_OPEN_FAILED_ATTEMPT),
        (BARE, (FAILED,), Opening.BARE_FAILING),
    ],
    ids=[
        "inline proof",
        "obtain",
        "suffices",
        "replace",
        "nlinarith",
        "other",
        "bare, proved in the block",
        "bare, left open",
        "bare, a failing attempt after",
        "bare, failing itself",
    ],
)
def test_an_opening_is_classified_by_its_first_tactic_and_its_claim(
    text: str, outcomes: tuple[TacticOutcome, ...], expected: Opening
) -> None:
    assert opening_of(text, outcomes) == expected


@pytest.mark.parametrize(
    ("difficulty", "band"),
    [(None, "unknown"), (4.99, "0-499"), (5.0, "500-999"), (29.99, "2000-2999"), (45.0, "4500+")],
)
def test_a_statements_band_is_its_probe_band_of_proof_characters(difficulty: float | None, band: str) -> None:
    assert proof_band(difficulty) == band


BAND = "0-499"


def trees(closed_off_graph: int, failed_attempts: int, decomposition: float, direct: float) -> TreeWatch:
    """100 samples: the two growing subclasses, the rest direct openings; on-graph advantages per sample."""
    samples = {
        WatchKey(Opening.BARE_CLOSED_IN_BLOCK, False, BAND): closed_off_graph,
        WatchKey(Opening.BARE_OPEN_FAILED_ATTEMPT, False, BAND): failed_attempts,
        WatchKey(Opening.OTHER, True, BAND): 100 - closed_off_graph - failed_attempts,
    }
    advantages = {
        WatchKey(Opening.BARE_CLOSED_IN_BLOCK, True, BAND): AdvantageSum(10, 10 * decomposition),
        WatchKey(Opening.OTHER, True, BAND): AdvantageSum(20, 20 * direct),
    }
    return TreeWatch(5, samples, advantages)


def health(bare_have_share: float) -> HealthMeasurements:
    return HealthMeasurements(bare_have_share=bare_have_share, mean_explanation_tokens=100.0)


REFERENCE = PhaseWatch(1, trees(4, 3, 0.9, 0.3), health(0.20))


def lines(current: PhaseWatch) -> list[str]:
    return watch_lines(current, REFERENCE, HeldOutRates(0.57, 0.32))


def test_a_quiet_phase_meets_no_stop_rule() -> None:
    assert not any("STOP-RULE" in line for line in lines(PhaseWatch(2, trees(5, 4, 0.8, 0.3), health(0.22))))


@pytest.mark.parametrize(
    ("current", "flagged"),
    [
        (PhaseWatch(4, trees(5, 4, 0.8, 0.3), health(0.26)), "bare `have` openings"),
        (PhaseWatch(4, trees(7, 4, 0.8, 0.3), health(0.22)), "proved in its block, off the proof graph"),
        (PhaseWatch(4, trees(5, 5, 0.8, 0.3), health(0.22)), "a failing attempt after"),
    ],
    ids=["bare haves up 6 points", "self-proving off the graph 1.75x", "failing attempts 1.67x"],
)
def test_a_rise_past_the_suggested_stop_rule_is_flagged_on_its_line(current: PhaseWatch, flagged: str) -> None:
    assert [line for line in lines(current) if "STOP-RULE" in line and flagged in line]


def test_the_on_graph_premium_is_the_ratio_of_decompositions_to_direct_openings() -> None:
    (premium,) = [line for line in lines(PhaseWatch(2, trees(4, 3, 0.9, 0.3), health(0.2))) if "per sample" in line]
    assert "+0.900, direct openings +0.300 (3.00x)" in premium


def test_version_zeros_held_out_rates_come_from_its_last_held_out_evaluation(tmp_path: Path) -> None:
    def summary(version: int, valid: int) -> str:
        return to_json(
            EvaluationSummary(
                EvaluationKind.HELD_OUT_STATES,
                f"v{version}",
                version,
                0,
                10,
                4,
                (),
                1,
                10,
                0,
                0.0,
                0.0,
                "",
                "",
                10,
                valid,
            )
        )

    path = tmp_path / "evaluations.jsonl"
    path.write_text("\n".join([summary(0, 5), summary(1, 9), summary(0, 6)]) + "\n", encoding="utf-8")
    assert version_zero_held_out(path) == HeldOutRates(0.6, 0.4)
