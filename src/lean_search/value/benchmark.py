"""A fixed value benchmark of sibling groups from labelled search graphs, and its metrics for any value estimates."""

import gzip
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from lean_search.search.graph_labels import GraphLabels, NodeClass
from lean_search.search.records import TreeRecord, from_json_object, to_json
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueEstimate,
    ValueTarget,
    recorded_estimates,
)
from lean_search.value.metrics import roc_auc, spearman_correlation
from lean_search.value.ranking import expanded_nodes

GROUP_PRIORITY = {NodeClass.PROOF_GRAPH: 0, NodeClass.DEAD_END: 1}


@dataclass(frozen=True)
class BenchmarkConfig:
    max_states_per_tree: int = 32
    max_states: int = 5000
    calibration_bins: int = 10


@dataclass(frozen=True)
class BenchmarkState:
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
    problem_name: str
    parent_id: int
    state_indices: tuple[int, ...]


@dataclass(frozen=True)
class ValueBenchmark:
    states: tuple[BenchmarkState, ...]
    groups: tuple[BenchmarkGroup, ...]


@dataclass(frozen=True)
class LabelledTree:
    record: TreeRecord
    labels: GraphLabels
    targets: Sequence[ValueTarget]


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


def build_benchmark(trees: Sequence[LabelledTree], config: BenchmarkConfig) -> ValueBenchmark:
    states: list[BenchmarkState] = []
    groups: list[BenchmarkGroup] = []
    for tree in sorted(trees, key=lambda tree: hashed(tree.record.problem_name)):
        chosen = tree_groups(tree, config.max_states_per_tree)
        tree_state_count = len({node_id for group in chosen for node_id in group.members})
        if len(states) + tree_state_count > config.max_states:
            continue
        targets = {target.node_id: target for target in tree.targets}
        index_by_node: dict[int, int] = {}
        for group in chosen:
            for node_id in group.members:
                if node_id not in index_by_node:
                    index_by_node[node_id] = len(states)
                    states.append(benchmark_state(tree, node_id, targets.get(node_id)))
            indices = tuple(index_by_node[node_id] for node_id in group.members)
            groups.append(BenchmarkGroup(tree.record.problem_name, group.parent_id, indices))
    return ValueBenchmark(tuple(states), tuple(groups))


def benchmark_state(tree: LabelledTree, node_id: int, target: ValueTarget | None) -> BenchmarkState:
    return BenchmarkState(
        problem_name=tree.record.problem_name,
        node_id=node_id,
        goals=tree.record.nodes[node_id].goals,
        node_class=tree.labels.node_classes[node_id],
        target_proof_probability=None if target is None else target.proof_probability,
        remaining_steps=tree.labels.remaining_steps[node_id],
        expanded_nodes=expanded_nodes(tree.labels, node_id) if tree.labels.expanded[node_id] else 0,
    )


def write_benchmark(path: Path, benchmark: ValueBenchmark) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write(to_json(benchmark))


def read_benchmark(path: Path) -> ValueBenchmark:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        return from_json_object(ValueBenchmark, json.load(file))


def recorded_benchmark_estimates(
    benchmark: ValueBenchmark, records: Mapping[str, TreeRecord], readout: RemainingStepsReadout
) -> list[ValueEstimate | None]:
    """The estimates the search recorded for each benchmark state (the value version that ran the search)."""
    per_tree = {name: recorded_estimates(record, readout) for name, record in records.items()}
    return [per_tree[state.problem_name][state.node_id] for state in benchmark.states]


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    states: int
    mean_predicted: float | None
    mean_target: float | None


@dataclass(frozen=True)
class RankingMetrics:
    groups_with_proof_state: int
    pairs: int
    # Proof-graph state scored above a sibling (ties count half), over all such sibling pairs and per sibling class.
    pairwise_accuracy: float | None
    over_dead_end_accuracy: float | None
    over_expanded_accuracy: float | None
    over_never_expanded_accuracy: float | None
    # Groups whose highest-scored state is on the proof graph, among groups that also hold an off-graph state.
    top_accuracy: float | None


@dataclass(frozen=True)
class CalibrationMetrics:
    # Proof-graph and dead-end states: Lean's anchors.
    anchor_states: int
    anchor_expected_calibration_error: float | None
    anchor_brier_score: float | None
    # Anchors plus averaged targets; with the value version that produced the averages this is partly circular.
    labelled_states: int
    labelled_expected_calibration_error: float | None
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
    states: int
    groups: int
    states_without_estimate: int
    ranking: RankingMetrics
    calibration: CalibrationMetrics
    separation: SeparationMetrics
    steps: StepMetrics


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def preference(first: ValueEstimate, second: ValueEstimate) -> float:
    """1 when the first scores higher (proof probability, then fewer steps), 0.5 for a tie."""
    first_key = (first.proof_probability, -first.remaining_steps)
    second_key = (second.proof_probability, -second.remaining_steps)
    if first_key == second_key:
        return 0.5
    return float(first_key > second_key)


