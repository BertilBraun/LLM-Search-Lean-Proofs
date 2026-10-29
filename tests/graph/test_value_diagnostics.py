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
    label_distribution,
    label_distributions,
    prediction_distribution,
    recorded_calibration,
    recorded_distributions,
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
    labels = label_distributions([labelled(solved_tree()), labelled(unsolved_tree())], [], 0.5)
    assert (labels.off_graph_solved_trees.targets, labels.off_graph_unsolved_trees.targets) == (1, 2)


def test_proof_graph_labels_carry_no_dead_mass_before_mu() -> None:
    labels = label_distributions([labelled(solved_tree())], [], 0.5)
    assert labels.proof_graph.bins[DEAD_BIN] == 0.0


def test_off_graph_labels_are_dead_before_mu() -> None:
    labels = label_distributions([labelled(unsolved_tree())], [], 0.5)
    assert labels.off_graph_unsolved_trees.bins[DEAD_BIN] == 1.0


def test_replay_labels_keep_their_weights() -> None:
    labels = label_distributions([], [(ALIVE, 2.0)], 0.5)
    assert (labels.replay.targets, labels.replay.weight) == (1, 2.0)


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


@pytest.mark.parametrize(("expanded", "states"), [(True, 3), (False, 1)])
def test_recorded_distributions_of_expanded_and_frontier_states(expanded: bool, states: int) -> None:
    assert len(recorded_distributions([labelled(solved_tree())], expanded)) == states


def test_recorded_calibration_compares_with_the_proof_graph_label() -> None:
    bins = recorded_calibration([labelled(solved_tree())]).bins
    assert [(bin.states, bin.mean_target) for bin in bins if bin.states] == [(1, 0.0), (2, 1.0)]


def test_benchmark_calibration_uses_only_expanded_states() -> None:
    provenance = TreeProvenance("gate", SearchGuidance.VALUE_FREE, None, "")
    bench = build_benchmark([TreeSource(provenance, (labelled(solved_tree()),))], BenchmarkConfig())
    scores = BenchmarkScores("m", benchmark_fingerprint(bench), (ALIVE,) * len(bench.states))
    assert benchmark_calibration(bench, scores).states == 2
