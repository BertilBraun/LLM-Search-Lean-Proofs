"""Labels of a finished search graph: edge kinds, the proof graph, dead ends and expanded descendants."""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.search.records import NodeRecord, TreeRecord
from lean_search.search.tree import Edge, EdgeOutcome, FailureKind, NodeStatus, StepSource


class EdgeKind(StrEnum):
    LEAN_ERROR = "lean_error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    FORBIDDEN = "forbidden"
    # The block named something that does not exist; rejected before Lean ran.
    UNKNOWN_IDENTIFIER = "unknown_identifier"
    # A policy sample without a usable block (none, cut off at the token cap, empty or forbidden).
    UNPARSED_SAMPLE = "unparsed_sample"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    NEW_STATE = "new_state"
    # Lean reported no goals left, but the proof failed verification.
    UNVERIFIED_PROOF = "unverified_proof"
    NO_PROGRESS = "no_progress"
    BACK_TO_ANCESTOR = "back_to_ancestor"
    SIBLING_STATE = "sibling_state"
    TRANSPOSITION = "transposition"
    REPEAT = "repeat"

    @property
    def is_failure(self) -> bool:
        return self in FAILURE_KINDS

    @property
    def is_forward(self) -> bool:
        return self in FORWARD_KINDS

    @property
    def is_no_progress(self) -> bool:
        return self in (EdgeKind.NO_PROGRESS, EdgeKind.BACK_TO_ANCESTOR)


FAILURE_KINDS = frozenset(
    {
        EdgeKind.LEAN_ERROR,
        EdgeKind.HEARTBEAT_TIMEOUT,
        EdgeKind.WALL_CLOCK_TIMEOUT,
        EdgeKind.FORBIDDEN,
        EdgeKind.UNKNOWN_IDENTIFIER,
        EdgeKind.UNPARSED_SAMPLE,
        EdgeKind.INFRASTRUCTURE_FAILURE,
        EdgeKind.UNVERIFIED_PROOF,
    }
)
# The only routes: no-progress edges and edges back to an ancestor never count.
FORWARD_KINDS = frozenset({EdgeKind.NEW_STATE, EdgeKind.SIBLING_STATE, EdgeKind.TRANSPOSITION})


class NodeClass(StrEnum):
    PROOF_GRAPH = "proof_graph"
    DEAD_END = "dead_end"
    EXPANDED_OFF_GRAPH = "expanded_off_graph"
    NEVER_EXPANDED = "never_expanded"
    UNVERIFIED_PROOF = "unverified_proof"


@dataclass(frozen=True)
class EdgeLabel:
    edge_id: int
    parent_id: int
    source: StepSource
    text: str
    sample_count: int
    # REPEAT for a repeated text; the outcome fields below are those of the executed edge it repeats.
    kind: EdgeKind
    executed_edge_id: int
    effective_kind: EdgeKind
    executed_source: StepSource
    target_id: int | None
    failure_kind: FailureKind | None
    applied_tactics: int
    total_tactics: int

    @property
    def partial(self) -> bool:
        """A valid prefix reached a state, then a later tactic of the block failed."""
        return self.target_id is not None and self.failure_kind is not None

    @property
    def repeats_failed_automation(self) -> bool:
        return (
            self.kind == EdgeKind.REPEAT
            and self.executed_source == StepSource.AUTOMATION
            and self.effective_kind.is_failure
        )


@dataclass(frozen=True)
class ReachedNode:
    node_id: int
    distance: int


@dataclass(frozen=True)
class GraphLabels:
    edges: tuple[EdgeLabel, ...]
    node_classes: tuple[NodeClass, ...]
    # Fewest forward edges to a verified proof; None off the proof graph.
    remaining_steps: tuple[int | None, ...]
    expanded: tuple[bool, ...]
    # Distinct targets of each node's forward edges.
    successors: Mapping[int, tuple[int, ...]]
    # Per expanded node: the other expanded nodes reachable over forward edges, each once, at its fewest edges.
    expanded_descendants: Mapping[int, tuple[ReachedNode, ...]]

    @property
    def solved(self) -> bool:
        return any(node_class == NodeClass.PROOF_GRAPH for node_class in self.node_classes)

    def edges_by_parent(self) -> dict[int, list[EdgeLabel]]:
        by_parent: dict[int, list[EdgeLabel]] = {}
        for edge in self.edges:
            by_parent.setdefault(edge.parent_id, []).append(edge)
        return by_parent


