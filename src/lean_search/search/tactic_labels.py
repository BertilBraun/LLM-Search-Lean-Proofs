"""Per-tactic labels of policy samples: the state each executed tactic reached, judged against the proof graph."""

import dataclasses
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.lean.hypotheses import adds_only_redundant_hypotheses
from lean_search.search.graph_labels import (
    EdgeKind,
    GoalKey,
    GraphLabels,
    NodeClass,
    ancestor_ids,
    goal_key,
    nodes_by_goal_key,
)
from lean_search.search.records import TreeRecord
from lean_search.search.tree import Edge, EdgeOutcome, StepSource


class TacticLabel(StrEnum):
    PROOF_GRAPH = "proof_graph"
    # A dead end, or an expanded state off the proof graph whose subtree has enough expanded nodes to be evidence.
    OFF_GRAPH = "off_graph"
    # A state never expanded, or expanded off the proof graph with live children and too few expanded nodes.
    UNKNOWN = "unknown"
    # Unchanged, or back to an earlier state of its path: the block's own states, the node and its ancestors.
    NO_PROGRESS = "no_progress"
    # Adds only hypotheses whose types the context already has, or reflexive ones.
    REDUNDANT_HYPOTHESIS = "redundant_hypothesis"
    # The first tactic Lean rejected (timeouts included), an unverified proof's last one, a sample without a block.
    FAILING = "failing"
    # After the first failing tactic: never evaluated.
    MASKED = "masked"


@dataclass(frozen=True)
class TacticOutcome:
    label: TacticLabel
    # The node whose state the tactic reached, when a node has it.
    node_id: int | None = None
    # Goals fewer than before the tactic.
    goals_closed: int = 0
    # On the proof graph: the fewest top-level tactics from the state to a verified proof (0 once proved).
    remaining_steps: int | None = None


@dataclass(frozen=True)
class TacticLabelCounts:
    proof_graph: int = 0
    off_graph: int = 0
    unknown: int = 0
    no_progress: int = 0
    redundant_hypothesis: int = 0
    failing: int = 0
    masked: int = 0

    @staticmethod
    def of(labels: Iterable[TacticLabel]) -> "TacticLabelCounts":
        return TacticLabelCounts(**Counter(label.value for label in labels))

    @property
    def total(self) -> int:
        return sum(dataclasses.astuple(self))


