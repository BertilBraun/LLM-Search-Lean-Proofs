import dataclasses

import pytest
from graph_trees import GraphBuilder

from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.value.bins import DEAD_BIN, Readout
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


def targets_by_node(config: ValueTargetConfig = DEFAULT_CONFIG) -> dict[int, ValueTarget]:
    record, _ = solved_tree()
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, READOUT), READOUT, config)
    return {target.node_id: target for target in targets}


def node_id(name: str) -> int:
    return solved_tree()[1][name]


@pytest.mark.parametrize(("name", "steps"), [("r", 2.0), ("a", 1.0)])
def test_proof_graph_target_has_exact_steps(name: str, steps: float) -> None:
    assert targets_by_node()[node_id(name)].remaining_steps == steps


def test_proof_graph_target_is_certain() -> None:
    assert targets_by_node()[node_id("a")].proof_probability == 1.0


def test_dead_end_target_is_zero() -> None:
    assert targets_by_node()[node_id("dead")].proof_probability == 0.0


def test_dead_end_target_has_no_steps() -> None:
    assert targets_by_node()[node_id("dead")].source == TargetSource.DEAD_END


def test_averaged_proof_probability_is_the_mean_over_expanded_descendants() -> None:
    assert targets_by_node()[node_id("off")].proof_probability == pytest.approx((0.8 + 0.0) / 2)


def test_averaged_steps_are_the_mean_of_distance_plus_h() -> None:
    assert targets_by_node()[node_id("off")].remaining_steps == pytest.approx(((1 + 4) + (1 + 16)) / 2)


def test_averaged_weight_grows_with_expanded_descendants() -> None:
    assert targets_by_node()[node_id("off")].weight == pytest.approx(0.5 * 2 / (2 + 4))


@pytest.mark.parametrize("name", ["x", "y"])
def test_states_without_expanded_descendants_get_no_target(name: str) -> None:
    assert node_id(name) not in targets_by_node()


def test_dead_descendants_use_their_recorded_estimate_without_anchoring() -> None:
    target = targets_by_node(ValueTargetConfig(anchor_dead_descendants=False))[node_id("off")]
    assert target.proof_probability == pytest.approx((0.8 + 14 / 15) / 2)


def test_low_temperature_slides_the_average_toward_the_best_descendant() -> None:
    target = targets_by_node(ValueTargetConfig(temperature=0.01))[node_id("off")]
    assert target.proof_probability == pytest.approx(0.8, abs=1e-6)


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


def target(source: TargetSource, probability: float, steps: float | None, node: int = 0) -> ValueTarget:
    return ValueTarget("t", node, ("⊢ g",), source, probability, steps, 1.0, 0)


@pytest.mark.parametrize(
    ("value_target", "expected"),
    [
        (target(TargetSource.PROOF_GRAPH, 1.0, 2.0), {1: 1.0}),
        (target(TargetSource.DEAD_END, 0.0, None), {DEAD_BIN: 1.0}),
        (target(TargetSource.AVERAGED, 0.4, 11.0), {7: 0.4, DEAD_BIN: 0.6}),
    ],
)
def test_bin_target_without_smoothing(value_target: ValueTarget, expected: dict[int, float]) -> None:
    distribution = bin_target(value_target, sigma=0.0)
    assert distribution == pytest.approx([expected.get(index, 0.0) for index in range(len(distribution))])


def test_smoothed_bin_target_sums_to_one() -> None:
    assert sum(bin_target(target(TargetSource.AVERAGED, 0.4, 3.3), sigma=0.5)) == pytest.approx(1.0)


def test_cap_keeps_every_proof_graph_target() -> None:
    targets = [target(TargetSource.DEAD_END, 0.0, None, node) for node in range(10)]
    targets.append(target(TargetSource.PROOF_GRAPH, 1.0, 1.0, 10))
    kept = capped_targets(targets, 3)
    assert sum(kept_target.source == TargetSource.PROOF_GRAPH for kept_target in kept) == 1


def test_cap_limits_the_targets_per_tree() -> None:
    targets = [target(TargetSource.DEAD_END, 0.0, None, node) for node in range(10)]
    assert len(capped_targets(targets, 3)) == 3


def test_balanced_weights_give_each_source_its_share() -> None:
    targets = [target(TargetSource.DEAD_END, 0.0, None, node) for node in range(9)]
    targets.append(target(TargetSource.PROOF_GRAPH, 1.0, 1.0, 9))
    balanced = balanced_weights(targets, SourceShares(proof_graph=0.5, dead_end=0.5, averaged=0.0))
    proof_weight = sum(item.weight for item in balanced if item.source == TargetSource.PROOF_GRAPH)
    assert proof_weight == pytest.approx(sum(item.weight for item in balanced) / 2)


def test_balanced_weights_keep_the_total() -> None:
    targets = [target(TargetSource.DEAD_END, 0.0, None, node) for node in range(9)]
    targets.append(dataclasses.replace(target(TargetSource.PROOF_GRAPH, 1.0, 1.0, 9), weight=2.0))
    balanced = balanced_weights(targets, SourceShares())
    assert sum(item.weight for item in balanced) == pytest.approx(11.0)