def ranking_metrics(benchmark: ValueBenchmark, estimates: Sequence[ValueEstimate | None]) -> RankingMetrics:
    by_class: dict[NodeClass, list[float]] = {}
    top: list[float] = []
    groups_with_proof_state = 0
    for group in benchmark.groups:
        scored = [(benchmark.states[index], estimates[index]) for index in group.state_indices]
        scored = [(state, estimate) for state, estimate in scored if estimate is not None]
        proofs = [estimate for state, estimate in scored if state.node_class == NodeClass.PROOF_GRAPH]
        others = [(state, estimate) for state, estimate in scored if state.node_class != NodeClass.PROOF_GRAPH]
        if not proofs:
            continue
        groups_with_proof_state += 1
        for proof in proofs:
            for state, estimate in others:
                by_class.setdefault(state.node_class, []).append(preference(proof, estimate))
        if others:
            best_proof = max(proofs, key=lambda estimate: (estimate.proof_probability, -estimate.remaining_steps))
            top.append(min(preference(best_proof, estimate) for _, estimate in others))
    every_pair = [outcome for outcomes in by_class.values() for outcome in outcomes]
    return RankingMetrics(
        groups_with_proof_state=groups_with_proof_state,
        pairs=len(every_pair),
        pairwise_accuracy=mean(every_pair),
        over_dead_end_accuracy=mean(by_class.get(NodeClass.DEAD_END, [])),
        over_expanded_accuracy=mean(by_class.get(NodeClass.EXPANDED_OFF_GRAPH, [])),
        over_never_expanded_accuracy=mean(by_class.get(NodeClass.NEVER_EXPANDED, [])),
        top_accuracy=mean(top),
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


def calibration_metrics(
    benchmark: ValueBenchmark, estimates: Sequence[ValueEstimate | None], bin_count: int
) -> CalibrationMetrics:
    anchor_predicted: list[float] = []
    anchor_targets: list[float] = []
    labelled_predicted: list[float] = []
    labelled_targets: list[float] = []
    for state, estimate in zip(benchmark.states, estimates, strict=True):
        if estimate is None or state.target_proof_probability is None:
            continue
        labelled_predicted.append(estimate.proof_probability)
        labelled_targets.append(state.target_proof_probability)
        if state.node_class in (NodeClass.PROOF_GRAPH, NodeClass.DEAD_END):
            anchor_predicted.append(estimate.proof_probability)
            anchor_targets.append(state.target_proof_probability)
    anchor_bins = reliability_bins(anchor_predicted, anchor_targets, bin_count)
    brier = [(predicted - target) ** 2 for predicted, target in zip(anchor_predicted, anchor_targets, strict=True)]
    return CalibrationMetrics(
        anchor_states=len(anchor_predicted),
        anchor_expected_calibration_error=expected_calibration_error(anchor_bins),
        anchor_brier_score=mean(brier),
        labelled_states=len(labelled_predicted),
        labelled_expected_calibration_error=expected_calibration_error(
            reliability_bins(labelled_predicted, labelled_targets, bin_count)
        ),
        anchor_bins=anchor_bins,
    )


def separation_metrics(benchmark: ValueBenchmark, estimates: Sequence[ValueEstimate | None]) -> SeparationMetrics:
    proof_scores: list[float] = []
    expanded_scores: list[float] = []
    dead_scores: list[float] = []
    for state, estimate in zip(benchmark.states, estimates, strict=True):
        if estimate is None:
            continue
        match state.node_class:
            case NodeClass.PROOF_GRAPH:
                proof_scores.append(estimate.proof_probability)
                if state.expanded_nodes:
                    expanded_scores.append(estimate.proof_probability)
            case NodeClass.EXPANDED_OFF_GRAPH:
                expanded_scores.append(estimate.proof_probability)
            case NodeClass.DEAD_END:
                dead_scores.append(estimate.proof_probability)
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


def step_metrics(benchmark: ValueBenchmark, estimates: Sequence[ValueEstimate | None]) -> StepMetrics:
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
    benchmark: ValueBenchmark, estimates: Sequence[ValueEstimate | None], config: BenchmarkConfig
) -> BenchmarkMetrics:
    assert len(estimates) == len(benchmark.states)
    return BenchmarkMetrics(
        states=len(benchmark.states),
        groups=len(benchmark.groups),
        states_without_estimate=sum(estimate is None for estimate in estimates),
        ranking=ranking_metrics(benchmark, estimates),
        calibration=calibration_metrics(benchmark, estimates, config.calibration_bins),
        separation=separation_metrics(benchmark, estimates),
        steps=step_metrics(benchmark, estimates),
    )


@dataclass(frozen=True)
class BenchmarkComposition:
    states: int
    groups: int
    proof_graph: int
    dead_end: int
    expanded_off_graph: int
    never_expanded: int
    groups_with_proof_state: int
    trees: int


def benchmark_composition(benchmark: ValueBenchmark) -> BenchmarkComposition:
    classes = [state.node_class for state in benchmark.states]
    return BenchmarkComposition(
        states=len(benchmark.states),
        groups=len(benchmark.groups),
        proof_graph=classes.count(NodeClass.PROOF_GRAPH),
        dead_end=classes.count(NodeClass.DEAD_END),
        expanded_off_graph=classes.count(NodeClass.EXPANDED_OFF_GRAPH),
        never_expanded=classes.count(NodeClass.NEVER_EXPANDED),
        groups_with_proof_state=sum(
            any(benchmark.states[index].node_class == NodeClass.PROOF_GRAPH for index in group.state_indices)
            for group in benchmark.groups
        ),
        trees=len({state.problem_name for state in benchmark.states}),
    )
