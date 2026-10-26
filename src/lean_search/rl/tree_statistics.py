"""Per-tree counts of the labelled search graph, its value targets and GRPO groups, summable into run totals."""

import dataclasses
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig
from lean_search.search.graph_labels import EdgeKind, EdgeLabel, GraphLabels, NodeClass
from lean_search.search.records import TreeRecord
from lean_search.search.tree import NodeStatus, StepSource
from lean_search.value.graph_targets import TargetSource, ValueTarget

# Upper bounds of the size buckets 1, 2-3, 4-7, 8-15, 16-31, 32+.
SIZE_BUCKET_LIMITS = (1, 3, 7, 15, 31)


@dataclass(frozen=True)
class EdgeKindCounts:
    lean_error: int = 0
    heartbeat_timeout: int = 0
    wall_clock_timeout: int = 0
    forbidden: int = 0
    infrastructure_failure: int = 0
    new_state: int = 0
    unverified_proof: int = 0
    no_progress: int = 0
    back_to_ancestor: int = 0
    sibling_state: int = 0
    transposition: int = 0
    repeat: int = 0

    @staticmethod
    def of(kinds: Iterable[EdgeKind]) -> "EdgeKindCounts":
        counts = Counter(kind.value for kind in kinds)
        return EdgeKindCounts(**counts)

    @property
    def total(self) -> int:
        return sum(dataclasses.astuple(self))


@dataclass(frozen=True)
class SizeHistogram:
    # Counts in the buckets 1, 2-3, 4-7, 8-15, 16-31, 32+.
    buckets: tuple[int, ...] = (0,) * (len(SIZE_BUCKET_LIMITS) + 1)
    total_size: int = 0

    @staticmethod
    def of(sizes: Iterable[int]) -> "SizeHistogram":
        buckets = [0] * (len(SIZE_BUCKET_LIMITS) + 1)
        total = 0
        for size in sizes:
            buckets[sum(size > limit for limit in SIZE_BUCKET_LIMITS)] += 1
            total += size
        return SizeHistogram(tuple(buckets), total)

    @property
    def mean_size(self) -> float:
        count = sum(self.buckets)
        return self.total_size / count if count else 0.0


@dataclass(frozen=True)
class GraphStatistics:
    trees: int
    solved_trees: int
    nodes: int
    expanded_nodes: int
    never_expanded_nodes: int
    edges: EdgeKindCounts
    policy_edges: EdgeKindCounts
    automation_edges: EdgeKindCounts
    # Policy edges weighted by the samples behind them.
    policy_samples: EdgeKindCounts
    # A valid prefix reached a state, then a later tactic failed.
    partial_failures: int
    repeats_of_failed_automation: int
    forced_edges: int
    proof_path_nodes: int
    proof_graph_nodes: int
    off_path_proof_graph_nodes: int
    transpositions_into_proof_graph: int
    off_path_transpositions_into_proof_graph: int
    off_path_transposition_sources: int
    # Transpositions from off-path nodes into a node of the found proof path.
    off_path_transpositions_into_proof_path: int
    dead_ends: int
    expanded_off_graph_nodes: int
    proof_graph_targets: int
    dead_end_targets: int
    averaged_targets: int
    # Expanded off-graph nodes without an expanded descendant, hence without a target.
    expanded_without_target: int
    averaged_descendants: SizeHistogram
    # Expanded nodes including the node itself, for every expanded node.
    expanded_subtree_sizes: SizeHistogram
    groups: int
    group_samples: int
    groups_with_mixed_rewards: int
    outcome_groups_with_mixed_rewards: int
    local_reward: float
    global_reward: float
    # Positive local reward on samples whose state reached is off the proof graph.
    positive_local_reward: float
    positive_local_reward_off_proof_graph: float


@dataclass(frozen=True)
class TreeStatistics:
    problem_name: str
    statistics: GraphStatistics


def class_count(labels: GraphLabels, node_class: NodeClass) -> int:
    return sum(current == node_class for current in labels.node_classes)


def is_into_proof_graph(edge: EdgeLabel, labels: GraphLabels) -> bool:
    return (
        edge.kind == EdgeKind.TRANSPOSITION
        and edge.target_id is not None
        and labels.node_classes[edge.target_id] == NodeClass.PROOF_GRAPH
    )


