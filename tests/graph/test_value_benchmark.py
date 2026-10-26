from pathlib import Path

import pytest
from graph_trees import GraphBuilder

from lean_search.search.graph_labels import NodeClass, label_graph
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkGroup,
    BenchmarkMetrics,
    BenchmarkState,
    LabelledTree,
    ValueBenchmark,
    benchmark_composition,
    benchmark_metrics,
    build_benchmark,
    read_benchmark,
    recorded_benchmark_estimates,
    write_benchmark,
)
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueEstimate,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)

READOUT = RemainingStepsReadout()


def labelled_tree() -> LabelledTree:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    proof_child = builder.child(builder.root, "⊢ p", value=2.0)
    dead = builder.child(builder.root, "⊢ d", value=1.5)
    builder.failure(dead)
    expanded = builder.child(builder.root, "⊢ e", value=4.0)
    builder.child(expanded, "⊢ e1", value=5.0)
    builder.child(builder.root, "⊢ n", value=6.0)
    proof = builder.child(proof_child)
    record = builder.record(proof)
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, READOUT), READOUT, ValueTargetConfig())
    return LabelledTree(record, labels, targets)


def test_benchmark_holds_every_sibling_state_with_goals() -> None:
    benchmark = build_benchmark([labelled_tree()], BenchmarkConfig())
    assert benchmark_composition(benchmark).states == 5


def test_benchmark_includes_never_expanded_children() -> None:
    benchmark = build_benchmark([labelled_tree()], BenchmarkConfig())
    assert benchmark_composition(benchmark).never_expanded == 2


def test_benchmark_round_trips_through_its_file(tmp_path: Path) -> None:
    benchmark = build_benchmark([labelled_tree()], BenchmarkConfig())
    write_benchmark(tmp_path / "benchmark.json.gz", benchmark)
    assert read_benchmark(tmp_path / "benchmark.json.gz") == benchmark


def test_recorded_estimates_come_from_the_tree() -> None:
    tree = labelled_tree()
    benchmark = build_benchmark([tree], BenchmarkConfig())
    estimates = recorded_benchmark_estimates(benchmark, {"t": tree.record}, READOUT)
    assert estimates[0] == READOUT.estimate(tree.record.nodes[benchmark.states[0].node_id].value_estimate or 0.0)


def test_per_tree_cap_keeps_proof_graph_groups() -> None:
    benchmark = build_benchmark([labelled_tree()], BenchmarkConfig(max_states_per_tree=1))
    assert benchmark_composition(benchmark).groups_with_proof_state == 1


def hand_built_metrics() -> BenchmarkMetrics:
    states = (
        BenchmarkState("t", 1, ("⊢ p",), NodeClass.PROOF_GRAPH, 1.0, 1, 1),
        BenchmarkState("t", 2, ("⊢ d",), NodeClass.DEAD_END, 0.0, None, 1),
        BenchmarkState("t", 3, ("⊢ e",), NodeClass.EXPANDED_OFF_GRAPH, 0.5, None, 2),
        BenchmarkState("t", 4, ("⊢ n",), NodeClass.NEVER_EXPANDED, None, None, 0),
        BenchmarkState("t", 5, ("⊢ m",), NodeClass.NEVER_EXPANDED, None, None, 0),
    )
    benchmark = ValueBenchmark(states, (BenchmarkGroup("t", 0, (0, 1, 2, 3, 4)),))
    estimates = [
        ValueEstimate(0.9, 1.5),
        ValueEstimate(0.95, 1.2),
        ValueEstimate(0.2, 9.0),
        ValueEstimate(0.1, 12.0),
        None,
    ]
    return benchmark_metrics(benchmark, estimates, BenchmarkConfig())


def test_pairwise_ranking_accuracy() -> None:
    assert hand_built_metrics().ranking.pairwise_accuracy == pytest.approx(2 / 3)


def test_ranking_accuracy_over_dead_ends() -> None:
    assert hand_built_metrics().ranking.over_dead_end_accuracy == 0.0


def test_top_accuracy_needs_the_proof_state_above_every_sibling() -> None:
    assert hand_built_metrics().ranking.top_accuracy == 0.0


def test_states_without_estimate_are_counted() -> None:
    assert hand_built_metrics().states_without_estimate == 1


def test_anchor_calibration_error() -> None:
    assert hand_built_metrics().calibration.anchor_expected_calibration_error == pytest.approx(0.425)


def test_anchor_brier_score() -> None:
    assert hand_built_metrics().calibration.anchor_brier_score == pytest.approx((0.1**2 + 0.95**2) / 2)


def test_dead_live_separation() -> None:
    assert hand_built_metrics().separation.proof_graph_over_dead_end_auc == 0.0


def test_remaining_step_error_on_proof_graph_states() -> None:
    assert hand_built_metrics().steps.mean_absolute_error == pytest.approx(0.5)
