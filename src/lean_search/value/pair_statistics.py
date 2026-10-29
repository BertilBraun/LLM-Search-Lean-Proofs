"""The benchmark's pair statistic: how often a value model gives the proof-graph child of a labelled sibling pair the
lower h (the quantity A* orders its frontier by), and how a model compares with a reference model beyond what the
problems the benchmark happens to hold could explain."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy

from lean_search.search.graph_labels import NodeClass
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkPairKind,
    BenchmarkScores,
    TreeKey,
    ValueBenchmark,
    labelled,
)
from lean_search.value.bins import Readout


@dataclass(frozen=True)
class PairStatisticConfig:
    # Problems are resampled with replacement, each with all its pairs; the interval is the percentile interval.
    bootstrap_resamples: int = 5000
    confidence: float = 0.95
    seed: int = 0


@dataclass(frozen=True)
class LabelledPair:
    tree: TreeKey
    # Benchmark state indices: the proof-graph child and its dead-end or explored off-graph sibling.
    preferred: int
    other: int
    kind: BenchmarkPairKind


def labelled_pairs(benchmark: ValueBenchmark, config: BenchmarkConfig) -> list[LabelledPair]:
    """Each proof-graph state over each labelled sibling (a dead end, or an off-graph state the search explored)."""
    pairs = []
    for group in benchmark.groups:
        members = [(index, benchmark.states[index]) for index in group.state_indices]
        known = [(index, state) for index, state in members if labelled(state, config)]
        proofs = [index for index, state in known if state.node_class == NodeClass.PROOF_GRAPH]
        for index, state in known:
            match state.node_class:
                case NodeClass.DEAD_END:
                    kind = BenchmarkPairKind.PROOF_OVER_DEAD_END
                case NodeClass.EXPANDED_OFF_GRAPH:
                    kind = BenchmarkPairKind.PROOF_OVER_EXPANDED
                case NodeClass.PROOF_GRAPH | NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
                    continue
            tree = TreeKey(group.run, group.problem_name)
            pairs.extend(LabelledPair(tree, proof, index, kind) for proof in proofs)
    return pairs


def remaining_steps(scores: BenchmarkScores, readout: Readout) -> list[float | None]:
    """h per benchmark state as A* reads it; None where the prompt did not fit."""
    return [
        None if distribution is None else readout.remaining_steps(distribution) for distribution in scores.distributions
    ]


def lower_h_outcome(preferred: float, other: float) -> float:
    """1 when the proof-graph state gets the lower h (A* expands it first), 0.5 for a tie."""
    if preferred == other:
        return 0.5
    return float(preferred < other)


@dataclass(frozen=True)
class PairShare:
    """One model's pairs: those it scored, their problems, and the share whose proof-graph state gets the lower h."""

    problems: int
    pairs: int
    share: float | None


def pair_share(benchmark: ValueBenchmark, steps: Sequence[float | None], config: BenchmarkConfig) -> PairShare:
    outcomes: dict[TreeKey, list[float]] = {}
    for pair in labelled_pairs(benchmark, config):
        preferred, other = steps[pair.preferred], steps[pair.other]
        if preferred is not None and other is not None:
            outcomes.setdefault(pair.tree, []).append(lower_h_outcome(preferred, other))
    values = [value for tree in outcomes.values() for value in tree]
    return PairShare(len(outcomes), len(values), sum(values) / len(values) if values else None)


@dataclass(frozen=True)
class TreeOutcomes:
    pairs: int
    model: float
    reference: float


@dataclass(frozen=True)
class PairStatistic:
    # Problems with a pair scored by both models, and those pairs.
    problems: int
    pairs: int
    # Pairs the two models order differently.
    discordant_pairs: int
    # Share of pairs whose proof-graph state gets the lower h (ties half).
    model_share: float | None
    reference_share: float | None
    # Model minus reference, and its bootstrap interval over problems.
    difference: float | None
    lower: float | None
    upper: float | None
    # Independent pairs that would give the bootstrap's spread of the difference: fewer than `pairs` when the pairs
    # of one problem move together.
    effective_pairs: float | None
    resamples: int
    confidence: float


def bootstrap_differences(trees: Sequence[TreeOutcomes], resamples: int, seed: int) -> numpy.ndarray:
    """The pooled share difference over problems drawn with replacement, once per resample."""
    pairs = numpy.array([tree.pairs for tree in trees], dtype=float)
    gains = numpy.array([tree.model - tree.reference for tree in trees])
    drawn = numpy.random.default_rng(seed).integers(0, len(trees), size=(resamples, len(trees)))
    return gains[drawn].sum(axis=1) / pairs[drawn].sum(axis=1)


def pair_statistic(
    benchmark: ValueBenchmark,
    model: Sequence[float | None],
    reference: Sequence[float | None],
    benchmark_config: BenchmarkConfig,
    config: PairStatisticConfig,
) -> PairStatistic:
    """Per labelled pair scored by both, whether each model gives the proof-graph state the lower h; a paired cluster
    bootstrap over problems of the model's share minus the reference's."""
    by_tree: dict[TreeKey, list[tuple[float, float]]] = {}
    for pair in labelled_pairs(benchmark, benchmark_config):
        steps = (model[pair.preferred], model[pair.other], reference[pair.preferred], reference[pair.other])
        if any(value is None for value in steps):
            continue
        model_preferred, model_other, reference_preferred, reference_other = steps
        by_tree.setdefault(pair.tree, []).append(
            (lower_h_outcome(model_preferred, model_other), lower_h_outcome(reference_preferred, reference_other))
        )
    outcomes = [outcome for tree_outcomes in by_tree.values() for outcome in tree_outcomes]
    if not outcomes:
        return PairStatistic(0, 0, 0, None, None, None, None, None, None, config.bootstrap_resamples, config.confidence)
    trees = [
        TreeOutcomes(len(pairs), sum(first for first, _ in pairs), sum(second for _, second in pairs))
        for pairs in by_tree.values()
    ]
    differences = bootstrap_differences(trees, config.bootstrap_resamples, config.seed)
    tail = (1 - config.confidence) / 2
    lower, upper = numpy.quantile(differences, [tail, 1 - tail])
    pair_gains = numpy.array([first - second for first, second in outcomes])
    spread = float(differences.var())
    model_share = sum(first for first, _ in outcomes) / len(outcomes)
    reference_share = sum(second for _, second in outcomes) / len(outcomes)
    return PairStatistic(
        problems=len(trees),
        pairs=len(outcomes),
        discordant_pairs=sum(first != second for first, second in outcomes),
        model_share=model_share,
        reference_share=reference_share,
        difference=model_share - reference_share,
        lower=float(lower),
        upper=float(upper),
        effective_pairs=float(pair_gains.var()) / spread if spread > 0 else None,
        resamples=config.bootstrap_resamples,
        confidence=config.confidence,
    )
