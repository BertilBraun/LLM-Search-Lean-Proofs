import dataclasses

import pytest
from graph_trees import GraphBuilder

from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.value.bins import DEAD_BIN, STEP_BIN_COUNT, Readout
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    SourceShares,
    TargetSource,
    ValueEstimate,
    ValueTarget,
    ValueTargetConfig,
    balanced_weights,
    bin_estimate,
    bin_target,
    capped_targets,
    recorded_estimates,
    value_targets,
)

READOUT = RemainingStepsReadout(dead_steps=16.0, fewest_steps=1.0)
DEFAULT_CONFIG = ValueTargetConfig()


def solved_tree() -> tuple[TreeRecord, dict[str, int]]:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    a = builder.child(builder.root, "⊢ a", value=2.0)
    off = builder.child(builder.root, "⊢ off", value=5.0)
    x = builder.child(off, "⊢ x", value=4.0)
    dead = builder.child(off, "⊢ dead", value=2.0)
    builder.failure(dead)
    y = builder.child(x, "⊢ y", value=7.0)
    proof = builder.child(a)
    record = builder.record(proof)
    return record, {"r": 0, "a": a.node_id, "off": off.node_id, "x": x.node_id, "dead": dead.node_id, "y": y.node_id}


def labelled_targets(record: TreeRecord, config: ValueTargetConfig = DEFAULT_CONFIG) -> dict[int, ValueTarget]:
    targets = value_targets(record, label_graph(record), recorded_estimates(record, READOUT), config)
    return {target.node_id: target for target in targets}


def targets_by_node(config: ValueTargetConfig = DEFAULT_CONFIG) -> dict[int, ValueTarget]:
    return labelled_targets(solved_tree()[0], config)


def node_id(name: str) -> int:
    return solved_tree()[1][name]


@pytest.mark.parametrize(("name", "steps"), [("r", 2), ("a", 1)])
def test_proof_graph_target_has_exact_steps(name: str, steps: int) -> None:
    assert targets_by_node()[node_id(name)].exact_steps == steps


def test_proof_graph_target_mixes_its_concrete_one_with_its_value_part() -> None:
    assert targets_by_node()[node_id("a")].proof_probability == pytest.approx(0.85 + 0.15 * 14 / 15)


def test_value_part_is_the_mean_over_expanded_descendants() -> None:
    assert targets_by_node()[node_id("off")].value_part.proof_probability == pytest.approx((0.8 + 14 / 15) / 2)


def test_value_part_steps_are_the_mean_of_distance_plus_h() -> None:
    assert targets_by_node()[node_id("off")].value_part.remaining_steps == pytest.approx(((1 + 4) + (1 + 2)) / 2)


def test_off_graph_target_is_mu_times_its_value_part() -> None:
    assert targets_by_node()[node_id("off")].proof_probability == pytest.approx(0.15 * (0.8 + 14 / 15) / 2)


def test_dead_end_is_an_ordinary_off_graph_target() -> None:
    assert targets_by_node()[node_id("dead")].source == TargetSource.OFF_GRAPH


def test_state_without_expanded_descendants_uses_its_own_estimate() -> None:
    assert targets_by_node()[node_id("x")].value_part == ValueEstimate(0.8, 4.0)


def test_never_expanded_state_gets_no_target() -> None:
    assert node_id("y") not in targets_by_node()


@pytest.mark.parametrize(("name", "weight"), [("off", 0.5 * 3 / (3 + 4)), ("x", 0.5 * 1 / (1 + 4))])
def test_off_graph_weight_grows_with_expanded_nodes(name: str, weight: float) -> None:
    assert targets_by_node()[node_id(name)].weight == pytest.approx(weight)


@pytest.mark.parametrize(("name", "probability"), [("a", 1.0), ("off", 0.0)])
def test_zero_value_share_keeps_the_concrete_label(name: str, probability: float) -> None:
    assert targets_by_node(ValueTargetConfig(value_share=0.0))[node_id(name)].proof_probability == probability


def test_low_temperature_slides_the_value_part_toward_the_best_descendant() -> None:
    target = targets_by_node(ValueTargetConfig(temperature=0.01))[node_id("off")]
    assert target.value_part.proof_probability == pytest.approx(14 / 15, abs=1e-6)


def test_unsolved_tree_keeps_its_expanded_states_as_off_graph_targets() -> None:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    child = builder.child(builder.root, "⊢ child", value=4.0)
    builder.failure(child)
    assert [target.source for target in labelled_targets(builder.record()).values()] == [TargetSource.OFF_GRAPH] * 2


