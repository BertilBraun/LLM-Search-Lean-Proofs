import pytest
from graph_trees import GraphBuilder

from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkScores,
    LabelledTree,
    SearchGuidance,
    TreeProvenance,
    TreeSource,
    benchmark_fingerprint,
    build_benchmark,
)
from lean_search.value.bins import DEAD_BIN, Readout
from lean_search.value.diagnostics import (
    benchmark_calibration,
    frontier_distributions,
    label_distribution,
    label_distributions,
    phase_value_metrics,
    prediction_distribution,
    recorded_calibration,
    recorded_steps,
    target_predictions,
)
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets

ALIVE = (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
MOSTLY_DEAD = (0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.95)


def labelled(record: TreeRecord, value_share: float = 0.0) -> LabelledTree:
    labels = label_graph(record)
    estimates = recorded_estimates(record, RemainingStepsReadout())
    config = ValueTargetConfig(value_share=value_share)
    return LabelledTree(record, labels, value_targets(record, labels, estimates, config))


def solved_tree() -> TreeRecord:
    """The root and its proof-graph child scored alive, a dead end scored mostly dead, a frontier child alive."""
    builder = GraphBuilder("⊢ r", root_value=2.0)
    builder.root.value_distribution = ALIVE
    proof_child = builder.child(builder.root, "⊢ p", value=2.0, distribution=ALIVE)
    dead = builder.child(builder.root, "⊢ d", value=15.0, distribution=MOSTLY_DEAD)
    builder.failure(dead)
    builder.child(builder.root, "⊢ n", value=2.0, distribution=ALIVE)
    return builder.record(builder.child(proof_child))


def unsolved_tree() -> TreeRecord:
    builder = GraphBuilder("⊢ r", root_value=4.0)
    child = builder.child(builder.root, "⊢ c", value=4.0)
    builder.failure(child)
    return builder.record()


def test_a_label_distribution_is_the_weighted_mean_of_its_targets() -> None:
    distribution = label_distribution([(ALIVE, 1.0), (MOSTLY_DEAD, 3.0)])
    assert distribution.bins[DEAD_BIN] == pytest.approx(0.75 * 0.95)


def test_off_graph_targets_of_unsolved_trees_are_counted_apart() -> None:
    labels = label_distributions([labelled(solved_tree()), labelled(unsolved_tree())], 0.5)
    assert (labels.off_graph_solved_trees.targets, labels.off_graph_unsolved_trees.targets) == (1, 2)


def test_proof_graph_labels_carry_no_dead_mass_before_mu() -> None:
    labels = label_distributions([labelled(solved_tree())], 0.5)
    assert labels.proof_graph.bins[DEAD_BIN] == 0.0


def test_off_graph_labels_are_dead_before_mu() -> None:
    labels = label_distributions([labelled(unsolved_tree())], 0.5)
    assert labels.off_graph_unsolved_trees.bins[DEAD_BIN] == 1.0


def test_a_label_distribution_keeps_count_and_weight() -> None:
    distribution = label_distribution([(ALIVE, 2.0)])
    assert (distribution.targets, distribution.weight) == (1, 2.0)


def test_unsmoothed_labels_put_an_exact_step_in_its_own_bin() -> None:
    labels = label_distributions([labelled(solved_tree())], 0.0)
    assert labels.proof_graph.bins[1] == 0.5


def test_dead_histogram_puts_a_near_certain_dead_end_in_the_last_tenth() -> None:
    assert prediction_distribution([MOSTLY_DEAD], Readout()).dead_histogram[-1] == 1


def test_alive_steps_histogram_bins_by_step() -> None:
    assert prediction_distribution([ALIVE], Readout()).alive_steps_histogram[1] == 1


def test_mean_bins_average_the_states() -> None:
    mean_bins = prediction_distribution([ALIVE, MOSTLY_DEAD], Readout()).mean_bins
    assert mean_bins[DEAD_BIN] == pytest.approx(0.475)


def test_a_certain_dead_end_reads_out_as_eight_or_more_steps_given_alive() -> None:
    certain = (0.0,) * DEAD_BIN + (1.0,)
    assert prediction_distribution([certain], Readout()).alive_steps_histogram[-1] == 1


def test_frontier_distributions_are_the_never_expanded_states() -> None:
    assert frontier_distributions([labelled(solved_tree())]) == [ALIVE]


def test_target_predictions_follow_the_labels_sources() -> None:
    predictions = target_predictions([labelled(solved_tree())], Readout())
    assert (predictions.proof_graph.states, predictions.off_graph_solved_trees.states) == (2, 1)


def test_target_predictions_read_the_recorded_bins() -> None:
    predictions = target_predictions([labelled(solved_tree())], Readout())
    assert predictions.off_graph_solved_trees.mean_bins[DEAD_BIN] == pytest.approx(0.95)


def test_recorded_steps_compare_with_the_exact_remaining_steps() -> None:
    steps = recorded_steps([labelled(solved_tree())], Readout())
    assert (steps.proof_graph_states, steps.mean_absolute_error) == (2, pytest.approx(0.5))


def test_recorded_calibration_reports_the_brier_score() -> None:
    assert recorded_calibration([labelled(solved_tree())]).brier_score == pytest.approx(0.05**2 / 3)


def test_phase_metrics_count_every_target() -> None:
    labels = phase_value_metrics([labelled(solved_tree()), labelled(unsolved_tree())], Readout()).labels
    assert (
        labels.proof_graph.targets,
        labels.off_graph_solved_trees.targets,
        labels.off_graph_unsolved_trees.targets,
    ) == (2, 1, 2)


def test_recorded_calibration_compares_with_the_proof_graph_label() -> None:
    bins = recorded_calibration([labelled(solved_tree())]).bins
    assert [(bin.states, bin.mean_target) for bin in bins if bin.states] == [(1, 0.0), (2, 1.0)]


def test_benchmark_calibration_uses_only_expanded_states() -> None:
    provenance = TreeProvenance("benchmark", SearchGuidance.VALUE_FREE, None, "")
    bench = build_benchmark([TreeSource(provenance, (labelled(solved_tree()),))], BenchmarkConfig())
    scores = BenchmarkScores("m", benchmark_fingerprint(bench), (ALIVE,) * len(bench.states))
    assert benchmark_calibration(bench, scores).states == 2
