"""What the value model trains on and what it predicts: label and prediction distributions over the bins, calibration
of the proof probability against the concrete label z of expanded states, and its remaining steps on the proof graph,
from the bins a search recorded (free, per phase) or from fresh scores of the benchmark."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.search.graph_labels import NodeClass
from lean_search.value.benchmark import (
    BenchmarkScores,
    LabelledTree,
    ReliabilityBin,
    StepMetrics,
    ValueBenchmark,
    expected_calibration_error,
    reliability_bins,
)
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, Readout
from lean_search.value.graph_targets import TargetSource, bin_target
from lean_search.value.metrics import mean, spearman_correlation

DEAD_HISTOGRAM_BINS = 10
# Expected remaining steps given alive lie between 1 and the 8+ readout (12): one bin per step.
STEPS_HISTOGRAM_LOW = 1.0
STEPS_HISTOGRAM_BINS = 11
CALIBRATION_BINS = 10


@dataclass(frozen=True)
class LabelDistribution:
    targets: int
    weight: float
    # The weight-averaged target distribution over the bins 1..7, 8+, dead.
    bins: tuple[float, ...]


def label_distribution(targets: Iterable[tuple[Sequence[float], float]]) -> LabelDistribution:
    """From (bin distribution, weight) pairs."""
    count = 0
    total = 0.0
    masses = [0.0] * BIN_COUNT
    for distribution, weight in targets:
        count += 1
        total += weight
        for index, probability in enumerate(distribution):
            masses[index] += weight * probability
    return LabelDistribution(count, total, tuple(mass / total if total else 0.0 for mass in masses))


@dataclass(frozen=True)
class LabelDistributions:
    proof_graph: LabelDistribution
    off_graph_solved_trees: LabelDistribution
    off_graph_unsolved_trees: LabelDistribution


SOURCES = ((TargetSource.PROOF_GRAPH, True), (TargetSource.OFF_GRAPH, True), (TargetSource.OFF_GRAPH, False))


def label_distributions(trees: Sequence[LabelledTree], sigma: float) -> LabelDistributions:
    """The value targets of the trees by source and tree outcome, with their weights before class balancing; `sigma`
    smooths exact steps over the step bins (0: the label's own bin)."""
    groups: dict[tuple[TargetSource, bool], list[tuple[Sequence[float], float]]] = {source: [] for source in SOURCES}
    for tree in trees:
        for target in tree.targets:
            groups[target.source, tree.labels.solved].append((bin_target(target, sigma), target.weight))
    proof_graph, off_graph_solved, off_graph_unsolved = (label_distribution(groups[source]) for source in SOURCES)
    return LabelDistributions(proof_graph, off_graph_solved, off_graph_unsolved)


@dataclass(frozen=True)
class PredictionDistribution:
    states: int
    # Mean probability of each bin 1..7, 8+, dead.
    mean_bins: tuple[float, ...]
    # States per tenth of p_dead: [0, 0.1), ..., [0.9, 1].
    dead_histogram: tuple[int, ...]
    # States per step of the expected remaining steps given alive: [1, 2), ..., [11, 12].
    alive_steps_histogram: tuple[int, ...]


def histogram_bin(value: float, low: float, width: float, count: int) -> int:
    return min(max(int((value - low) / width), 0), count - 1)


def prediction_distribution(distributions: Iterable[Sequence[float]], readout: Readout) -> PredictionDistribution:
    states = 0
    sums = [0.0] * BIN_COUNT
    dead = [0] * DEAD_HISTOGRAM_BINS
    steps = [0] * STEPS_HISTOGRAM_BINS
    for distribution in distributions:
        states += 1
        for index, probability in enumerate(distribution):
            sums[index] += probability
        dead[histogram_bin(distribution[DEAD_BIN], 0.0, 1 / DEAD_HISTOGRAM_BINS, DEAD_HISTOGRAM_BINS)] += 1
        alive_steps = readout.alive_remaining_steps(distribution)
        steps[histogram_bin(alive_steps, STEPS_HISTOGRAM_LOW, 1.0, STEPS_HISTOGRAM_BINS)] += 1
    return PredictionDistribution(
        states, tuple(total / states if states else 0.0 for total in sums), tuple(dead), tuple(steps)
    )


@dataclass(frozen=True)
class PredictionDistributions:
    """The serving model's recorded bins on the states the labels cover, by the same source and tree outcome."""

    proof_graph: PredictionDistribution
    off_graph_solved_trees: PredictionDistribution
    off_graph_unsolved_trees: PredictionDistribution


def target_predictions(trees: Sequence[LabelledTree], readout: Readout) -> PredictionDistributions:
    groups: dict[tuple[TargetSource, bool], list[tuple[float, ...]]] = {source: [] for source in SOURCES}
    for tree in trees:
        for target in tree.targets:
            distribution = tree.record.nodes[target.node_id].value_distribution
            if distribution is not None:
                groups[target.source, tree.labels.solved].append(distribution)
    proof_graph, off_graph_solved, off_graph_unsolved = (
        prediction_distribution(groups[source], readout) for source in SOURCES
    )
    return PredictionDistributions(proof_graph, off_graph_solved, off_graph_unsolved)


def frontier_distributions(trees: Sequence[LabelledTree]) -> list[tuple[float, ...]]:
    """The bins the serving value model recorded for the never-expanded frontier."""
    return [
        node.value_distribution
        for tree in trees
        for node in tree.record.nodes
        if tree.labels.node_classes[node.node_id] == NodeClass.NEVER_EXPANDED
        and node.goals
        and node.value_distribution is not None
    ]


@dataclass(frozen=True)
class Calibration:
    states: int
    expected_calibration_error: float | None
    brier_score: float | None
    # Predicted proof probability (1 - p_dead) against the share of proof-graph states, per tenth of the prediction.
    bins: tuple[ReliabilityBin, ...]


def calibration(pairs: Iterable[tuple[float, float]]) -> Calibration:
    """From (predicted proof probability, z) pairs."""
    predicted: list[float] = []
    observed: list[float] = []
    for probability, label in pairs:
        predicted.append(probability)
        observed.append(label)
    bins = reliability_bins(predicted, observed, CALIBRATION_BINS)
    brier = mean([(probability - label) ** 2 for probability, label in zip(predicted, observed, strict=True)])
    return Calibration(len(predicted), expected_calibration_error(bins), brier, bins)


def concrete_label(node_class: NodeClass) -> float | None:
    """z of an expanded state: 1 on the proof graph, 0 off it (dead ends included)."""
    match node_class:
        case NodeClass.PROOF_GRAPH:
            return 1.0
        case NodeClass.EXPANDED_OFF_GRAPH | NodeClass.DEAD_END:
            return 0.0
        case NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
            return None


def benchmark_calibration(benchmark: ValueBenchmark, scores: BenchmarkScores) -> Calibration:
    """The scored model's proof probability on the benchmark's expanded states against z."""
    pairs = []
    for state, distribution in zip(benchmark.states, scores.distributions, strict=True):
        label = concrete_label(state.node_class)
        if distribution is not None and state.expanded_nodes and label is not None:
            pairs.append((1 - distribution[DEAD_BIN], label))
    return calibration(pairs)


def recorded_calibration(trees: Sequence[LabelledTree]) -> Calibration:
    """The serving value model's recorded proof probability on expanded states against z."""
    pairs = []
    for tree in trees:
        for node in tree.record.nodes:
            label = concrete_label(tree.labels.node_classes[node.node_id])
            if tree.labels.expanded[node.node_id] and node.value_distribution is not None and label is not None:
                pairs.append((1 - node.value_distribution[DEAD_BIN], label))
    return calibration(pairs)


def recorded_steps(trees: Sequence[LabelledTree], readout: Readout) -> StepMetrics:
    """The recorded expected steps given alive against the exact remaining steps of proof-graph states (the shortest
    route to a proof, whatever order the search found it in)."""
    predicted: list[float] = []
    exact: list[float] = []
    for tree in trees:
        for node in tree.record.nodes:
            steps = tree.labels.remaining_steps[node.node_id]
            if steps and node.goals and node.value_distribution is not None:
                predicted.append(readout.alive_remaining_steps(node.value_distribution))
                exact.append(float(steps))
    return StepMetrics(
        proof_graph_states=len(exact),
        mean_absolute_error=mean([abs(first - second) for first, second in zip(predicted, exact, strict=True)]),
        spearman=spearman_correlation(predicted, exact) if len(exact) > 1 else None,
    )


@dataclass(frozen=True)
class PhaseValueMetrics:
    """Free per phase: the serving value model against the phase's own labelled search graphs."""

    # The phase's value targets, exact steps unsmoothed.
    labels: LabelDistributions
    # The recorded bins of the same states, and of the never-expanded frontier.
    predictions: PredictionDistributions
    frontier: PredictionDistribution
    # Expanded states.
    calibration: Calibration
    steps: StepMetrics


def phase_value_metrics(trees: Sequence[LabelledTree], readout: Readout) -> PhaseValueMetrics:
    return PhaseValueMetrics(
        labels=label_distributions(trees, 0.0),
        predictions=target_predictions(trees, readout),
        frontier=prediction_distribution(frontier_distributions(trees), readout),
        calibration=recorded_calibration(trees),
        steps=recorded_steps(trees, readout),
    )


def scored(scores: BenchmarkScores) -> list[tuple[float, ...]]:
    return [distribution for distribution in scores.distributions if distribution is not None]
