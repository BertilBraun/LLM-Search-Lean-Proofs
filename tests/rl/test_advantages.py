import pytest
from rl_samples import FAILING, MASKED, NO_PROGRESS, OFF_GRAPH, PROOF_GRAPH, REDUNDANT, UNKNOWN, group, sample

from lean_search.rl.advantages import CreditMode, group_advantages, local_share_of_advantages

PROOF_REWARD = 0.85
OFF_GRAPH_REWARD = 0.0
NO_PROGRESS_REWARD = -0.15
FAILING_REWARD = -0.15


def example() -> list[float | None]:
    """The advantages of every tactic of the DESIGN's example at the root of xpeeq7, in order."""
    advantages = group_advantages(
        group(
            sample("A", PROOF_GRAPH, PROOF_GRAPH, PROOF_GRAPH, closed=1),
            sample("B", PROOF_GRAPH, FAILING, MASKED),
            sample("C", UNKNOWN, FAILING, MASKED),
            sample("D", REDUNDANT),
        )
    )
    return [value for item in advantages.samples for value in item.tactics]


def test_design_example_signs() -> None:
    signs = ["+" if value > 0 else "-" if value < 0 else "0" for value in example() if value is not None]
    assert signs == ["+", "+", "+", "+", "-", "-", "-"]


def test_design_example_leaves_the_unknown_and_masked_tactics_untrained() -> None:
    assert [index for index, value in enumerate(example()) if value is None] == [5, 6, 8]


@pytest.mark.parametrize(
    ("labels", "score"),
    [
        ((PROOF_GRAPH,), PROOF_REWARD),
        ((OFF_GRAPH,), OFF_GRAPH_REWARD),
        ((NO_PROGRESS,), NO_PROGRESS_REWARD),
        ((REDUNDANT,), NO_PROGRESS_REWARD),
        ((FAILING,), FAILING_REWARD),
        ((PROOF_GRAPH, FAILING, MASKED), (PROOF_REWARD + FAILING_REWARD) / 2),
        ((UNKNOWN, PROOF_GRAPH), PROOF_REWARD),
    ],
    ids=["proof graph", "off graph", "no progress", "redundant", "failing", "partial", "unknown left out"],
)
def test_sample_score_is_the_mean_of_its_known_tactics(labels: tuple, score: float) -> None:
    assert sample("s", *labels).score == pytest.approx(score)


@pytest.mark.parametrize("no_op", [NO_PROGRESS, REDUNDANT])
def test_a_no_op_does_not_beat_a_failure(no_op: object) -> None:
    advantages = group_advantages(group(sample("a", FAILING, multiplicity=6), sample("b", no_op)))
    assert advantages.samples[1].sequence == pytest.approx(0.0)


def test_closing_a_goal_earns_the_bonus() -> None:
    assert sample("s", PROOF_GRAPH, closed=2).score == pytest.approx(PROOF_REWARD + 0.15 * 0.2)


def test_sample_with_only_unknown_tactics_has_no_score() -> None:
    assert sample("s", UNKNOWN, UNKNOWN).score is None


def test_baseline_is_the_multiplicity_weighted_mean_score() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, multiplicity=3), sample("b", FAILING)))
    assert advantages.baseline == pytest.approx((3 * PROOF_REWARD + FAILING_REWARD) / 4)


def test_unknown_sample_stays_out_of_the_baseline() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", FAILING), sample("c", UNKNOWN)))
    assert advantages.baseline == pytest.approx((PROOF_REWARD + FAILING_REWARD) / 2)


def test_unknown_sample_gets_no_sequence_advantage() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", FAILING), sample("c", UNKNOWN)))
    assert advantages.samples[2].sequence is None


def test_tactic_advantage_is_its_reward_minus_the_baseline() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, FAILING, MASKED), sample("b", PROOF_GRAPH)))
    baseline = ((PROOF_REWARD + FAILING_REWARD) / 2 + PROOF_REWARD) / 2
    assert advantages.samples[0].tactics[1] == pytest.approx(FAILING_REWARD - baseline)


@pytest.mark.parametrize(
    ("labels", "has_closing"),
    [((PROOF_GRAPH, PROOF_GRAPH), True), ((PROOF_GRAPH, FAILING, MASKED), False), ((PROOF_GRAPH, UNKNOWN), False)],
)
def test_closing_tokens_take_the_last_tactic_of_a_complete_block(labels: tuple, has_closing: bool) -> None:
    advantages = group_advantages(group(sample("a", *labels), sample("b", FAILING)))
    assert (advantages.samples[0].closing is not None) is has_closing


@pytest.mark.parametrize(
    ("second", "signal"),
    [(sample("b", PROOF_GRAPH), False), (sample("b", FAILING), True), (sample("b", UNKNOWN), False)],
    ids=["identical", "different", "unknown"],
)
def test_group_signal(second: object, signal: bool) -> None:
    assert group_advantages(group(sample("a", PROOF_GRAPH), second)).has_signal(CreditMode.PER_TACTIC) is signal


def test_equal_scores_with_different_tactics_carry_a_per_tactic_signal_only() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, FAILING), sample("b", FAILING, PROOF_GRAPH)))
    assert (advantages.has_signal(CreditMode.PER_TACTIC), advantages.has_signal(CreditMode.SEQUENCE)) == (True, False)


@pytest.mark.parametrize(
    ("first", "second", "share"),
    [
        (sample("a", PROOF_GRAPH, closed=1), sample("b", PROOF_GRAPH), 1.0),
        (sample("a", PROOF_GRAPH), sample("b", OFF_GRAPH), 0.0),
    ],
    ids=["local only", "global only"],
)
def test_local_share_of_advantages(first: object, second: object, share: float) -> None:
    assert local_share_of_advantages([group_advantages(group(first, second))]) == pytest.approx(share)