def test_value_part_distance_counts_tactics() -> None:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    child = builder.child(builder.root, "⊢ child", value=4.0, tactics=3)
    builder.failure(child)
    assert labelled_targets(builder.record())[0].value_part.remaining_steps == pytest.approx(3 + 4)


@pytest.mark.parametrize(("steps", "probability"), [(1.0, 1.0), (16.0, 0.0), (8.5, 0.5), (20.0, 0.0), (0.5, 1.0)])
def test_remaining_steps_readout(steps: float, probability: float) -> None:
    assert READOUT.estimate(steps).proof_probability == pytest.approx(probability)


def test_bin_estimate_reads_one_minus_dead() -> None:
    probabilities = (0.75, 0, 0, 0, 0, 0, 0, 0, 0.25)
    assert bin_estimate(probabilities, Readout()) == ValueEstimate(0.75, 1.0)


def test_verified_proof_has_an_exact_estimate() -> None:
    record, _ = solved_tree()
    proof_id = len(record.nodes) - 1
    assert recorded_estimates(record, READOUT)[proof_id] == ValueEstimate(1.0, 0.0)


def target(
    source: TargetSource, exact_steps: int | None, value_part: ValueEstimate | None = None, node: int = 0
) -> ValueTarget:
    return ValueTarget("t", node, ("⊢ g",), source, exact_steps, value_part, 0.15, 1.0, 0)


@pytest.mark.parametrize(
    ("value_target", "expected"),
    [
        (target(TargetSource.PROOF_GRAPH, 2), {1: 1.0}),
        (target(TargetSource.OFF_GRAPH, None), {DEAD_BIN: 1.0}),
        (
            target(TargetSource.PROOF_GRAPH, 2, ValueEstimate(0.4, 11.0)),
            {1: 0.85, 7: 0.15 * 0.4, DEAD_BIN: 0.15 * 0.6},
        ),
        (target(TargetSource.OFF_GRAPH, None, ValueEstimate(0.4, 3.0)), {2: 0.15 * 0.4, DEAD_BIN: 0.85 + 0.15 * 0.6}),
    ],
)
def test_bin_target_without_smoothing(value_target: ValueTarget, expected: dict[int, float]) -> None:
    distribution = bin_target(value_target, sigma=0.0)
    assert distribution == pytest.approx([expected.get(index, 0.0) for index in range(len(distribution))])


@pytest.mark.parametrize("source", [TargetSource.PROOF_GRAPH, TargetSource.OFF_GRAPH])
def test_bin_target_alive_mass_is_the_mixed_proof_probability(source: TargetSource) -> None:
    value_target = target(source, 3 if source == TargetSource.PROOF_GRAPH else None, ValueEstimate(0.4, 3.3))
    assert sum(bin_target(value_target, sigma=0.5)[:STEP_BIN_COUNT]) == pytest.approx(value_target.proof_probability)


def test_smoothed_bin_target_sums_to_one() -> None:
    assert sum(bin_target(target(TargetSource.OFF_GRAPH, None, ValueEstimate(0.4, 3.3)), sigma=0.5)) == pytest.approx(
        1.0
    )


def test_cap_keeps_every_proof_graph_target() -> None:
    targets = [target(TargetSource.OFF_GRAPH, None, node=node) for node in range(10)]
    targets.append(target(TargetSource.PROOF_GRAPH, 1, node=10))
    kept = capped_targets(targets, 3)
    assert sum(kept_target.source == TargetSource.PROOF_GRAPH for kept_target in kept) == 1


def test_cap_limits_the_targets_per_tree() -> None:
    targets = [target(TargetSource.OFF_GRAPH, None, node=node) for node in range(10)]
    assert len(capped_targets(targets, 3)) == 3


def test_balanced_weights_give_each_source_its_share() -> None:
    targets = [target(TargetSource.OFF_GRAPH, None, node=node) for node in range(9)]
    targets.append(target(TargetSource.PROOF_GRAPH, 1, node=9))
    balanced = balanced_weights(targets, SourceShares(proof_graph=0.5, off_graph=0.5))
    proof_weight = sum(item.weight for item in balanced if item.source == TargetSource.PROOF_GRAPH)
    assert proof_weight == pytest.approx(sum(item.weight for item in balanced) / 2)


def test_balanced_weights_keep_the_total() -> None:
    targets = [target(TargetSource.OFF_GRAPH, None, node=node) for node in range(9)]
    targets.append(dataclasses.replace(target(TargetSource.PROOF_GRAPH, 1, node=9), weight=2.0))
    balanced = balanced_weights(targets, SourceShares())
    assert sum(item.weight for item in balanced) == pytest.approx(11.0)
