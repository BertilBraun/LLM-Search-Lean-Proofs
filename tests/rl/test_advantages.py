import dataclasses

import pytest
from rl_samples import (
    FAILING,
    MASKED,
    NO_PROGRESS,
    NODE_STEPS,
    OFF_GRAPH,
    PROOF_GRAPH,
    REDUNDANT,
    REWARDS,
    UNKNOWN,
    group,
    sample,
)

from lean_search.rl.advantages import CreditMode, group_advantages, local_share_of_advantages
from lean_search.rl.grpo_groups import tactic_reward
from lean_search.search.tactic_labels import TacticOutcome

STEP = 0.2
COST = 0.1
ON_GRAPH_REWARD = 0.85
ONE_STEP_REWARD = ON_GRAPH_REWARD + STEP
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
        ((PROOF_GRAPH,), ONE_STEP_REWARD),
        ((OFF_GRAPH,), OFF_GRAPH_REWARD),
        ((NO_PROGRESS,), NO_PROGRESS_REWARD),
        ((REDUNDANT,), NO_PROGRESS_REWARD),
        ((FAILING,), FAILING_REWARD),
        ((PROOF_GRAPH, PROOF_GRAPH), ONE_STEP_REWARD + STEP),
        ((PROOF_GRAPH, FAILING, MASKED), ONE_STEP_REWARD - COST),
        ((PROOF_GRAPH, NO_PROGRESS, PROOF_GRAPH), ONE_STEP_REWARD + STEP - COST),
        ((PROOF_GRAPH, UNKNOWN), ONE_STEP_REWARD),
        ((UNKNOWN, PROOF_GRAPH), ONE_STEP_REWARD),
        ((NO_PROGRESS, PROOF_GRAPH), ONE_STEP_REWARD - COST),
    ],
    ids=[
        "proof graph",
        "off graph",
        "no progress",
        "redundant",
        "failing",
        "two steps",
        "partial",
        "wasted tactic between",
        "unknown last state",
        "unknown first state",
        "no-op first",
    ],
)
def test_sample_score_is_the_final_known_state_minus_the_wasted_tactics(labels: tuple, score: float) -> None:
    assert sample("s", *labels).score == pytest.approx(score)


@pytest.mark.parametrize(("value_share", "floor"), [(0.0, 0.0), (0.15, 0.85 * 0.15)], ids=["before gate", "after"])
def test_proof_graph_detour_never_scores_below_the_best_off_graph_state(value_share: float, floor: float) -> None:
    config = dataclasses.replace(REWARDS, value_share=value_share)
    detour = TacticOutcome(PROOF_GRAPH, remaining_steps=NODE_STEPS + 10)
    parts = tactic_reward(detour, config, NODE_STEPS).parts
    assert parts is not None and parts.total == pytest.approx(floor)


@pytest.mark.parametrize("no_op", [NO_PROGRESS, REDUNDANT])
def test_a_no_op_does_not_beat_a_failure(no_op: object) -> None:
    advantages = group_advantages(group(sample("a", FAILING, multiplicity=6), sample("b", no_op)))
    assert advantages.samples[1].sequence == pytest.approx(0.0)


def test_closing_a_goal_earns_the_bonus() -> None:
    assert sample("s", PROOF_GRAPH, closed=2).score == pytest.approx(ONE_STEP_REWARD + 0.15 * 0.2)


@pytest.mark.parametrize("labels", [(UNKNOWN, UNKNOWN), (UNKNOWN, FAILING, MASKED)], ids=["unknown", "then failing"])
def test_sample_without_a_known_state_or_first_failure_has_no_score(labels: tuple) -> None:
    assert sample("s", *labels).score is None


def test_baseline_is_the_multiplicity_weighted_mean_score() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, multiplicity=3), sample("b", FAILING)))
    assert advantages.baseline == pytest.approx((3 * ONE_STEP_REWARD + FAILING_REWARD) / 4)


def test_unknown_sample_stays_out_of_the_baseline() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", FAILING), sample("c", UNKNOWN)))
    assert advantages.baseline == pytest.approx((ONE_STEP_REWARD + FAILING_REWARD) / 2)


def test_unknown_sample_gets_no_sequence_advantage() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", FAILING), sample("c", UNKNOWN)))
    assert advantages.samples[2].sequence is None


def test_first_tactic_baseline_is_the_multiplicity_weighted_mean_first_state_reward() -> None:
    advantages = group_advantages(
        group(sample("a", PROOF_GRAPH, PROOF_GRAPH, multiplicity=3), sample("b", FAILING), sample("c", UNKNOWN))
    )
    assert advantages.first_tactic_baseline == pytest.approx((3 * ONE_STEP_REWARD + FAILING_REWARD) / 4)


@pytest.mark.parametrize(
    ("first", "reward"), [(PROOF_GRAPH, ONE_STEP_REWARD), (FAILING, FAILING_REWARD)], ids=["proof graph", "failing"]
)
def test_first_tactic_advantage_is_its_reward_minus_the_first_tactic_baseline(first: object, reward: float) -> None:
    advantages = group_advantages(group(sample("a", first), sample("b", PROOF_GRAPH, PROOF_GRAPH)))
    first_tactic_baseline = (reward + ONE_STEP_REWARD) / 2
    assert advantages.samples[0].tactics[0] == pytest.approx(reward - first_tactic_baseline)


