import dataclasses

import pytest
from rl_samples import FAILING, MASKED, NODE_STEPS, PROOF_GRAPH, REWARDS, UNKNOWN, UNPROVED_CLAIM, group

from lean_search.rl.advantages import group_advantages
from lean_search.rl.grpo_groups import GroupSample, RewardConfig, judged_in_block, tactic_reward
from lean_search.search.graph_labels import EdgeKind
from lean_search.search.tactic_labels import TacticOutcome

STEP = 0.2
COST = 0.1
ON_GRAPH = 0.85
FAILURE = -0.15
UNPAID = dataclasses.replace(REWARDS, claims_earn_progress=False)
# Arms A and D since 2026-11-18.
ARMS = dataclasses.replace(UNPAID, unproved_claim_cost=0.3)


def step(remaining: int) -> TacticOutcome:
    return TacticOutcome(PROOF_GRAPH, remaining_steps=remaining)


def claim(remaining: int, left_open: bool = False) -> TacticOutcome:
    """A claim on the proof graph: proved later in its block, or (`left_open`) by the tree."""
    return TacticOutcome(PROOF_GRAPH, remaining_steps=remaining, adds_claim=True, leaves_claim_open=left_open)


INVENTED = TacticOutcome(UNPROVED_CLAIM, leaves_claim_open=True, adds_claim=True)
FAILED = TacticOutcome(FAILING)
NOT_RUN = TacticOutcome(MASKED)


def block(config: RewardConfig, *outcomes: TacticOutcome, text: str = "s") -> GroupSample:
    rewards = [tactic_reward(outcome, config, NODE_STEPS) for outcome in outcomes]
    return GroupSample(text, (0,), 1, EdgeKind.NEW_STATE, judged_in_block(rewards, config))


def score(config: RewardConfig, *outcomes: TacticOutcome) -> float | None:
    return block(config, *outcomes).score


def test_by_default_a_claim_on_the_proof_graph_earns_its_step() -> None:
    assert score(REWARDS, claim(NODE_STEPS - 1, left_open=True)) == pytest.approx(ON_GRAPH + STEP)


def test_a_bare_claim_the_tree_proves_later_earns_no_progress() -> None:
    assert score(UNPAID, claim(NODE_STEPS - 1, left_open=True)) == pytest.approx(ON_GRAPH)


def test_proving_a_claim_in_its_block_beats_leaving_it_to_the_tree_by_the_proofs_step() -> None:
    inline = score(UNPAID, claim(NODE_STEPS - 1), step(NODE_STEPS - 2))
    bare = score(UNPAID, claim(NODE_STEPS - 1, left_open=True))
    assert inline is not None and bare is not None and inline - bare == pytest.approx(STEP)


def test_a_claim_with_its_proof_scores_like_one_direct_step() -> None:
    assert score(UNPAID, claim(NODE_STEPS - 1), step(NODE_STEPS - 2)) == pytest.approx(
        score(UNPAID, step(NODE_STEPS - 1))
    )


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ((step(3), claim(2), step(1)), ON_GRAPH + 2 * STEP),
        ((claim(3), step(2), claim(1), step(0)), ON_GRAPH + 2 * STEP),
        ((claim(3, left_open=True), FAILED, NOT_RUN), ON_GRAPH - COST),
        ((step(3), claim(2, left_open=True)), ON_GRAPH + STEP),
        ((step(3), step(2)), ON_GRAPH + 2 * STEP),
    ],
    ids=[
        "a claim between two steps",
        "two claims with their proofs",
        "a claim the tree proves, a failing attempt in the block",
        "a step, then a claim the tree proves",
        "two steps without a claim",
    ],
)
def test_without_claim_progress_a_block_scores_its_proving_steps(
    outcomes: tuple[TacticOutcome, ...], expected: float
) -> None:
    assert score(UNPAID, *outcomes) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("outcomes", "default", "arms"),
    [
        ((INVENTED,), FAILURE - COST, FAILURE - 0.3),
        ((INVENTED, FAILED, NOT_RUN), FAILURE - COST, FAILURE - 0.3),
        ((step(3), INVENTED), ON_GRAPH + STEP - 2 * COST, ON_GRAPH + STEP - COST - 0.3),
    ],
    ids=["left open", "a failed attempt at it", "after a step"],
)
def test_an_invented_claim_left_open_costs_the_set_claim_cost(
    outcomes: tuple[TacticOutcome, ...], default: float, arms: float
) -> None:
    assert (score(REWARDS, *outcomes), score(ARMS, *outcomes)) == (pytest.approx(default), pytest.approx(arms))