def ancestor_ids(nodes: Sequence[NodeRecord], node_id: int) -> set[int]:
    ancestors = set()
    current = nodes[node_id].parent_id
    while current is not None:
        ancestors.add(current)
        current = nodes[current].parent_id
    return ancestors


def is_verified_proof(node: NodeRecord) -> bool:
    return not node.goals and node.status == NodeStatus.PROVED


def own_kind(edge: Edge, nodes: Sequence[NodeRecord]) -> EdgeKind:
    match edge.outcome:
        case EdgeOutcome.REPEATED:
            return EdgeKind.REPEAT
        case EdgeOutcome.REJECTED:
            return EdgeKind.FORBIDDEN if edge.failure is None else failure_edge_kind(edge.failure.kind)
        case EdgeOutcome.FAILED:
            assert edge.failure is not None, edge.edge_id
            return failure_edge_kind(edge.failure.kind)
        case EdgeOutcome.CHILD:
            assert edge.target_id is not None, edge.edge_id
            target = nodes[edge.target_id]
            return (
                EdgeKind.UNVERIFIED_PROOF if not target.goals and not is_verified_proof(target) else EdgeKind.NEW_STATE
            )
        case EdgeOutcome.DUPLICATE:
            assert edge.target_id is not None, edge.edge_id
            if edge.target_id == edge.parent_id:
                return EdgeKind.NO_PROGRESS
            if edge.target_id in ancestor_ids(nodes, edge.parent_id):
                return EdgeKind.BACK_TO_ANCESTOR
            if nodes[edge.target_id].parent_id == edge.parent_id:
                return EdgeKind.SIBLING_STATE
            return EdgeKind.TRANSPOSITION


def failure_edge_kind(kind: FailureKind) -> EdgeKind:
    match kind:
        case FailureKind.ERROR:
            return EdgeKind.LEAN_ERROR
        case FailureKind.HEARTBEAT_TIMEOUT:
            return EdgeKind.HEARTBEAT_TIMEOUT
        case FailureKind.WALL_CLOCK_TIMEOUT:
            return EdgeKind.WALL_CLOCK_TIMEOUT
        case FailureKind.FORBIDDEN:
            return EdgeKind.FORBIDDEN
        case FailureKind.UNKNOWN_IDENTIFIER:
            return EdgeKind.UNKNOWN_IDENTIFIER
        case FailureKind.UNPARSED:
            return EdgeKind.UNPARSED_SAMPLE
        case FailureKind.REPL_FAILURE:
            return EdgeKind.INFRASTRUCTURE_FAILURE


def edge_labels(record: TreeRecord) -> tuple[EdgeLabel, ...]:
    kinds = [own_kind(edge, record.nodes) for edge in record.edges]
    labels = []
    for edge, kind in zip(record.edges, kinds, strict=True):
        executed = edge
        while executed.repeat_of is not None:
            executed = record.edges[executed.repeat_of]
        labels.append(
            EdgeLabel(
                edge_id=edge.edge_id,
                parent_id=edge.parent_id,
                source=edge.source,
                text=edge.text,
                sample_count=edge.sample_count,
                kind=kind,
                executed_edge_id=executed.edge_id,
                effective_kind=kinds[executed.edge_id],
                executed_source=executed.source,
                target_id=executed.target_id,
                failure_kind=None if executed.failure is None else executed.failure.kind,
                applied_tactics=executed.applied_tactics,
                total_tactics=executed.total_tactics,
            )
        )
    return tuple(labels)


