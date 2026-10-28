import dataclasses

import pytest
from graph_trees import GraphBuilder

from lean_search.rl.grpo_groups import (
    GroupSample,
    PolicyGroup,
    RewardConfig,
    RewardMode,
    normalized_advantages,
    policy_groups,
)
from lean_search.search import FailureKind, StepSource
from lean_search.search.graph_labels import EdgeKind, label_graph
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)

READOUT = RemainingStepsReadout()
CONFIG = RewardConfig(
    global_weight=4.0,
    lean_error_reward=-1.0,
    heartbeat_timeout_reward=-0.5,
    wall_clock_timeout_reward=-1.0,
    no_progress_reward=-0.1,
    already_seen_reward=0.0,
    shaping_weight=0.1,
    goal_closed_bonus=0.2,
    shorter_proof_bonus=0.0,
)


def groups(config: RewardConfig = CONFIG) -> dict[int, PolicyGroup]:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    sweep_failure = builder.failure(builder.root, text="linarith", source=StepSource.AUTOMATION)
    a = builder.child(builder.root, "⊢ a", value=2.0, text="good")
    builder.failure(builder.root, text="error")
    builder.failure(builder.root, FailureKind.HEARTBEAT_TIMEOUT, text="slow")
    builder.duplicate(builder.root, builder.root, text="no progress")
    dead = builder.child(builder.root, "⊢ dead", value=1.5, text="to dead")
    builder.failure(dead, text="dead error")
    builder.repeat(builder.root, sweep_failure)
    builder.child(builder.root, "⊢ prefix", value=4.0, text="partial", failure_after=1)
    twice = builder.failure(builder.root, text="twice", sample_count=2)
    builder.repeat(builder.root, twice)
    builder.unparsed(builder.root)
    builder.unparsed(builder.root)
    builder.failure(builder.root, FailureKind.UNKNOWN_IDENTIFIER, text="exact mystery")
    expanded = builder.child(builder.root, "⊢ expanded", value=6.0, text="to expanded")
    grandchild = builder.child(expanded, "⊢ grandchild", value=4.0)
    builder.child(grandchild, "⊢ leaf", value=9.0)
    proof = builder.child(a, text="close")
    record = builder.record(proof)
    labels = label_graph(record)
    estimates = recorded_estimates(record, READOUT)
    targets = value_targets(record, labels, estimates, ValueTargetConfig())
    return {group.node_id: group for group in policy_groups(record, labels, estimates, targets, config)}


def sample(text: str, config: RewardConfig = CONFIG, node_id: int = 0) -> GroupSample:
    (match,) = [sample for sample in groups(config)[node_id].samples if sample.text == text]
    return match


def test_proof_graph_child_gets_shaping_plus_beta() -> None:
    assert sample("good").reward == pytest.approx(0.1 * (3 - 2) + 4.0)


def test_lean_error_reward() -> None:
    assert sample("error").reward == -1.0


def test_heartbeat_timeout_reward_is_configurable() -> None:
    assert sample("slow").reward == -0.5


def test_no_progress_on_the_proof_graph_earns_no_global_reward() -> None:
    assert sample("no progress").reward == pytest.approx(-0.1)


def test_dead_end_child_earns_no_global_reward() -> None:
    assert sample("to dead").components.global_value == 0.0


def test_repeat_of_a_failed_sweep_tactic_scores_as_the_failure() -> None:
    assert sample("linarith").reward == -1.0


def test_partial_block_pays_the_error_after_its_prefix() -> None:
    assert sample("partial").reward == pytest.approx(-1.0 + 0.1 * (3 - 4))


def test_partial_block_prefix_reward() -> None:
    assert sample("partial").credit.prefix_reward == pytest.approx(0.1 * (3 - 4))


def test_partial_block_points_at_the_first_failing_tactic() -> None:
    assert sample("partial").credit.first_failing_tactic == 1


def test_identical_texts_merge_and_keep_their_multiplicity() -> None:
    assert sample("twice").multiplicity == 3


def test_group_holds_only_policy_samples() -> None:
    assert groups()[0].sample_count == 14


def test_unparsed_samples_merge_into_one_failed_sample() -> None:
    assert (sample("").multiplicity, sample("").kind, sample("").reward) == (2, EdgeKind.UNPARSED_SAMPLE, -1.0)


def test_unparsed_samples_earn_no_global_reward() -> None:
    assert sample("").components.global_value == 0.0


def test_unknown_identifier_scores_like_a_lean_error() -> None:
    assert (sample("exact mystery").kind, sample("exact mystery").reward) == (EdgeKind.UNKNOWN_IDENTIFIER, -1.0)


def test_partial_block_exposes_its_prefix_components() -> None:
    partial = sample("partial")
    assert partial.credit.prefix_components == dataclasses.replace(partial.components, failure=0.0)


def test_closing_step_earns_the_goal_bonus() -> None:
    builder_groups = groups()
    (closing,) = [group for group in builder_groups.values() if group.goals == ("⊢ a",)]
    assert closing.samples[0].components.goals_closed == pytest.approx(0.2)


def test_proving_expansion_is_incomplete() -> None:
    (closing,) = [group for group in groups().values() if group.goals == ("⊢ a",)]
    assert not closing.complete


def test_expanded_off_graph_child_is_neutral_before_the_gate() -> None:
    assert sample("to expanded").components.global_value == 0.0


def test_expanded_off_graph_child_gets_its_backed_up_value_after_the_gate() -> None:
    config = dataclasses.replace(CONFIG, use_backed_up_values=True)
    assert sample("to expanded", config).components.global_value == pytest.approx(
        READOUT.estimate(4.0).proof_probability
    )


def test_never_expanded_child_is_neutral_after_the_gate() -> None:
    config = dataclasses.replace(CONFIG, use_backed_up_values=True)
    assert sample("partial", config).components.global_value == 0.0


def test_shorter_proofs_earn_a_larger_global_term() -> None:
    config = dataclasses.replace(CONFIG, shorter_proof_bonus=1.0)
    assert sample("good", config).components.global_value == pytest.approx(1.0 + 1.0 / (1 + 1))


@pytest.mark.parametrize(("text", "reward"), [("good", 1.0), ("error", 0.0), ("no progress", 0.0), ("partial", 0.0)])
def test_outcome_only_rewards(text: str, reward: float) -> None:
    assert sample(text, dataclasses.replace(CONFIG, mode=RewardMode.OUTCOME_ONLY)).reward == reward


def test_outcome_only_group_off_the_proof_graph_has_no_spread() -> None:
    config = dataclasses.replace(CONFIG, mode=RewardMode.OUTCOME_ONLY)
    off_graph = [group for group in groups(config).values() if group.goals == ("⊢ expanded",)]
    assert not off_graph[0].has_mixed_rewards


def test_normalized_advantages_have_zero_mean_over_the_samples() -> None:
    group = groups()[0]
    advantages = normalized_advantages(group)
    weighted = sum(advantage * item.multiplicity for advantage, item in zip(advantages, group.samples, strict=True))
    assert weighted == pytest.approx(0.0, abs=1e-9)
