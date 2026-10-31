"""The orderings the reward must keep so that no valid or attempted step scores below a failure or a bare claim."""

import pytest
from rl_samples import (
    FAILING,
    MASKED,
    NO_PROGRESS,
    OFF_GRAPH,
    PROOF_GRAPH,
    REDUNDANT,
    REWARDS,
    UNKNOWN,
    UNPROVED_CLAIM,
    group,
    sample,
)

from lean_search.rl.advantages import group_advantages
from lean_search.search.tactic_labels import TacticLabel

COST = REWARDS.wasted_tactic_cost


def score(*labels: TacticLabel) -> float:
    value = sample("s", *labels).score
    assert value is not None
    return value


def test_a_proof_graph_state_beats_an_explored_off_graph_one() -> None:
    assert score(PROOF_GRAPH) > score(OFF_GRAPH)


def test_an_explored_off_graph_state_scores_like_an_unknown_one() -> None:
    assert score(OFF_GRAPH) == pytest.approx(score(UNKNOWN))


def test_an_unknown_state_scores_half_the_failure_local() -> None:
    assert score(UNKNOWN) == pytest.approx(REWARDS.local_share * REWARDS.unknown_local)


@pytest.mark.parametrize("wasted", [FAILING, NO_PROGRESS, REDUNDANT])
def test_an_unknown_state_beats_a_wasted_first_tactic(wasted: TacticLabel) -> None:
    assert score(UNKNOWN) > score(wasted)


def test_a_real_attempt_succeeding_seven_percent_of_the_time_beats_any_useless_valid_step() -> None:
    attempt = 0.07 * score(PROOF_GRAPH) + 0.93 * score(FAILING)
    assert attempt > max(score(OFF_GRAPH), score(UNKNOWN))


PREFIXES = [
    (PROOF_GRAPH,),
    (PROOF_GRAPH, PROOF_GRAPH),
    (OFF_GRAPH,),
    (UNKNOWN,),
    (PROOF_GRAPH, UNKNOWN),
    (PROOF_GRAPH, OFF_GRAPH),
    (UNPROVED_CLAIM,),
    (PROOF_GRAPH, UNPROVED_CLAIM),
    (UNPROVED_CLAIM, UNPROVED_CLAIM),
]
PREFIX_IDS = [
    "proof graph",
    "two proof-graph steps",
    "off graph",
    "unknown",
    "proof graph then unknown",
    "proof graph then off graph",
    "open claim",
    "proof graph then open claim",
    "two open claims",
]


@pytest.mark.parametrize("valid", [UNKNOWN, OFF_GRAPH])
@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_a_valid_continuation_scores_at_least_an_error_there(
    prefix: tuple[TacticLabel, ...], valid: TacticLabel
) -> None:
    assert score(*prefix, valid) >= score(*prefix, FAILING, MASKED) - 1e-12


@pytest.mark.parametrize("valid", [UNKNOWN, OFF_GRAPH])
@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_a_valid_continuation_gets_at_least_an_errors_advantage(
    prefix: tuple[TacticLabel, ...], valid: TacticLabel
) -> None:
    advantages = group_advantages(group(sample("a", *prefix, valid), sample("b", *prefix, FAILING, MASKED)))
    position = len(prefix)
    continuation, error = (item.tactics[position] for item in advantages.samples)
    assert continuation is not None and error is not None and continuation >= error - 1e-12


@pytest.mark.parametrize("wasted", [NO_PROGRESS, REDUNDANT])
@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_a_no_op_continuation_scores_at_least_an_error_there(
    prefix: tuple[TacticLabel, ...], wasted: TacticLabel
) -> None:
    assert score(*prefix, wasted) >= score(*prefix, FAILING, MASKED) - 1e-12


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_appending_an_error_never_gains(prefix: tuple[TacticLabel, ...]) -> None:
    assert score(*prefix, FAILING, MASKED) <= score(*prefix) + 1e-12


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_appending_an_invented_claim_never_gains(prefix: tuple[TacticLabel, ...]) -> None:
    assert score(*prefix, UNPROVED_CLAIM) <= score(*prefix) + 1e-12


def test_stepping_off_the_found_route_after_progress_keeps_the_progress() -> None:
    assert score(PROOF_GRAPH, PROOF_GRAPH, UNKNOWN) > score(PROOF_GRAPH)


def test_continuing_off_the_found_route_after_progress_gets_the_better_explanation_advantage() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", PROOF_GRAPH, PROOF_GRAPH, UNKNOWN)))
    stop, go_on = (item.sequence for item in advantages.samples)
    assert stop is not None and go_on is not None and go_on > stop


def test_appending_an_error_after_an_unknown_continuation_costs_c() -> None:
    assert score(PROOF_GRAPH, UNKNOWN, FAILING, MASKED) == pytest.approx(score(PROOF_GRAPH, UNKNOWN) - COST)


