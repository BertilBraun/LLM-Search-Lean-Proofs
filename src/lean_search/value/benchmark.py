"""A fixed value benchmark of sibling groups from labelled search graphs, its provenance, and metrics for estimates."""

import gzip
import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from lean_search.search.graph_labels import GraphLabels, NodeClass
from lean_search.search.priority import PriorityConfig, PriorityKind
from lean_search.search.records import TreeRecord, from_json_object, to_json
from lean_search.value.bins import Readout
from lean_search.value.config import ValueConfig
from lean_search.value.graph_targets import ValueTarget, bin_estimate
from lean_search.value.metrics import roc_auc, spearman_correlation
from lean_search.value.ranking import PairKind, expanded_nodes

GROUP_PRIORITY = {NodeClass.PROOF_GRAPH: 0, NodeClass.DEAD_END: 1}
RECORDED_DESCRIPTION = "recorded (biased if the trees were guided by this model)"


class SearchGuidance(StrEnum):
    # Best-first without a value estimate (cumulative log-probability, depth plus goals): labels no value model chose.
    VALUE_FREE = "value_free"
    # A* on a fixed heuristic h (goal count).
    HEURISTIC_VALUE = "heuristic_value"
    # A* on a served value model: that model chose which states were expanded and so which carry labels.
    VALUE_MODEL = "value_model"
    # The trees record value estimates but the run's config is unknown.
    UNKNOWN_VALUE = "unknown_value"


@dataclass(frozen=True)
class TreeProvenance:
    run: str
    guidance: SearchGuidance
    # The priority kind from the run's config; None when the config is unknown.
    priority: PriorityKind | None
    # The served value adapter, or the merged value model's name, that guided an A* search; "" otherwise.
    value_model: str


class GuidedTrees(StrEnum):
    REFUSE = "refuse"
    WARN = "warn"


def search_provenance(run: str, config_text: str | None, records: Sequence[TreeRecord]) -> TreeProvenance:
    """From the run's config.toml; without one, trees that recorded value estimates count as guided by an unknown h."""
    recorded_values = any(node.value_estimate is not None for record in records for node in record.nodes)
    if config_text is None:
        guidance = SearchGuidance.UNKNOWN_VALUE if recorded_values else SearchGuidance.VALUE_FREE
        return TreeProvenance(run, guidance, None, "")
    data = tomllib.loads(config_text)
    priority = from_json_object(PriorityConfig, data.get("priority", {}))
    value = from_json_object(ValueConfig, data.get("value", {}))
    if priority.kind != PriorityKind.A_STAR:
        if recorded_values:
            raise ValueError(f"{run}: the config's priority is {priority.kind} but the trees record value estimates.")
        return TreeProvenance(run, SearchGuidance.VALUE_FREE, priority.kind, "")
    if not value.model:
        return TreeProvenance(run, SearchGuidance.HEURISTIC_VALUE, priority.kind, str(priority.value_estimator))
    return TreeProvenance(run, SearchGuidance.VALUE_MODEL, priority.kind, value.adapter or value.model)


def guidance_conflicts(
    provenance: Sequence[TreeProvenance], compared_models: Sequence[str] | None
) -> tuple[TreeProvenance, ...]:
    """Runs whose labels one of the compared value models selected; None compares every value model."""
    conflicts = []
    for source in provenance:
        match source.guidance:
            case SearchGuidance.VALUE_FREE | SearchGuidance.HEURISTIC_VALUE:
                continue
            case SearchGuidance.VALUE_MODEL:
                if compared_models is None or source.value_model in compared_models:
                    conflicts.append(source)
            case SearchGuidance.UNKNOWN_VALUE:
                conflicts.append(source)
    return tuple(conflicts)


def conflict_message(source: TreeProvenance) -> str:
    match source.guidance:
        case SearchGuidance.UNKNOWN_VALUE:
            return f"{source.run}: trees record value estimates and the run's config is unknown"
        case _:
            return f"{source.run}: trees from an A* search guided by {source.value_model}, which chose the labels"


@dataclass(frozen=True)
class BenchmarkConfig:
    max_states_per_tree: int = 32
    max_states: int = 5000
    calibration_bins: int = 10
    # An expanded off-graph sibling carries a label once the search explored below it (it plus an expanded child).
    min_expanded_nodes: int = 2


