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


PREFIXES = [(PROOF_GRAPH,), (PROOF_GRAPH, PROOF_GRAPH), (OFF_GRAPH,), (UNKNOWN,), (PROOF_GRAPH, UNKNOWN)]
PREFIX_IDS = ["proof graph", "two proof-graph steps", "off graph", "unknown", "proof graph then unknown"]


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_a_valid_unknown_continuation_scores_at_least_an_error_there(prefix: tuple[TacticLabel, ...]) -> None:
    assert score(*prefix, UNKNOWN) >= score(*prefix, FAILING, MASKED)


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_a_valid_unknown_continuation_gets_at_least_an_errors_advantage(prefix: tuple[TacticLabel, ...]) -> None:
    advantages = group_advantages(group(sample("a", *prefix, UNKNOWN), sample("b", *prefix, FAILING, MASKED)))
    position = len(prefix)
    continuation, error = (item.tactics[position] for item in advantages.samples)
    assert continuation is not None and error is not None and continuation >= error


def test_stepping_off_the_found_route_after_progress_keeps_the_progress() -> None:
    assert score(PROOF_GRAPH, PROOF_GRAPH, UNKNOWN) > score(PROOF_GRAPH)


def test_continuing_off_the_found_route_after_progress_gets_the_better_explanation_advantage() -> None:
    advantages = group_advantages(group(sample("a", PROOF_GRAPH), sample("b", PROOF_GRAPH, PROOF_GRAPH, UNKNOWN)))
    stop, go_on = (item.sequence for item in advantages.samples)
    assert stop is not None and go_on is not None and go_on > stop


def test_appending_an_error_after_an_unknown_continuation_costs_c() -> None:
    assert score(PROOF_GRAPH, UNKNOWN, FAILING, MASKED) == pytest.approx(
        score(PROOF_GRAPH, UNKNOWN) - REWARDS.wasted_tactic_cost
    )


# A claim proved in its block: its opener's state and the state after the proof are unknown.
PROVED_CLAIM = (UNKNOWN, UNKNOWN)
FAILED_ATTEMPT = (UNPROVED_CLAIM, FAILING, MASKED)
BARE_CLAIM = (UNPROVED_CLAIM,)


def test_a_proved_claim_beats_a_failed_attempt_at_it() -> None:
    assert score(*PROVED_CLAIM) > score(*FAILED_ATTEMPT)


def test_a_failed_attempt_at_a_claim_beats_the_bare_claim() -> None:
    assert score(*FAILED_ATTEMPT) > score(*BARE_CLAIM)


def test_a_failed_attempt_at_a_claim_scores_like_a_failing_tactic() -> None:
    assert score(*FAILED_ATTEMPT) == pytest.approx(score(FAILING))


def test_a_failed_multi_tactic_attempt_at_a_claim_scores_like_a_failing_tactic() -> None:
    assert score(UNPROVED_CLAIM, UNKNOWN, FAILING, MASKED) == pytest.approx(score(FAILING))


def test_after_progress_a_failed_attempt_at_a_claim_costs_what_an_error_costs() -> None:
    assert score(PROOF_GRAPH, *FAILED_ATTEMPT) == pytest.approx(score(PROOF_GRAPH, FAILING, MASKED))


def test_after_progress_a_failed_attempt_at_a_claim_beats_the_bare_claim() -> None:
    assert score(PROOF_GRAPH, *FAILED_ATTEMPT) > score(PROOF_GRAPH, *BARE_CLAIM)


def test_a_bare_claim_scores_its_penalty_and_the_closing_cost() -> None:
    assert score(*BARE_CLAIM) == pytest.approx(
        REWARDS.local_share * REWARDS.unproved_claim_local - REWARDS.wasted_tactic_cost
    )


def test_valid_steps_on_an_open_claim_take_the_claim_penalty_once() -> None:
    assert score(UNPROVED_CLAIM, UNKNOWN, UNKNOWN) == pytest.approx(score(*BARE_CLAIM))


def test_a_second_open_claim_costs_c() -> None:
    assert score(UNPROVED_CLAIM, UNPROVED_CLAIM) == pytest.approx(score(*BARE_CLAIM) - REWARDS.wasted_tactic_cost)
