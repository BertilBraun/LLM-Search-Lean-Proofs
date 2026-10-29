"""What a value retrain trained on and what the models predict: label and prediction distributions over the bins,
and calibration of the proof probability against the concrete label z of expanded states."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.search.graph_labels import NodeClass
from lean_search.value.benchmark import (
    BenchmarkScores,
    LabelledTree,
    ReliabilityBin,
    ValueBenchmark,
    expected_calibration_error,
    reliability_bins,
)
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, Readout
from lean_search.value.graph_targets import TargetSource, bin_target

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
    replay: LabelDistribution


def label_distributions(
    trees: Sequence[LabelledTree], replay: Iterable[tuple[Sequence[float], float]], sigma: float
) -> LabelDistributions:
    """The value targets of the trees by source and tree outcome, with their weights before class balancing."""
    groups: dict[tuple[TargetSource, bool], list[tuple[Sequence[float], float]]] = {
        (TargetSource.PROOF_GRAPH, True): [],
        (TargetSource.OFF_GRAPH, True): [],
        (TargetSource.OFF_GRAPH, False): [],
    }
    for tree in trees:
        solved = tree.labels.solved
        for target in tree.targets:
            groups[target.source, solved].append((bin_target(target, sigma), target.weight))
    return LabelDistributions(
        proof_graph=label_distribution(groups[TargetSource.PROOF_GRAPH, True]),
        off_graph_solved_trees=label_distribution(groups[TargetSource.OFF_GRAPH, True]),
        off_graph_unsolved_trees=label_distribution(groups[TargetSource.OFF_GRAPH, False]),
        replay=label_distribution(replay),
    )


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
class Calibration:
    states: int
    expected_calibration_error: float | None
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
    return Calibration(len(predicted), expected_calibration_error(bins), bins)


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


def recorded_distributions(trees: Sequence[LabelledTree], expanded: bool) -> list[tuple[float, ...]]:
    """The bins the serving value model recorded for the expanded states, or for the never-expanded frontier."""
    distributions = []
    for tree in trees:
        for node in tree.record.nodes:
            node_class = tree.labels.node_classes[node.node_id]
            wanted = tree.labels.expanded[node.node_id] if expanded else node_class == NodeClass.NEVER_EXPANDED
            if wanted and node.goals and node.value_distribution is not None:
                distributions.append(node.value_distribution)
    return distributions


def recorded_calibration(trees: Sequence[LabelledTree]) -> Calibration:
    """The serving value model's recorded proof probability on expanded states against z."""
    pairs = []
    for tree in trees:
        for node in tree.record.nodes:
            label = concrete_label(tree.labels.node_classes[node.node_id])
            if tree.labels.expanded[node.node_id] and node.value_distribution is not None and label is not None:
                pairs.append((1 - node.value_distribution[DEAD_BIN], label))
    return calibration(pairs)


@dataclass(frozen=True)
class ValueDiagnostics:
    # The retrain's targets (its window of trees) and v0 replay.
    labels: LabelDistributions
    # Fresh predictions of the candidate and the published model on the gate's benchmark.
    benchmark_candidate: PredictionDistribution
    benchmark_published: PredictionDistribution
    benchmark_candidate_calibration: Calibration
    # What the serving model recorded on the phase's trees (none in trees written before the bins were kept).
    phase_expanded: PredictionDistribution
    phase_frontier: PredictionDistribution
    phase_calibration: Calibration


def value_diagnostics(
    window: Sequence[LabelledTree],
    replay: Iterable[tuple[Sequence[float], float]],
    phase: Sequence[LabelledTree],
    benchmark: ValueBenchmark,
    candidate: BenchmarkScores,
    published: BenchmarkScores,
    readout: Readout,
    sigma: float,
) -> ValueDiagnostics:
    return ValueDiagnostics(
        labels=label_distributions(window, replay, sigma),
        benchmark_candidate=prediction_distribution(scored(candidate), readout),
        benchmark_published=prediction_distribution(scored(published), readout),
        benchmark_candidate_calibration=benchmark_calibration(benchmark, candidate),
        phase_expanded=prediction_distribution(recorded_distributions(phase, expanded=True), readout),
        phase_frontier=prediction_distribution(recorded_distributions(phase, expanded=False), readout),
        phase_calibration=recorded_calibration(phase),
    )


def scored(scores: BenchmarkScores) -> list[tuple[float, ...]]:
    return [distribution for distribution in scores.distributions if distribution is not None]