class TacticGraph:
    """The states of one labelled search graph by goal key, at tactic granularity."""

    def __init__(self, record: TreeRecord, labels: GraphLabels, min_expanded_nodes: int) -> None:
        self.record = record
        self.labels = labels
        self.min_expanded_nodes = min_expanded_nodes
        self.node_by_key = nodes_by_goal_key(record)
        # Intermediate states of edges on a route to a proof.
        self.proof_graph_keys: set[GoalKey] = set()
        # Proof-graph states by goal key at their fewest remaining steps: nodes and intermediate states alike.
        self.steps_by_key: dict[GoalKey, int] = {}
        for node in record.nodes:
            if node.goals and (steps := labels.remaining_steps[node.node_id]) is not None:
                self.add_steps(goal_key(node.goals), steps)
        for edge in record.edges:
            if not self.on_route_to_proof(edge):
                continue
            for index, goals in enumerate(edge.tactic_goals):
                if goals:
                    self.add_steps(goal_key(goals), self.route_steps(edge, index))
                    if index < edge.applied_tactics - 1:
                        self.proof_graph_keys.add(goal_key(goals))

    def add_steps(self, key: GoalKey, steps: int) -> None:
        self.steps_by_key[key] = min(steps, self.steps_by_key.get(key, steps))

    def on_route_to_proof(self, edge: Edge) -> bool:
        return (
            self.labels.edges[edge.edge_id].kind.is_forward
            and edge.target_id is not None
            and self.labels.node_classes[edge.target_id] == NodeClass.PROOF_GRAPH
        )

    def route_steps(self, edge: Edge, index: int) -> int:
        """The remaining steps after the edge's tactic `index`, on its route to a proof."""
        assert edge.target_id is not None
        target_steps = self.labels.remaining_steps[edge.target_id]
        assert target_steps is not None, edge.edge_id
        return target_steps + edge.applied_tactics - index - 1

    def is_on_proof_graph(self, key: GoalKey, node_id: int | None) -> bool:
        on_graph_node = node_id is not None and self.labels.node_classes[node_id] == NodeClass.PROOF_GRAPH
        return on_graph_node or key in self.proof_graph_keys

    def remaining_steps(self, key: GoalKey, node_id: int | None) -> int:
        """The shortest of the state's distances: its node's and those of every proof-graph state with its key."""
        node_steps = None if node_id is None else self.labels.remaining_steps[node_id]
        return min(steps for steps in (node_steps, self.steps_by_key.get(key)) if steps is not None)

    def is_off_graph_evidence(self, node_id: int | None) -> bool:
        """A dead end, or expanded with `min_expanded_nodes` expanded nodes in its subtree counting itself."""
        if node_id is None or not self.labels.expanded[node_id]:
            return False
        if self.labels.node_classes[node_id] == NodeClass.DEAD_END:
            return True
        return 1 + len(self.labels.expanded_descendants[node_id]) >= self.min_expanded_nodes

    def edge_tactics(self, edge: Edge) -> tuple[TacticOutcome, ...]:
        """Every executed tactic of an executed edge, in order; a sample without tactics counts as one failing."""
        assert not edge.tactic_goals or len(edge.tactic_goals) == edge.applied_tactics, edge.edge_id
        failed = edge.failure is not None or edge.outcome == EdgeOutcome.REJECTED
        count = max(len(edge.executed_tactics) or edge.total_tactics, edge.applied_tactics + failed)
        parent = self.record.nodes[edge.parent_id]
        ancestors = {parent.node_id} | ancestor_ids(self.record.nodes, parent.node_id)
        on_route = self.on_route_to_proof(edge)
        earlier: list[tuple[str, ...]] = [parent.goals]
        earlier_keys = {goal_key(parent.goals)}
        previous: tuple[str, ...] | None = parent.goals
        outcomes = []
        for index in range(count):
            if index >= edge.applied_tactics:
                outcomes.append(
                    TacticOutcome(TacticLabel.FAILING if index == edge.applied_tactics else TacticLabel.MASKED)
                )
                continue
            last = index == edge.applied_tactics - 1
            goals = self.tactic_goals(edge, index, last)
            if goals is None:
                outcomes.append(
                    TacticOutcome(TacticLabel.PROOF_GRAPH, remaining_steps=self.route_steps(edge, index))
                    if on_route
                    else TacticOutcome(TacticLabel.UNKNOWN)
                )
            else:
                key = goal_key(goals)
                node_id = edge.target_id if last else self.node_by_key.get(key)
                outcomes.append(self.judge(goals, key, node_id, previous, earlier, earlier_keys, ancestors))
                earlier.append(goals)
                earlier_keys.add(key)
            previous = goals
        return tuple(outcomes)

    def tactic_goals(self, edge: Edge, index: int, last: bool) -> tuple[str, ...] | None:
        if edge.tactic_goals:
            return edge.tactic_goals[index]
        if last:
            assert edge.target_id is not None, edge.edge_id
            return self.record.nodes[edge.target_id].goals
        return None

    def judge(
        self,
        goals: tuple[str, ...],
        key: GoalKey,
        node_id: int | None,
        previous: tuple[str, ...] | None,
        earlier: Sequence[tuple[str, ...]],
        earlier_keys: set[GoalKey],
        ancestors: set[int],
    ) -> TacticOutcome:
        closed = 0 if previous is None else max(0, len(previous) - len(goals))
        if not goals:
            proved = node_id is not None and self.labels.node_classes[node_id] == NodeClass.PROOF_GRAPH
            if proved:
                return TacticOutcome(TacticLabel.PROOF_GRAPH, node_id, closed, remaining_steps=0)
            return TacticOutcome(TacticLabel.FAILING, node_id, closed)
        if node_id in ancestors or key in earlier_keys:
            return TacticOutcome(TacticLabel.NO_PROGRESS, node_id)
        if any(adds_only_redundant_hypotheses(state, goals) for state in earlier):
            return TacticOutcome(TacticLabel.REDUNDANT_HYPOTHESIS, node_id)
        if self.is_on_proof_graph(key, node_id):
            return TacticOutcome(TacticLabel.PROOF_GRAPH, node_id, closed, self.remaining_steps(key, node_id))
        if self.is_off_graph_evidence(node_id):
            return TacticOutcome(TacticLabel.OFF_GRAPH, node_id)
        return TacticOutcome(TacticLabel.UNKNOWN, node_id)


def policy_tactics(
    record: TreeRecord, labels: GraphLabels, min_expanded_nodes: int
) -> dict[int, tuple[TacticOutcome, ...]]:
    """Per executed edge of a policy sample (repeats share it), its tactics; infrastructure failures excluded."""
    graph = TacticGraph(record, labels, min_expanded_nodes)
    outcomes: dict[int, tuple[TacticOutcome, ...]] = {}
    for label in labels.edges:
        if label.source != StepSource.POLICY or label.effective_kind == EdgeKind.INFRASTRUCTURE_FAILURE:
            continue
        if label.executed_edge_id not in outcomes:
            outcomes[label.executed_edge_id] = graph.edge_tactics(record.edges[label.executed_edge_id])
    return outcomes
