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
    UNKNOWN,
    UNPROVED_CLAIM,
    group,
    sample,
)
from test_policy_data import completion, single_tree_data

from lean_search.rl.advantages import CreditMode, group_advantages
from lean_search.rl.policy_data import ExpansionTexts, PolicyDataConfig, PolicySequence
from lean_search.search.graph_labels import EdgeKind
from lean_search.search.tactic_labels import TacticLabel


def test_a_complete_block_closer_on_the_proof_graph_scores_1() -> None:
    assert sample("step", PROOF_GRAPH).verified_progress == 1.0


def test_a_block_closing_its_goal_scores_1() -> None:
    assert sample("done", PROOF_GRAPH, steps=(0,), closed=1).verified_progress == 1.0


@pytest.mark.parametrize(
    "labels",
    [
        (PROOF_GRAPH, FAILING, MASKED),
        (FAILING,),
        (NO_PROGRESS,),
        (REDUNDANT,),
        (UNPROVED_CLAIM,),
        (OFF_GRAPH,),
        (PROOF_GRAPH, OFF_GRAPH),
    ],
    ids=[
        "progress then a failure",
        "a failure",
        "a no-op",
        "a redundant step",
        "an open claim",
        "an explored dead end",
        "progress then a dead end",
    ],
)
def test_a_block_without_verified_progress_scores_0(labels: tuple[TacticLabel, ...]) -> None:
    assert sample("block", *labels).verified_progress == 0.0


def test_a_step_on_the_proof_graph_no_closer_than_the_node_scores_0() -> None:
    assert sample("sideways", PROOF_GRAPH, steps=(NODE_STEPS,)).verified_progress == 0.0


@pytest.mark.parametrize("labels", [(UNKNOWN,), (PROOF_GRAPH, UNKNOWN)], ids=["unknown", "progress then unknown"])
def test_a_complete_block_ending_in_an_unknown_state_has_no_score(labels: tuple[TacticLabel, ...]) -> None:
    assert sample("block", *labels).verified_progress is None


def test_a_block_on_a_backward_edge_scores_0() -> None:
    backward = dataclasses.replace(sample("back", PROOF_GRAPH), kind=EdgeKind.BACK_TO_ANCESTOR)
    assert backward.verified_progress == 0.0


def test_the_advantage_is_r_minus_the_mean_r_of_the_samples_with_an_r() -> None:
    mixed = group(
        sample("step", PROOF_GRAPH, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("error", FAILING, multiplicity=2, edge_id=2),
        sample("unseen", UNKNOWN, edge_id=3),
    )
    values = [advantages.verified_progress for advantages in group_advantages(mixed).samples]
    assert values == pytest.approx([0.75, -0.25, -0.25, None])


def test_a_group_whose_samples_with_an_r_agree_carries_no_signal() -> None:
    agreeing = group(sample("a", FAILING, edge_id=0), sample("b", NO_PROGRESS, edge_id=1), sample("c", UNKNOWN))
    assert not group_advantages(agreeing).has_signal(CreditMode.VERIFIED_PROGRESS)


def test_a_group_with_only_unknown_endings_carries_no_signal() -> None:
    unseen = group(sample("a", UNKNOWN, edge_id=0), sample("b", PROOF_GRAPH, UNKNOWN, edge_id=1))
    assert not group_advantages(unseen).has_signal(CreditMode.VERIFIED_PROGRESS)


def verified_progress_sequences() -> list[PolicySequence]:
    mixed = group(
        sample("step", PROOF_GRAPH, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("unseen", UNKNOWN, edge_id=2),
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "step"), completion(1, "error"), completion(2, "unseen")))]
    return list(single_tree_data([mixed], texts, PolicyDataConfig(CreditMode.VERIFIED_PROGRESS)).sequences)


def test_every_sampled_token_of_a_scored_sample_gets_its_advantage() -> None:
    assert set(verified_progress_sequences()[0].advantages) == {0.5}


def test_a_sample_without_a_score_is_left_out_of_the_policy_data() -> None:
    assert [sequence.edge_id for sequence in verified_progress_sequences()] == [0, 1]


def test_the_phase_counts_the_sequences_left_out_without_a_score() -> None:
    mixed = group(
        sample("step", PROOF_GRAPH, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("unseen", UNKNOWN, edge_id=2),
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "step"), completion(1, "error"), completion(2, "unseen")))]
    metrics = single_tree_data([mixed], texts, PolicyDataConfig(CreditMode.VERIFIED_PROGRESS)).metrics
    assert metrics.unscored_sequences == 1


def test_the_phase_records_the_mean_verified_progress_of_the_samples_with_an_r() -> None:
    mixed = group(sample("step", PROOF_GRAPH, edge_id=0), sample("error", FAILING, edge_id=1), sample("x", UNKNOWN))
    metrics = single_tree_data([mixed], [], PolicyDataConfig(CreditMode.VERIFIED_PROGRESS)).metrics
    assert metrics.mean_verified_progress == pytest.approx(0.5)


def test_the_phase_records_the_share_of_samples_without_a_score() -> None:
    mixed = group(sample("step", PROOF_GRAPH, edge_id=0), sample("error", FAILING, edge_id=1), sample("x", UNKNOWN))
    metrics = single_tree_data([mixed], [], PolicyDataConfig(CreditMode.VERIFIED_PROGRESS)).metrics
    assert metrics.unscored_progress_share == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    "labels",
    [(REDUNDANT, PROOF_GRAPH), (NO_PROGRESS, PROOF_GRAPH), (UNPROVED_CLAIM, PROOF_GRAPH)],
    ids=["a redundant step first", "a no-op first", "an open claim first"],
)
def test_progress_after_a_wasted_tactic_scores_0(labels: tuple[TacticLabel, ...]) -> None:
    assert sample("block", *labels).verified_progress == 0.0


def test_a_block_ending_on_a_claim_it_adds_scores_0() -> None:
    step = sample("have", PROOF_GRAPH)
    claim = dataclasses.replace(step, tactics=(dataclasses.replace(step.tactics[-1], adds_claim=True),))
    assert claim.verified_progress == 0.0


def test_a_wasted_block_ending_in_an_unknown_state_scores_0() -> None:
    assert sample("block", REDUNDANT, UNKNOWN).verified_progress == 0.0


def test_the_mean_verified_progress_covers_groups_without_a_signal_too() -> None:
    mixed = group(sample("step", PROOF_GRAPH, edge_id=0), sample("error", FAILING, edge_id=1), node_id=0)
    agreeing = group(sample("a", FAILING, edge_id=2), sample("b", FAILING, edge_id=3), node_id=1)
    metrics = single_tree_data([mixed, agreeing], [], PolicyDataConfig(CreditMode.VERIFIED_PROGRESS)).metrics
    assert metrics.mean_verified_progress == pytest.approx(0.25)