def graph_statistics(
    record: TreeRecord,
    labels: GraphLabels,
    targets: Sequence[ValueTarget],
    groups: Sequence[PolicyGroup],
    outcome_groups: Sequence[PolicyGroup],
    reward_config: RewardConfig,
) -> GraphStatistics:
    on_path = {node.node_id for node in record.nodes if node.status == NodeStatus.PROVED}
    policy = [edge for edge in labels.edges if edge.source == StepSource.POLICY]
    into_proof = [edge for edge in labels.edges if is_into_proof_graph(edge, labels)]
    off_path_into_proof = [edge for edge in into_proof if edge.parent_id not in on_path]
    sources = Counter(target.source for target in targets)
    expanded_off_graph = [
        node_id for node_id, node_class in enumerate(labels.node_classes) if node_class == NodeClass.EXPANDED_OFF_GRAPH
    ]
    averaged = [target for target in targets if target.source == TargetSource.AVERAGED]
    samples = [sample for group in groups for sample in group.samples]
    local = [sample.components.local * sample.multiplicity for sample in samples]
    off_graph = [
        sample.target_id is None or labels.node_classes[sample.target_id] != NodeClass.PROOF_GRAPH for sample in samples
    ]
    proof_graph_nodes = class_count(labels, NodeClass.PROOF_GRAPH)
    return GraphStatistics(
        trees=1,
        solved_trees=int(record.result.proved),
        nodes=len(record.nodes),
        expanded_nodes=sum(labels.expanded),
        never_expanded_nodes=class_count(labels, NodeClass.NEVER_EXPANDED),
        edges=EdgeKindCounts.of(edge.kind for edge in labels.edges),
        policy_edges=EdgeKindCounts.of(edge.kind for edge in policy),
        automation_edges=EdgeKindCounts.of(edge.kind for edge in labels.edges if edge.source == StepSource.AUTOMATION),
        policy_samples=EdgeKindCounts.of(edge.kind for edge in policy for _ in range(edge.sample_count)),
        partial_failures=sum(edge.partial and edge.kind != EdgeKind.REPEAT for edge in labels.edges),
        repeats_of_failed_automation=sum(edge.repeats_failed_automation for edge in labels.edges),
        forced_edges=sum(edge.forced for edge in record.edges),
        proof_path_nodes=len(on_path),
        proof_graph_nodes=proof_graph_nodes,
        off_path_proof_graph_nodes=sum(
            node_class == NodeClass.PROOF_GRAPH and node_id not in on_path
            for node_id, node_class in enumerate(labels.node_classes)
        ),
        transpositions_into_proof_graph=len(into_proof),
        off_path_transpositions_into_proof_graph=len(off_path_into_proof),
        off_path_transposition_sources=len({edge.parent_id for edge in off_path_into_proof}),
        off_path_transpositions_into_proof_path=sum(edge.target_id in on_path for edge in off_path_into_proof),
        dead_ends=class_count(labels, NodeClass.DEAD_END),
        expanded_off_graph_nodes=len(expanded_off_graph),
        proof_graph_targets=sources[TargetSource.PROOF_GRAPH],
        dead_end_targets=sources[TargetSource.DEAD_END],
        averaged_targets=sources[TargetSource.AVERAGED],
        expanded_without_target=len(expanded_off_graph) - sources[TargetSource.AVERAGED],
        averaged_descendants=SizeHistogram.of(target.expanded_descendants for target in averaged),
        expanded_subtree_sizes=SizeHistogram.of(
            1 + len(descendants) for descendants in labels.expanded_descendants.values()
        ),
        groups=len(groups),
        group_samples=sum(group.sample_count for group in groups),
        groups_with_mixed_rewards=sum(group.has_mixed_rewards for group in groups),
        outcome_groups_with_mixed_rewards=sum(group.has_mixed_rewards for group in outcome_groups),
        local_reward=sum(local),
        global_reward=sum(
            reward_config.global_weight * sample.components.global_value * sample.multiplicity for sample in samples
        ),
        positive_local_reward=sum(max(0.0, value) for value in local),
        positive_local_reward_off_proof_graph=sum(
            max(0.0, value) for value, off in zip(local, off_graph, strict=True) if off
        ),
    )


def summed(first: object, second: object) -> object:
    match first:
        case EdgeKindCounts() | SizeHistogram() | GraphStatistics():
            return type(first)(
                **{
                    field.name: summed(getattr(first, field.name), getattr(second, field.name))
                    for field in dataclasses.fields(first)
                }
            )
        case tuple():
            assert isinstance(second, tuple)
            return tuple(left + right for left, right in zip(first, second, strict=True))
        case int() | float():
            assert isinstance(second, int | float)
            return first + second
        case _:
            raise AssertionError(f"cannot sum {first!r}")


def total_statistics(statistics: Sequence[GraphStatistics]) -> GraphStatistics:
    total = statistics[0]
    for current in statistics[1:]:
        total = summed(total, current)
        assert isinstance(total, GraphStatistics)
    return total
