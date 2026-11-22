import pytest
from rl_samples import FAILING, MASKED, NODE_STEPS, PROOF_GRAPH, REDUNDANT, UNKNOWN, group, sample
from test_policy_data import completion, single_tree_data

from lean_search.rl.advantages import CreditMode, group_advantages
from lean_search.rl.policy_data import ExpansionTexts, PolicyDataConfig, PolicySequence
from lean_search.search.tactic_labels import TacticLabel


def test_a_one_step_block_scores_its_share_of_the_remaining_proof() -> None:
    assert sample("step", PROOF_GRAPH).verified_fraction == pytest.approx(1 / NODE_STEPS)


def test_a_two_step_block_scores_twice_a_one_step_one() -> None:
    assert sample("two", PROOF_GRAPH, PROOF_GRAPH).verified_fraction == pytest.approx(2 / NODE_STEPS)


def test_a_block_closing_its_goal_scores_1() -> None:
    assert sample("done", PROOF_GRAPH, steps=(0,), closed=1).verified_fraction == 1.0


@pytest.mark.parametrize(
    "labels", [(FAILING,), (PROOF_GRAPH, FAILING, MASKED), (REDUNDANT, PROOF_GRAPH)], ids=["error", "tail", "waste"]
)
def test_a_block_without_verified_progress_scores_0(labels: tuple[TacticLabel, ...]) -> None:
    assert sample("block", *labels).verified_fraction == 0.0


def test_a_clean_block_ending_in_an_unknown_state_has_no_score() -> None:
    assert sample("unseen", PROOF_GRAPH, UNKNOWN).verified_fraction is None


def test_the_advantage_is_r_minus_the_mean_r_of_the_samples_with_an_r() -> None:
    mixed = group(
        sample("done", PROOF_GRAPH, steps=(0,), closed=1, edge_id=0),
        sample("step", PROOF_GRAPH, edge_id=1),
        sample("error", FAILING, edge_id=2),
        sample("unseen", UNKNOWN, edge_id=3),
    )
    values = [advantages.verified_fraction for advantages in group_advantages(mixed).samples]
    mean = (1 + 1 / NODE_STEPS) / 3
    assert values == pytest.approx([1 - mean, 1 / NODE_STEPS - mean, -mean, None])


def test_a_group_whose_samples_cover_the_same_share_carries_no_signal() -> None:
    same = group(sample("a", PROOF_GRAPH, edge_id=0), sample("b", PROOF_GRAPH, edge_id=1))
    assert not group_advantages(same).has_signal(CreditMode.VERIFIED_FRACTION)


def test_a_longer_correct_block_trains_against_a_shorter_one() -> None:
    lengths = group(sample("one", PROOF_GRAPH, edge_id=0), sample("two", PROOF_GRAPH, PROOF_GRAPH, edge_id=1))
    assert group_advantages(lengths).has_signal(CreditMode.VERIFIED_FRACTION)


def fraction_sequences() -> list[PolicySequence]:
    mixed = group(
        sample("step", PROOF_GRAPH, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("unseen", UNKNOWN, edge_id=2),
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "step"), completion(1, "error"), completion(2, "unseen")))]
    return list(single_tree_data([mixed], texts, PolicyDataConfig(CreditMode.VERIFIED_FRACTION)).sequences)


def test_a_sample_without_a_score_is_left_out_under_fraction_credit() -> None:
    assert [sequence.edge_id for sequence in fraction_sequences()] == [0, 1]


def test_every_sampled_token_of_a_scored_sample_gets_its_fraction_advantage() -> None:
    advantages = fraction_sequences()[0].advantages
    assert advantages == pytest.approx([1 / (2 * NODE_STEPS)] * len(advantages))


def test_the_phase_records_the_mean_verified_fraction() -> None:
    mixed = group(sample("step", PROOF_GRAPH, edge_id=0), sample("error", FAILING, edge_id=1))
    metrics = single_tree_data([mixed], [], PolicyDataConfig(CreditMode.VERIFIED_FRACTION)).metrics
    assert metrics.mean_verified_fraction == pytest.approx(1 / (2 * NODE_STEPS))


def test_the_score_is_the_last_states_gain_not_the_block_length() -> None:
    assert sample("detour", PROOF_GRAPH, PROOF_GRAPH, steps=(2, 3)).verified_fraction == pytest.approx(1 / NODE_STEPS)


def test_a_sample_counts_its_multiplicity_in_the_fraction_baseline() -> None:
    weighted = group(sample("step", PROOF_GRAPH, multiplicity=3, edge_id=0), sample("error", FAILING, edge_id=1))
    baseline = 3 * (1 / NODE_STEPS) / 4
    assert group_advantages(weighted).samples[1].verified_fraction == pytest.approx(-baseline)