def test_a_claim_detour_keeps_its_loss() -> None:
    detour = claim(NODE_STEPS + 2, left_open=True)
    assert score(UNPAID, detour) == pytest.approx(score(REWARDS, detour))


def test_the_tactic_after_a_claim_gains_its_own_step_not_the_claims() -> None:
    tactics = block(UNPAID, step(3), claim(2), step(1)).tactics
    assert [tactic.gain.total for tactic in tactics[1:] if tactic.gain is not None] == pytest.approx([0.0, STEP])


def test_a_claim_anchoring_its_block_gets_less_first_tactic_credit_than_a_direct_step() -> None:
    advantages = group_advantages(
        group(block(UNPAID, claim(3), step(2), text="claim"), block(UNPAID, step(3), step(2), text="direct"))
    )
    claim_first, direct_first = (sample.tactics[0] for sample in advantages.samples)
    assert claim_first is not None and direct_first is not None and claim_first < direct_first


def test_an_invented_claim_left_open_scores_below_a_failure_in_its_group() -> None:
    advantages = group_advantages(
        group(block(ARMS, INVENTED, text="claim"), block(ARMS, FAILED, text="error"), block(ARMS, step(3), text="step"))
    )
    invented, failure, _ = (sample.sequence for sample in advantages.samples)
    assert invented is not None and failure is not None and invented < failure < 0


def test_unset_claim_cost_is_c() -> None:
    assert score(REWARDS, INVENTED) == pytest.approx(
        score(dataclasses.replace(REWARDS, unproved_claim_cost=COST), INVENTED)
    )


UNKNOWN_STATE = TacticOutcome(UNKNOWN)
# Block prefixes under the arms' reward, claims on the proof graph and invented ones among them.
PREFIXES = [
    (step(3),),
    (claim(3),),
    (claim(3), step(2)),
    (step(3), claim(2, left_open=True)),
    (UNKNOWN_STATE,),
    (INVENTED,),
    (step(3), INVENTED),
]
PREFIX_IDS = [
    "a step",
    "a claim",
    "a claim and its proof",
    "a step and a claim the tree proves",
    "unknown",
    "an invented claim",
    "a step and an invented claim",
]


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_under_the_arms_reward_a_valid_continuation_scores_at_least_an_error_there(
    prefix: tuple[TacticOutcome, ...],
) -> None:
    assert score(ARMS, *prefix, UNKNOWN_STATE) >= score(ARMS, *prefix, FAILED, NOT_RUN) - 1e-12


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_under_the_arms_reward_appending_an_error_never_gains(prefix: tuple[TacticOutcome, ...]) -> None:
    assert score(ARMS, *prefix, FAILED, NOT_RUN) <= score(ARMS, *prefix) + 1e-12


@pytest.mark.parametrize("prefix", PREFIXES, ids=PREFIX_IDS)
def test_under_the_arms_reward_appending_an_invented_claim_never_gains(prefix: tuple[TacticOutcome, ...]) -> None:
    assert score(ARMS, *prefix, INVENTED) <= score(ARMS, *prefix) + 1e-12


ON_GRAPH_PREFIXES = PREFIXES[:4]


@pytest.mark.parametrize("prefix", ON_GRAPH_PREFIXES, ids=PREFIX_IDS[:4])
def test_under_the_arms_reward_appending_a_claim_on_the_proof_graph_never_gains(
    prefix: tuple[TacticOutcome, ...],
) -> None:
    last = min(outcome.remaining_steps for outcome in prefix if outcome.remaining_steps is not None)
    assert score(ARMS, *prefix, claim(last - 1, left_open=True)) == pytest.approx(score(ARMS, *prefix))


def test_a_claim_reaching_the_proof_graph_after_an_unknown_state_keeps_the_graph_but_not_its_step() -> None:
    assert score(UNPAID, UNKNOWN_STATE, claim(NODE_STEPS - 2, left_open=True)) == pytest.approx(ON_GRAPH + STEP)


def test_a_claim_moving_two_steps_closer_by_a_shorter_route_earns_the_second() -> None:
    assert score(UNPAID, claim(NODE_STEPS - 2, left_open=True)) == pytest.approx(ON_GRAPH + STEP)


def test_a_claim_on_a_detour_after_a_detour_never_gains_below_zero() -> None:
    tactics = block(UNPAID, step(NODE_STEPS + 5), claim(NODE_STEPS + 4)).tactics
    assert tactics[1].gain is not None and tactics[1].gain.total >= 0.0