def forward_successors(edges: Sequence[EdgeLabel]) -> dict[int, tuple[int, ...]]:
    targets: dict[int, dict[int, None]] = {}
    for edge in edges:
        if edge.kind.is_forward:
            assert edge.target_id is not None
            targets.setdefault(edge.parent_id, {})[edge.target_id] = None
    return {node_id: tuple(node_targets) for node_id, node_targets in targets.items()}


def reverse(successors: Mapping[int, Sequence[int]]) -> dict[int, list[int]]:
    predecessors: dict[int, list[int]] = {}
    for node_id, targets in successors.items():
        for target_id in targets:
            predecessors.setdefault(target_id, []).append(node_id)
    return predecessors


def proof_distances(record: TreeRecord, predecessors: Mapping[int, Sequence[int]]) -> dict[int, int]:
    distances = {node.node_id: 0 for node in record.nodes if is_verified_proof(node)}
    queue = deque(distances)
    while queue:
        node_id = queue.popleft()
        for predecessor in predecessors.get(node_id, ()):
            if predecessor not in distances:
                distances[predecessor] = distances[node_id] + 1
                queue.append(predecessor)
    return distances


def dead_end_ids(
    record: TreeRecord,
    edges: Sequence[EdgeLabel],
    on_proof_graph: Mapping[int, int],
    successors: Mapping[int, Sequence[int]],
) -> set[int]:
    """Fully expanded nodes without a new state whose transpositions (if any) only reach other dead ends."""
    infrastructure_failures = {edge.parent_id for edge in edges if edge.kind == EdgeKind.INFRASTRUCTURE_FAILURE}
    candidates = {
        node.node_id
        for node in record.nodes
        if node.goals
        and node.expansion_index is not None
        and node.status != NodeStatus.OPEN
        and not any(record.nodes[child_id].goals for child_id in node.child_ids)
        and node.node_id not in on_proof_graph
        and node.node_id not in infrastructure_failures
    }
    predecessors = reverse(successors)
    live = [node.node_id for node in record.nodes if node.node_id not in candidates]
    while live:
        for predecessor in predecessors.get(live.pop(), ()):
            if predecessor in candidates:
                candidates.remove(predecessor)
                live.append(predecessor)
    return candidates


def reached_expanded(
    start_id: int, successors: Mapping[int, Sequence[int]], expanded: Sequence[bool]
) -> tuple[ReachedNode, ...]:
    distances = {start_id: 0}
    queue = deque([start_id])
    while queue:
        node_id = queue.popleft()
        for target_id in successors.get(node_id, ()):
            if target_id not in distances:
                distances[target_id] = distances[node_id] + 1
                queue.append(target_id)
    return tuple(
        ReachedNode(node_id, distance)
        for node_id, distance in distances.items()
        if node_id != start_id and expanded[node_id]
    )


def node_class(
    node: NodeRecord, on_proof_graph: Mapping[int, int], dead_ends: set[int], expanded: Sequence[bool]
) -> NodeClass:
    if node.node_id in on_proof_graph:
        return NodeClass.PROOF_GRAPH
    if not node.goals:
        return NodeClass.UNVERIFIED_PROOF
    if node.node_id in dead_ends:
        return NodeClass.DEAD_END
    if expanded[node.node_id]:
        return NodeClass.EXPANDED_OFF_GRAPH
    return NodeClass.NEVER_EXPANDED


def label_graph(record: TreeRecord) -> GraphLabels:
    edges = edge_labels(record)
    successors = forward_successors(edges)
    on_proof_graph = proof_distances(record, reverse(successors))
    dead_ends = dead_end_ids(record, edges, on_proof_graph, successors)
    expanded = tuple(node.expansion_index is not None for node in record.nodes)
    return GraphLabels(
        edges=edges,
        node_classes=tuple(node_class(node, on_proof_graph, dead_ends, expanded) for node in record.nodes),
        remaining_steps=tuple(on_proof_graph.get(node.node_id) for node in record.nodes),
        expanded=expanded,
        successors=successors,
        expanded_descendants={
            node.node_id: reached_expanded(node.node_id, successors, expanded)
            for node in record.nodes
            if expanded[node.node_id]
        },
    )