@pytest.mark.parametrize(("proofs", "failures"), [(6, 2), (1, 7), (7, 1)])
def test_correct_first_tactic_shared_by_every_proof_is_never_negative(proofs: int, failures: int) -> None:
    proof = sample("proof", PROOF_GRAPH, PROOF_GRAPH, PROOF_GRAPH, PROOF_GRAPH, closed=1, multiplicity=proofs)
    advantages = group_advantages(group(proof, sample("error", FAILING, multiplicity=failures)))
    assert advantages.samples[0].tactics[0] >= 0


@pytest.mark.parametrize(
    "labels",
    [
        (PROOF_GRAPH, PROOF_GRAPH, PROOF_GRAPH),
        (PROOF_GRAPH, FAILING, MASKED),
        (PROOF_GRAPH, OFF_GRAPH),
        (NO_PROGRESS, PROOF_GRAPH, PROOF_GRAPH),
        (UNKNOWN, NO_PROGRESS, PROOF_GRAPH),
        (NO_PROGRESS, FAILING, MASKED),
    ],
    ids=["proof", "partial", "leaves the graph", "no-op first", "unknown first", "no-op then failing"],
)
def test_tactic_advantages_add_up_to_score_minus_the_first_tactic_baseline(labels: tuple) -> None:
    trained = sample("a", *labels)
    advantages = group_advantages(group(trained, sample("b", PROOF_GRAPH), sample("c", FAILING)))
    total = sum(value for value in advantages.samples[0].tactics if value is not None)
    assert total == pytest.approx(trained.score - advantages.first_tactic_baseline)


@pytest.mark.parametrize("no_op", [NO_PROGRESS, REDUNDANT])
def test_no_op_first_tactic_before_progress_costs_its_tokens_only(no_op: object) -> None:
    advantages = group_advantages(group(sample("a", no_op, PROOF_GRAPH), sample("b", FAILING)))
    assert advantages.samples[0].tactics[0] == pytest.approx(-COST)


@pytest.mark.parametrize(("steps", "gained"), [((3, 2), 1), ((3, 1), 2), ((3, 3), 0)])
def test_later_proof_graph_tactic_gains_progress_per_step(steps: tuple[int, int], gained: int) -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, PROOF_GRAPH, steps=steps), sample("b", FAILING)))
    assert advantages.samples[0].tactics[1] == pytest.approx(STEP * gained)


def test_later_tactic_closing_a_goal_also_earns_the_bonus() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, PROOF_GRAPH, closed=1), sample("b", FAILING)))
    assert advantages.samples[0].tactics[1] == pytest.approx(STEP + 0.15 * 0.1)


@pytest.mark.parametrize("wasted", [FAILING, NO_PROGRESS, REDUNDANT])
def test_wasted_later_tactic_costs_its_tokens_only(wasted: object) -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, wasted), sample("b", FAILING)))
    assert advantages.samples[0].tactics[1] == pytest.approx(-COST)


def test_wasted_later_tactic_after_an_unknown_state_costs_its_tokens_only() -> None:
    advantages = group_advantages(group(sample("a", UNKNOWN, FAILING, MASKED), sample("b", PROOF_GRAPH)))
    assert advantages.samples[0].tactics[1] == pytest.approx(-COST)


def test_later_tactic_leaving_the_proof_graph_loses_the_state_it_left() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, OFF_GRAPH), sample("b", FAILING)))
    assert advantages.samples[0].tactics[1] == pytest.approx(OFF_GRAPH_REWARD - ONE_STEP_REWARD)


def test_tactic_after_an_unknown_state_is_judged_against_the_last_known_one() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH, UNKNOWN, PROOF_GRAPH), sample("b", FAILING)))
    assert advantages.samples[0].tactics[2] == pytest.approx(STEP)


def test_tactic_without_a_known_earlier_state_is_judged_like_the_first() -> None:
    advantages = group_advantages(group(sample("a", UNKNOWN, PROOF_GRAPH), sample("b", FAILING)))
    first_tactic_baseline = (ONE_STEP_REWARD + FAILING_REWARD) / 2
    assert advantages.samples[0].tactics[1] == pytest.approx(ONE_STEP_REWARD - first_tactic_baseline)


def test_continuing_correctly_beats_stopping_in_the_explanation() -> None:
    advantages = group_advantages(group(sample("stop", PROOF_GRAPH), sample("continue", PROOF_GRAPH, PROOF_GRAPH)))
    stop, go_on = (sample_advantages.sequence for sample_advantages in advantages.samples)
    assert go_on > stop


@pytest.mark.parametrize(
    ("labels", "closing"),
    [((PROOF_GRAPH, PROOF_GRAPH), 0.0), ((PROOF_GRAPH, UNKNOWN), 0.0), ((PROOF_GRAPH, FAILING, MASKED), None)],
    ids=["complete", "unknown last state", "failed"],
)
def test_closing_tokens_get_zero_after_a_complete_block(labels: tuple, closing: float | None) -> None:
    advantages = group_advantages(group(sample("a", *labels), sample("b", FAILING)))
    assert advantages.samples[0].closing == closing


@pytest.mark.parametrize(
    ("second", "signal"),
    [(sample("b", PROOF_GRAPH), False), (sample("b", FAILING), True), (sample("b", UNKNOWN), False)],
    ids=["identical", "different", "unknown"],
)
def test_group_signal(second: object, signal: bool) -> None:
    assert group_advantages(group(sample("a", PROOF_GRAPH), second)).has_signal(CreditMode.PER_TACTIC) is signal


def test_equal_scores_with_different_tactics_carry_a_per_tactic_signal_only() -> None:
    advantages = group_advantages(
        group(sample("a", PROOF_GRAPH, PROOF_GRAPH, steps=(3, 2)), sample("b", PROOF_GRAPH, steps=(2,)))
    )
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
