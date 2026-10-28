"""Per-tree counts of the labelled search graph, its tactics, proofs, value targets and GRPO groups, summable."""

import dataclasses
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from lean_search.rl.advantages import CreditMode, group_advantages
from lean_search.rl.grpo_groups import PolicyGroup
from lean_search.search.graph_labels import EdgeKind, EdgeLabel, GraphLabels, NodeClass, is_verified_proof
from lean_search.search.records import NodeRecord, TreeRecord
from lean_search.search.tactic_labels import TacticLabelCounts, TacticOutcome
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
    unknown_identifier: int = 0
    unparsed_sample: int = 0
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
    off_graph_targets: int
    # Targets whose value part q averages expanded descendants; the others use their own estimate (or have no q).
    targets_averaging_descendants: int
    targets_without_value_part: int
    # Expanded states with goals that the per-tree cap left without a target.
    expanded_without_target: int
    # Expanded nodes including the node itself, for every off-graph target.
    off_graph_subtree_sizes: SizeHistogram
    # Expanded nodes including the node itself, for every expanded node.
    expanded_subtree_sizes: SizeHistogram
    # Tactics of every policy sample (infrastructure failures left out) and of the groups' samples, sample-weighted.
    policy_tactics: TacticLabelCounts
    group_tactics: TacticLabelCounts
    groups: int
    group_samples: int
    # Groups with a non-zero per-tactic advantage.
    groups_with_signal: int
    # Sums of (1 − λ) · G and λ · L over the groups' known tactics, sample-weighted.
    global_reward: float
    local_reward: float
    # Verified proofs, and their tactics and blocks along the tree path that found them.
    proofs: int
    proof_tactics: int
    proof_blocks: int
    # Expansions after the first proof, the proofs and proof-graph nodes they created, and exploration draws.
    harvest_expansions: int
    harvest_proofs: int
    harvest_proof_graph_nodes: int
    exploration_expansions: int


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


def path_tactics(record: TreeRecord, node: NodeRecord) -> int:
    tactics = 0
    while node.edge_id is not None:
        tactics += record.edges[node.edge_id].applied_tactics
        assert node.parent_id is not None
        node = record.nodes[node.parent_id]
    return tactics


def is_harvested(record: TreeRecord, node: NodeRecord) -> bool:
    """Created by one of the expansions after the first proof."""
    accounting = record.result.accounting
    first_harvest = accounting.expansions - accounting.harvest_expansions
    return (
        accounting.harvest_expansions > 0
        and node.edge_id is not None
        and record.edges[node.edge_id].expansion_index >= first_harvest
    )


def graph_statistics(
    record: TreeRecord,
    labels: GraphLabels,
    targets: Sequence[ValueTarget],
    tactics: Mapping[int, Sequence[TacticOutcome]],
    groups: Sequence[PolicyGroup],
) -> GraphStatistics:
    """`tactics` from `policy_tactics`, `groups` from `policy_groups`."""
    on_path = {node.node_id for node in record.nodes if node.status == NodeStatus.PROVED}
    policy = [edge for edge in labels.edges if edge.source == StepSource.POLICY]
    into_proof = [edge for edge in labels.edges if is_into_proof_graph(edge, labels)]
    off_path_into_proof = [edge for edge in into_proof if edge.parent_id not in on_path]
    sources = Counter(target.source for target in targets)
    expanded_with_goals = sum(
        expanded and bool(node.goals) for expanded, node in zip(labels.expanded, record.nodes, strict=True)
    )
    off_graph = [target for target in targets if target.source == TargetSource.OFF_GRAPH]
    samples = [sample for group in groups for sample in group.samples]
    known = [(parts, sample.multiplicity) for sample in samples for parts in sample.known]
    policy_samples = [
        edge
        for edge in policy
        if edge.effective_kind != EdgeKind.INFRASTRUCTURE_FAILURE
        for _ in range(edge.sample_count)
    ]
    proofs = [node for node in record.nodes if is_verified_proof(node)]
    proof_graph_nodes = class_count(labels, NodeClass.PROOF_GRAPH)
    accounting = record.result.accounting
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
        expanded_off_graph_nodes=class_count(labels, NodeClass.EXPANDED_OFF_GRAPH),
        proof_graph_targets=sources[TargetSource.PROOF_GRAPH],
        off_graph_targets=sources[TargetSource.OFF_GRAPH],
        targets_averaging_descendants=sum(bool(target.expanded_descendants) for target in targets),
        targets_without_value_part=sum(target.value_part is None for target in targets),
        expanded_without_target=expanded_with_goals - len(targets),
        off_graph_subtree_sizes=SizeHistogram.of(1 + target.expanded_descendants for target in off_graph),
        expanded_subtree_sizes=SizeHistogram.of(
            1 + len(descendants) for descendants in labels.expanded_descendants.values()
        ),
        policy_tactics=TacticLabelCounts.of(
            outcome.label for edge in policy_samples for outcome in tactics[edge.executed_edge_id]
        ),
        group_tactics=TacticLabelCounts.of(
            tactic.label for sample in samples for tactic in sample.tactics for _ in range(sample.multiplicity)
        ),
        groups=len(groups),
        group_samples=sum(group.sample_count for group in groups),
        groups_with_signal=sum(group_advantages(group).has_signal(CreditMode.PER_TACTIC) for group in groups),
        global_reward=sum(parts.global_part * weight for parts, weight in known),
        local_reward=sum(parts.local_part * weight for parts, weight in known),
        proofs=len(proofs),
        proof_tactics=sum(path_tactics(record, node) for node in proofs),
        proof_blocks=sum(node.depth for node in proofs),
        harvest_expansions=accounting.harvest_expansions,
        harvest_proofs=sum(is_harvested(record, node) for node in proofs),
        harvest_proof_graph_nodes=sum(
            node_class == NodeClass.PROOF_GRAPH and is_harvested(record, node)
            for node, node_class in zip(record.nodes, labels.node_classes, strict=True)
        ),
        exploration_expansions=accounting.exploration_expansions,
    )


def summed(first: object, second: object) -> object:
    match first:
        case EdgeKindCounts() | TacticLabelCounts() | SizeHistogram() | GraphStatistics():
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