@dataclass(frozen=True)
class BenchmarkState:
    run: str
    problem_name: str
    node_id: int
    goals: tuple[str, ...]
    node_class: NodeClass
    # 1 on the proof graph, 0 for a dead end, the averaged value of an expanded off-graph state, else None.
    target_proof_probability: float | None
    # Exact, on the proof graph only.
    remaining_steps: int | None
    expanded_nodes: int


@dataclass(frozen=True)
class BenchmarkGroup:
    run: str
    problem_name: str
    parent_id: int
    state_indices: tuple[int, ...]


@dataclass(frozen=True)
class ValueBenchmark:
    provenance: tuple[TreeProvenance, ...]
    states: tuple[BenchmarkState, ...]
    groups: tuple[BenchmarkGroup, ...]


@dataclass(frozen=True)
class LabelledTree:
    record: TreeRecord
    labels: GraphLabels
    targets: Sequence[ValueTarget]


@dataclass(frozen=True)
class TreeSource:
    provenance: TreeProvenance
    trees: tuple[LabelledTree, ...]


class TreeKey(NamedTuple):
    run: str
    problem_name: str


def hashed(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def group_priority(labels: GraphLabels, successors: Sequence[int]) -> int:
    return min(GROUP_PRIORITY.get(labels.node_classes[node_id], 2) for node_id in successors)


class SiblingStates(NamedTuple):
    priority: int
    order: str
    parent_id: int
    members: tuple[int, ...]


def tree_groups(tree: LabelledTree, max_states: int) -> list[SiblingStates]:
    """Every group with a proof-graph state, then groups with a dead end, then the rest while within `max_states`."""
    labels = tree.labels
    candidates = []
    for parent_id, successors in labels.successors.items():
        members = tuple(node_id for node_id in successors if tree.record.nodes[node_id].goals)
        if members:
            order = hashed(f"{tree.record.problem_name}/{parent_id}")
            candidates.append(SiblingStates(group_priority(labels, members), order, parent_id, members))
    chosen: list[SiblingStates] = []
    states: set[int] = set()
    for candidate in sorted(candidates):
        new_states = states | set(candidate.members)
        if candidate.priority > 0 and len(new_states) > max_states:
            continue
        states = new_states
        chosen.append(candidate)
    return chosen


def build_benchmark(sources: Sequence[TreeSource], config: BenchmarkConfig) -> ValueBenchmark:
    """One tree per statement (the first source listing it wins), in a fixed hashed order of statements."""
    ordered = sorted(
        (
            (hashed(tree.record.problem_name), position, source.provenance.run, tree)
            for position, source in enumerate(sources)
            for tree in source.trees
        ),
        key=lambda item: item[:2],
    )
    states: list[BenchmarkState] = []
    groups: list[BenchmarkGroup] = []
    taken: set[str] = set()
    for _, _, run, tree in ordered:
        if tree.record.problem_name in taken:
            continue
        chosen = tree_groups(tree, config.max_states_per_tree)
        tree_state_count = len({node_id for group in chosen for node_id in group.members})
        if len(states) + tree_state_count > config.max_states:
            continue
        taken.add(tree.record.problem_name)
        targets = {target.node_id: target for target in tree.targets}
        index_by_node: dict[int, int] = {}
        for group in chosen:
            for node_id in group.members:
                if node_id not in index_by_node:
                    index_by_node[node_id] = len(states)
                    states.append(benchmark_state(run, tree, node_id, targets.get(node_id)))
            indices = tuple(index_by_node[node_id] for node_id in group.members)
            groups.append(BenchmarkGroup(run, tree.record.problem_name, group.parent_id, indices))
    used_runs = {state.run for state in states}
    provenance = tuple(source.provenance for source in sources if source.provenance.run in used_runs)
    return ValueBenchmark(provenance, tuple(states), tuple(groups))


def benchmark_state(run: str, tree: LabelledTree, node_id: int, target: ValueTarget | None) -> BenchmarkState:
    return BenchmarkState(
        run=run,
        problem_name=tree.record.problem_name,
        node_id=node_id,
        goals=tree.record.nodes[node_id].goals,
        node_class=tree.labels.node_classes[node_id],
        target_proof_probability=None if target is None else target.proof_probability,
        remaining_steps=tree.labels.remaining_steps[node_id],
        expanded_nodes=expanded_nodes(tree.labels, node_id) if tree.labels.expanded[node_id] else 0,
    )


def benchmark_fingerprint(benchmark: ValueBenchmark) -> str:
    """Identifies the benchmark's states, so scores are only ever read against the states they were made for."""
    identity = [(state.run, state.problem_name, state.node_id, state.goals) for state in benchmark.states]
    return hashed(json.dumps(identity, ensure_ascii=False))


def write_benchmark(path: Path, benchmark: ValueBenchmark) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write(to_json(benchmark))


def read_benchmark(path: Path) -> ValueBenchmark:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return from_json_object(ValueBenchmark, json.load(file))


@dataclass(frozen=True)
class BenchmarkScores:
    """A value model's fresh bin distributions on every benchmark state, so models are compared on identical states."""

    model: str
    benchmark_fingerprint: str
    # Per benchmark state, the probabilities of the bins 1..7, 8+, dead; None when the prompt did not fit.
    distributions: tuple[tuple[float, ...] | None, ...]


def write_scores(path: Path, scores: BenchmarkScores) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write(to_json(scores))


def read_scores(path: Path) -> BenchmarkScores:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return from_json_object(BenchmarkScores, json.load(file))


class EstimateKind(StrEnum):
    # Bin distributions scored on the benchmark states: a proof probability (1 - p_dead) and steps given alive.
    FRESH = "fresh"
    # The scalar h a search recorded: no probability, so ranking and steps only.
    RECORDED = "recorded"


@dataclass(frozen=True)
class StateEstimate:
    # None for a recorded h, which carries no probability.
    proof_probability: float | None
    # Steps given alive for fresh scores, the recorded h otherwise.
    remaining_steps: float

    def ranking_key(self) -> tuple[float, ...]:
        if self.proof_probability is None:
            return (-self.remaining_steps,)
        return (self.proof_probability, -self.remaining_steps)


@dataclass(frozen=True)
class BenchmarkEstimates:
    kind: EstimateKind
    # None for h recorded by the searches that built the benchmark: each tree's own guiding model.
    model: str | None
    estimates: tuple[StateEstimate | None, ...]

    @property
    def description(self) -> str:
        match self.kind:
            case EstimateKind.FRESH:
                return f"fresh scores of {self.model}"
            case EstimateKind.RECORDED:
                source = "the guiding value model of each tree" if self.model is None else self.model
                return f"{RECORDED_DESCRIPTION}: h of {source}"


def fresh_estimates(benchmark: ValueBenchmark, scores: BenchmarkScores, readout: Readout) -> BenchmarkEstimates:
    if scores.benchmark_fingerprint != benchmark_fingerprint(benchmark):
        raise ValueError(f"The scores of {scores.model} were made for another benchmark.")
    estimates = []
    for probabilities in scores.distributions:
        if probabilities is None:
            estimates.append(None)
        else:
            estimate = bin_estimate(probabilities, readout)
            estimates.append(StateEstimate(estimate.proof_probability, estimate.remaining_steps))
    return BenchmarkEstimates(EstimateKind.FRESH, scores.model, tuple(estimates))


def recorded_benchmark_estimates(
    benchmark: ValueBenchmark, records: Mapping[TreeKey, TreeRecord]
) -> BenchmarkEstimates:
    """The h each benchmark state's own search recorded (the value version that ran it); value-free trees have none."""
    estimates = []
    for state in benchmark.states:
        value = records[TreeKey(state.run, state.problem_name)].nodes[state.node_id].value_estimate
        estimates.append(None if value is None else StateEstimate(None, value))
    return BenchmarkEstimates(EstimateKind.RECORDED, None, tuple(estimates))


def looked_up_estimates(benchmark: ValueBenchmark, records: Sequence[TreeRecord], model: str) -> BenchmarkEstimates:
    """The h `model` recorded for identical goals of the same statement in searches it guided (prompts are goals)."""
    recorded: dict[tuple[str, tuple[str, ...]], float] = {}
    for record in records:
        for node in record.nodes:
            if node.value_estimate is not None:
                recorded.setdefault((record.problem_name, node.goals), node.value_estimate)
    estimates = []
    for state in benchmark.states:
        value = recorded.get((state.problem_name, state.goals))
        estimates.append(None if value is None else StateEstimate(None, value))
    return BenchmarkEstimates(EstimateKind.RECORDED, model, tuple(estimates))


def circular_runs(benchmark: ValueBenchmark, estimates: BenchmarkEstimates) -> tuple[str, ...]:
    """Runs whose labels the estimating model selected (or may have: unknown configs)."""
    if estimates.model is None:
        guided = [source for source in benchmark.provenance if source.guidance != SearchGuidance.VALUE_FREE]
    else:
        guided = list(guidance_conflicts(benchmark.provenance, [estimates.model]))
    return tuple(source.run for source in guided)


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    states: int
    mean_predicted: float | None
    mean_target: float | None


@dataclass(frozen=True)
class PairAccuracy:
    pairs: int
    # The preferred state scored higher, ties count half.
    accuracy: float | None


@dataclass(frozen=True)
class RankingMetrics:
    groups_with_proof_state: int
    # A proof-graph state over its labelled siblings (dead ends and explored expanded states), all such pairs.
    pairs: int
    pairwise_accuracy: float | None
    proof_over_dead_end: PairAccuracy
    proof_over_expanded: PairAccuracy
    expanded_over_dead_end: PairAccuracy
    # Groups whose highest-scored labelled state is on the proof graph, among groups with a labelled sibling too.
    top_accuracy: float | None
    # Sibling states in scored groups that carry no label and so enter no pair: they are unknown, not negatives.
    never_expanded_siblings: int
    unexplored_expanded_siblings: int


@dataclass(frozen=True)
class CalibrationMetrics:
    # Proof-graph and dead-end states: Lean's anchors.
    anchor_states: int
    anchor_expected_calibration_error: float | None
    anchor_brier_score: float | None
    anchor_bins: tuple[ReliabilityBin, ...]


@dataclass(frozen=True)
class SeparationMetrics:
    # Proof probability separating proof-graph states (positive) from dead ends.
    proof_graph_over_dead_end_auc: float | None
    # Every expanded state that is not a dead end against dead ends.
    expanded_over_dead_end_auc: float | None


@dataclass(frozen=True)
class StepMetrics:
    proof_graph_states: int
    mean_absolute_error: float | None
    spearman: float | None


@dataclass(frozen=True)
class BenchmarkMetrics:
    estimates: str
    kind: EstimateKind
    model: str | None
    # Benchmark runs whose labels the estimating model selected: ranking metrics on them are circular.
    circular_runs: tuple[str, ...]
    states: int
    groups: int
    states_without_estimate: int
    ranking: RankingMetrics
    steps: StepMetrics
    # Only for estimates with a proof probability (fresh bins with a dead bin), never from a mapped h.
    calibration: CalibrationMetrics | None
    separation: SeparationMetrics | None


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def preference(first: StateEstimate, second: StateEstimate) -> float:
    """1 when the first scores higher (proof probability, then fewer steps), 0.5 for a tie."""
    first_key, second_key = first.ranking_key(), second.ranking_key()
    if first_key == second_key:
        return 0.5
    return float(first_key > second_key)


def labelled(state: BenchmarkState, config: BenchmarkConfig) -> bool:
    match state.node_class:
        case NodeClass.PROOF_GRAPH | NodeClass.DEAD_END:
            return True
        case NodeClass.EXPANDED_OFF_GRAPH:
            return state.expanded_nodes >= config.min_expanded_nodes
        case NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
            return False


def pair_accuracy(outcomes: Sequence[float]) -> PairAccuracy:
    return PairAccuracy(len(outcomes), mean(outcomes))


def ranking_metrics(
    benchmark: ValueBenchmark, estimates: Sequence[StateEstimate | None], config: BenchmarkConfig
) -> RankingMetrics:
    outcomes: dict[PairKind, list[float]] = {kind: [] for kind in PairKind}
    top: list[float] = []
    groups_with_proof_state = never_expanded = unexplored = 0
    for group in benchmark.groups:
        members = [(benchmark.states[index], estimates[index]) for index in group.state_indices]
        scored = [(state, estimate) for state, estimate in members if estimate is not None]
        known = [(state, estimate) for state, estimate in scored if labelled(state, config)]
        proofs = [estimate for state, estimate in known if state.node_class == NodeClass.PROOF_GRAPH]
        dead_ends = [estimate for state, estimate in known if state.node_class == NodeClass.DEAD_END]
        expanded = [estimate for state, estimate in known if state.node_class == NodeClass.EXPANDED_OFF_GRAPH]
        for proof in proofs:
            outcomes[PairKind.PROOF_OVER_DEAD_END].extend(preference(proof, other) for other in dead_ends)
            outcomes[PairKind.PROOF_OVER_EXPANDED].extend(preference(proof, other) for other in expanded)
        for alive in expanded:
            outcomes[PairKind.EXPANDED_OVER_DEAD_END].extend(preference(alive, other) for other in dead_ends)
        if not proofs:
            continue
        groups_with_proof_state += 1
        never_expanded += sum(state.node_class == NodeClass.NEVER_EXPANDED for state, _ in members)
        unexplored += sum(
            state.node_class == NodeClass.EXPANDED_OFF_GRAPH and not labelled(state, config) for state, _ in members
        )
        others = dead_ends + expanded
        if others:
            best_proof = max(proofs, key=StateEstimate.ranking_key)
            top.append(min(preference(best_proof, other) for other in others))
    proof_pairs = outcomes[PairKind.PROOF_OVER_DEAD_END] + outcomes[PairKind.PROOF_OVER_EXPANDED]
    return RankingMetrics(
        groups_with_proof_state=groups_with_proof_state,
        pairs=len(proof_pairs),
        pairwise_accuracy=mean(proof_pairs),
        proof_over_dead_end=pair_accuracy(outcomes[PairKind.PROOF_OVER_DEAD_END]),
        proof_over_expanded=pair_accuracy(outcomes[PairKind.PROOF_OVER_EXPANDED]),
        expanded_over_dead_end=pair_accuracy(outcomes[PairKind.EXPANDED_OVER_DEAD_END]),
        top_accuracy=mean(top),
        never_expanded_siblings=never_expanded,
        unexplored_expanded_siblings=unexplored,
    )


def reliability_bins(predicted: Sequence[float], targets: Sequence[float], count: int) -> tuple[ReliabilityBin, ...]:
    members: list[list[int]] = [[] for _ in range(count)]
    for index, probability in enumerate(predicted):
        members[min(int(probability * count), count - 1)].append(index)
    return tuple(
        ReliabilityBin(
            lower=position / count,
            upper=(position + 1) / count,
            states=len(indices),
            mean_predicted=mean([predicted[index] for index in indices]),
            mean_target=mean([targets[index] for index in indices]),
        )
        for position, indices in enumerate(members)
    )


def expected_calibration_error(bins: Sequence[ReliabilityBin]) -> float | None:
    total = sum(reliability_bin.states for reliability_bin in bins)
    if not total:
        return None
    return sum(
        reliability_bin.states / total * abs(reliability_bin.mean_predicted - reliability_bin.mean_target)
        for reliability_bin in bins
        if reliability_bin.mean_predicted is not None and reliability_bin.mean_target is not None
    )


def probability_estimates(estimates: Sequence[StateEstimate | None]) -> list[float | None]:
    probabilities = []
    for estimate in estimates:
        assert estimate is None or estimate.proof_probability is not None
        probabilities.append(None if estimate is None else estimate.proof_probability)
    return probabilities


def calibration_metrics(
    benchmark: ValueBenchmark, probabilities: Sequence[float | None], bin_count: int
) -> CalibrationMetrics:
    predicted: list[float] = []
    targets: list[float] = []
    for state, probability in zip(benchmark.states, probabilities, strict=True):
        if probability is None:
            continue
        match state.node_class:
            case NodeClass.PROOF_GRAPH:
                predicted.append(probability)
                targets.append(1.0)
            case NodeClass.DEAD_END:
                predicted.append(probability)
                targets.append(0.0)
            case NodeClass.EXPANDED_OFF_GRAPH | NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
                pass
    bins = reliability_bins(predicted, targets, bin_count)
    brier = [(probability - target) ** 2 for probability, target in zip(predicted, targets, strict=True)]
    return CalibrationMetrics(
        anchor_states=len(predicted),
        anchor_expected_calibration_error=expected_calibration_error(bins),
        anchor_brier_score=mean(brier),
        anchor_bins=bins,
    )


def separation_metrics(benchmark: ValueBenchmark, probabilities: Sequence[float | None]) -> SeparationMetrics:
    proof_scores: list[float] = []
    expanded_scores: list[float] = []
    dead_scores: list[float] = []
    for state, probability in zip(benchmark.states, probabilities, strict=True):
        if probability is None:
            continue
        match state.node_class:
            case NodeClass.PROOF_GRAPH:
                proof_scores.append(probability)
                if state.expanded_nodes:
                    expanded_scores.append(probability)
            case NodeClass.EXPANDED_OFF_GRAPH:
                expanded_scores.append(probability)
            case NodeClass.DEAD_END:
                dead_scores.append(probability)
            case NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
                pass
    return SeparationMetrics(
        proof_graph_over_dead_end_auc=roc_auc(
            proof_scores + dead_scores, [True] * len(proof_scores) + [False] * len(dead_scores)
        ),
        expanded_over_dead_end_auc=roc_auc(
            expanded_scores + dead_scores, [True] * len(expanded_scores) + [False] * len(dead_scores)
        ),
    )


def step_metrics(benchmark: ValueBenchmark, estimates: Sequence[StateEstimate | None]) -> StepMetrics:
    predicted: list[float] = []
    exact: list[float] = []
    for state, estimate in zip(benchmark.states, estimates, strict=True):
        if estimate is not None and state.remaining_steps is not None:
            predicted.append(estimate.remaining_steps)
            exact.append(float(state.remaining_steps))
    return StepMetrics(
        proof_graph_states=len(exact),
        mean_absolute_error=mean([abs(first - second) for first, second in zip(predicted, exact, strict=True)]),
        spearman=spearman_correlation(predicted, exact) if len(exact) > 1 else None,
    )


def benchmark_metrics(
    benchmark: ValueBenchmark, estimates: BenchmarkEstimates, config: BenchmarkConfig
) -> BenchmarkMetrics:
    states = estimates.estimates
    assert len(states) == len(benchmark.states)
    calibration = separation = None
    match estimates.kind:
        case EstimateKind.FRESH:
            probabilities = probability_estimates(states)
            calibration = calibration_metrics(benchmark, probabilities, config.calibration_bins)
            separation = separation_metrics(benchmark, probabilities)
        case EstimateKind.RECORDED:
            assert all(estimate is None or estimate.proof_probability is None for estimate in states)
    return BenchmarkMetrics(
        estimates=estimates.description,
        kind=estimates.kind,
        model=estimates.model,
        circular_runs=circular_runs(benchmark, estimates),
        states=len(benchmark.states),
        groups=len(benchmark.groups),
        states_without_estimate=sum(estimate is None for estimate in states),
        ranking=ranking_metrics(benchmark, states, config),
        steps=step_metrics(benchmark, states),
        calibration=calibration,
        separation=separation,
    )


@dataclass(frozen=True)
class BenchmarkComposition:
    states: int
    groups: int
    proof_graph: int
    dead_end: int
    expanded_off_graph: int
    # Expanded off-graph states the search explored below, which therefore pair with their siblings.
    labelled_expanded_off_graph: int
    never_expanded: int
    groups_with_proof_state: int
    trees: int


def benchmark_composition(benchmark: ValueBenchmark, config: BenchmarkConfig) -> BenchmarkComposition:
    classes = [state.node_class for state in benchmark.states]
    return BenchmarkComposition(
        states=len(benchmark.states),
        groups=len(benchmark.groups),
        proof_graph=classes.count(NodeClass.PROOF_GRAPH),
        dead_end=classes.count(NodeClass.DEAD_END),
        expanded_off_graph=classes.count(NodeClass.EXPANDED_OFF_GRAPH),
        labelled_expanded_off_graph=sum(
            state.node_class == NodeClass.EXPANDED_OFF_GRAPH and labelled(state, config) for state in benchmark.states
        ),
        never_expanded=classes.count(NodeClass.NEVER_EXPANDED),
        groups_with_proof_state=sum(
            any(benchmark.states[index].node_class == NodeClass.PROOF_GRAPH for index in group.state_indices)
            for group in benchmark.groups
        ),
        trees=len({(state.run, state.problem_name) for state in benchmark.states}),
    )