def test_an_explored_off_graph_state_ending_a_block_after_progress_costs_c() -> None:
    assert score(PROOF_GRAPH, OFF_GRAPH) == pytest.approx(score(PROOF_GRAPH) - COST)


def test_an_explored_off_graph_state_on_the_way_to_the_proof_graph_costs_nothing() -> None:
    assert sample("s", PROOF_GRAPH, OFF_GRAPH, PROOF_GRAPH).tactics[1].gain.total == pytest.approx(0.0)


BARE_CLAIM = (UNPROVED_CLAIM,)
# Review U's block shapes with the claim the tree never proves at the anchor.
OPEN_CLAIM_SHAPES = [
    BARE_CLAIM,
    (UNPROVED_CLAIM, FAILING, MASKED),
    (UNPROVED_CLAIM, UNKNOWN),
    (UNPROVED_CLAIM, UNKNOWN, UNKNOWN),
    (UNPROVED_CLAIM, OFF_GRAPH),
    (UNPROVED_CLAIM, NO_PROGRESS),
    (UNPROVED_CLAIM, REDUNDANT),
    (UNPROVED_CLAIM, NO_PROGRESS, FAILING, MASKED),
    (UNPROVED_CLAIM, UNKNOWN, FAILING, MASKED),
    (UNPROVED_CLAIM, UNPROVED_CLAIM),
    (UNPROVED_CLAIM, UNPROVED_CLAIM, FAILING, MASKED),
]
OPEN_CLAIM_IDS = [
    "bare",
    "failing proof",
    "valid partial step",
    "two valid steps",
    "off graph step",
    "no-op",
    "redundant",
    "no-op, failing",
    "valid step, failing",
    "two claims",
    "two claims, failing",
]


def test_a_bare_claim_scores_a_failure_and_c() -> None:
    assert score(*BARE_CLAIM) == pytest.approx(REWARDS.local_share * REWARDS.unproved_claim_local - COST)


@pytest.mark.parametrize("shape", OPEN_CLAIM_SHAPES, ids=OPEN_CLAIM_IDS)
def test_a_block_leaving_an_invented_claim_open_scores_like_the_bare_claim(shape: tuple[TacticLabel, ...]) -> None:
    assert score(*shape) == pytest.approx(score(*BARE_CLAIM))


@pytest.mark.parametrize("shape", OPEN_CLAIM_SHAPES, ids=OPEN_CLAIM_IDS)
def test_after_progress_a_block_leaving_an_invented_claim_open_costs_two_errors(
    shape: tuple[TacticLabel, ...],
) -> None:
    assert score(PROOF_GRAPH, *shape) == pytest.approx(score(PROOF_GRAPH) - 2 * COST)


@pytest.mark.parametrize("shape", OPEN_CLAIM_SHAPES[1:], ids=OPEN_CLAIM_IDS[1:])
def test_the_tactics_after_an_open_claim_get_no_advantage(shape: tuple[TacticLabel, ...]) -> None:
    advantages = group_advantages(group(sample("a", *shape), sample("b", PROOF_GRAPH)))
    assert all(value in (0.0, None) for value in advantages.samples[0].tactics[1:])


def test_the_open_claim_carries_the_penalty_on_its_own_tokens() -> None:
    advantages = group_advantages(group(sample("a", UNPROVED_CLAIM, FAILING, MASKED), sample("b", UNKNOWN)))
    assert advantages.samples[0].tactics[0] == pytest.approx(score(*BARE_CLAIM) - advantages.first_tactic_baseline)


def test_a_failed_attempt_at_a_provable_claim_beats_one_at_an_invented_claim() -> None:
    assert score(UNKNOWN, FAILING, MASKED) > score(UNPROVED_CLAIM, FAILING, MASKED)


def test_a_failed_attempt_at_a_provable_claim_gets_the_better_explanation_advantage() -> None:
    advantages = group_advantages(
        group(sample("a", UNKNOWN, FAILING, MASKED), sample("b", UNPROVED_CLAIM, FAILING, MASKED), sample("c", FAILING))
    )
    provable, invented, _ = (item.sequence for item in advantages.samples)
    assert provable is not None and invented is not None and provable > invented


def test_a_provable_bare_claim_beats_an_invented_one() -> None:
    assert score(UNKNOWN) > score(*BARE_CLAIM)


def test_a_claim_proved_in_its_block_beats_a_failed_attempt_at_it() -> None:
    assert score(UNKNOWN, UNKNOWN) > score(UNPROVED_CLAIM, FAILING, MASKED)


def test_an_open_invented_claim_scores_below_any_error() -> None:
    assert score(*BARE_CLAIM) < score(FAILING)
