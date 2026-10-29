"""The value gate: does a candidate order labelled siblings by h, as A* orders its frontier, better than the published
model, by more than which problems the benchmark happens to hold could explain."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy

from lean_search.search.graph_labels import NodeClass
from lean_search.value.benchmark import (
    BenchmarkConfig,
    BenchmarkMetrics,
    BenchmarkPairKind,
    BenchmarkScores,
    GuidedTrees,
    TreeKey,
    ValueBenchmark,
    benchmark_metrics,
    conflict_message,
    fresh_estimates,
    guidance_conflicts,
    labelled,
)
from lean_search.value.bins import Readout


@dataclass(frozen=True)
class GateConfig:
    # Problems are resampled with replacement, each with all its pairs; the interval is the percentile interval.
    bootstrap_resamples: int = 5000
    confidence: float = 0.95
    seed: int = 0
    # The candidate passes when the interval's lower bound on its gain lies above this.
    min_lower_bound: float = 0.0
    # Benchmark trees from an A* search on a value model: the current model (or its ancestor) chose their labels.
    guided_trees: GuidedTrees = GuidedTrees.REFUSE


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
class TreeOutcomes:
    pairs: int
    candidate: float
    current: float


@dataclass(frozen=True)
class GateStatistic:
    # Problems with a pair scored by both models, and those pairs.
    problems: int
    pairs: int
    # Pairs the two models order differently.
    discordant_pairs: int
    # Share of pairs whose proof-graph state gets the lower h (ties half).
    candidate_accuracy: float | None
    current_accuracy: float | None
    # Candidate minus current, and its bootstrap interval over problems.
    difference: float | None
    lower: float | None
    upper: float | None
    # Independent pairs that would give the bootstrap's spread of the difference: fewer than `pairs` when the pairs
    # of one problem move together.
    effective_pairs: float | None
    resamples: int
    confidence: float


def bootstrap_differences(trees: Sequence[TreeOutcomes], resamples: int, seed: int) -> numpy.ndarray:
    """The pooled accuracy difference over problems drawn with replacement, once per resample."""
    pairs = numpy.array([tree.pairs for tree in trees], dtype=float)
    gains = numpy.array([tree.candidate - tree.current for tree in trees])
    drawn = numpy.random.default_rng(seed).integers(0, len(trees), size=(resamples, len(trees)))
    return gains[drawn].sum(axis=1) / pairs[drawn].sum(axis=1)


def search_order_statistic(
    benchmark: ValueBenchmark,
    candidate: Sequence[float | None],
    current: Sequence[float | None],
    benchmark_config: BenchmarkConfig,
    config: GateConfig,
) -> GateStatistic:
    """Per labelled pair, whether each model gives the proof-graph state the lower h; candidate minus current."""
    by_tree: dict[TreeKey, list[tuple[float, float]]] = {}
    for pair in labelled_pairs(benchmark, benchmark_config):
        steps = (candidate[pair.preferred], candidate[pair.other], current[pair.preferred], current[pair.other])
        if any(value is None for value in steps):
            continue
        candidate_preferred, candidate_other, current_preferred, current_other = steps
        by_tree.setdefault(pair.tree, []).append(
            (lower_h_outcome(candidate_preferred, candidate_other), lower_h_outcome(current_preferred, current_other))
        )
    outcomes = [outcome for tree_outcomes in by_tree.values() for outcome in tree_outcomes]
    if not outcomes:
        return GateStatistic(0, 0, 0, None, None, None, None, None, None, config.bootstrap_resamples, config.confidence)
    trees = [
        TreeOutcomes(len(pairs), sum(first for first, _ in pairs), sum(second for _, second in pairs))
        for pairs in by_tree.values()
    ]
    differences = bootstrap_differences(trees, config.bootstrap_resamples, config.seed)
    tail = (1 - config.confidence) / 2
    lower, upper = numpy.quantile(differences, [tail, 1 - tail])
    pair_gains = numpy.array([first - second for first, second in outcomes])
    spread = float(differences.var())
    candidate_accuracy = sum(first for first, _ in outcomes) / len(outcomes)
    current_accuracy = sum(second for _, second in outcomes) / len(outcomes)
    return GateStatistic(
        problems=len(trees),
        pairs=len(outcomes),
        discordant_pairs=sum(first != second for first, second in outcomes),
        candidate_accuracy=candidate_accuracy,
        current_accuracy=current_accuracy,
        difference=candidate_accuracy - current_accuracy,
        lower=float(lower),
        upper=float(upper),
        effective_pairs=float(pair_gains.var()) / spread if spread > 0 else None,
        resamples=config.bootstrap_resamples,
        confidence=config.confidence,
    )


def gate_reasons(statistic: GateStatistic, config: GateConfig) -> tuple[str, ...]:
    if statistic.lower is None:
        return ("no labelled sibling pair scored by both models",)
    if statistic.lower <= config.min_lower_bound:
        return (
            f"gain in pairs ordered by h {statistic.difference:+.3f}, {config.confidence:.0%} interval "
            f"[{statistic.lower:+.3f}, {statistic.upper:+.3f}] over {statistic.problems} problems and "
            f"{statistic.pairs} pairs; lower bound not above {config.min_lower_bound:+g}",
        )
    return ()


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    statistic: GateStatistic
    # Diagnostics only (AUC, Brier, pair accuracy by p_dead, Spearman), never pass criteria.
    new: BenchmarkMetrics
    current: BenchmarkMetrics
    warnings: tuple[str, ...] = ()


def value_gate(
    benchmark: ValueBenchmark,
    new: BenchmarkScores,
    current: BenchmarkScores,
    readout: Readout,
    benchmark_config: BenchmarkConfig,
    config: GateConfig,
) -> GateResult:
    """Passes when the bootstrap interval of the candidate's gain in h-ordered pairs lies above the bound."""
    statistic = search_order_statistic(
        benchmark, remaining_steps(new, readout), remaining_steps(current, readout), benchmark_config, config
    )
    reasons = gate_reasons(statistic, config)
    # The current adapter (or its ancestor) usually guided any value-model search, so every such tree conflicts.
    conflicts = tuple(conflict_message(source) for source in guidance_conflicts(benchmark.provenance, None))
    warnings: tuple[str, ...] = ()
    match config.guided_trees:
        case GuidedTrees.REFUSE:
            reasons += conflicts
        case GuidedTrees.WARN:
            warnings = conflicts
    return GateResult(
        passed=not reasons,
        reasons=reasons,
        statistic=statistic,
        new=benchmark_metrics(benchmark, fresh_estimates(benchmark, new, readout), benchmark_config),
        current=benchmark_metrics(benchmark, fresh_estimates(benchmark, current, readout), benchmark_config),
        warnings=warnings,
    )
