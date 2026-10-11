"""The search tree: nodes are full proof states, edges are every attempted step including failed ones."""

from dataclasses import dataclass, field
from enum import StrEnum

from lean_search.lean import LeanError, LeanTimeout, ProofState

MAX_FAILURE_MESSAGE_CHARACTERS = 1000


class StepSource(StrEnum):
    AUTOMATION = "automation"
    POLICY = "policy"


class NodeStatus(StrEnum):
    # Not fully expanded: on the frontier, at the depth cap, or cut off by a budget mid-expansion.
    OPEN = "open"
    EXPANDED = "expanded"
    PROVED = "proved"
    FAILED = "failed"


class EdgeOutcome(StrEnum):
    CHILD = "child"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    REJECTED = "rejected"
    REPEATED = "repeated"


class FailureKind(StrEnum):
    ERROR = "error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    message: str

    @staticmethod
    def from_lean(outcome: LeanError | LeanTimeout) -> "Failure":
        message = outcome.message[:MAX_FAILURE_MESSAGE_CHARACTERS]
        match outcome:
            case LeanTimeout(wall_clock=True):
                return Failure(FailureKind.WALL_CLOCK_TIMEOUT, message)
            case LeanTimeout():
                return Failure(FailureKind.HEARTBEAT_TIMEOUT, message)
            case LeanError():
                return Failure(FailureKind.ERROR, message)

    @property
    def is_timeout(self) -> bool:
        return self.kind in (FailureKind.HEARTBEAT_TIMEOUT, FailureKind.WALL_CLOCK_TIMEOUT)


@dataclass(slots=True)
class Node:
    node_id: int
    parent_id: int | None
    edge_id: int | None
    step: str | None
    source: StepSource | None
    log_probability: float | None
    depth: int
    state: ProofState
    created_seconds: float
    step_lean_seconds: float
    status: NodeStatus = NodeStatus.OPEN
    priority: float | None = None
    value_estimate: float | None = None
    child_ids: list[int] = field(default_factory=list)
    expansion_index: int | None = None
    expanded_seconds: float | None = None
    expansion_wall_seconds: float | None = None
    expansion_lean_seconds: float | None = None
    verification_problems: tuple[str, ...] = ()

    @property
    def goals(self) -> tuple[str, ...]:
        return self.state.goals

    @property
    def is_proved(self) -> bool:
        return self.state.is_proved


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: int
    parent_id: int
    expansion_index: int
    text: str
    source: StepSource
    log_probability: float | None
    prompt_tokens: int
    generated_tokens: int
    outcome: EdgeOutcome
    target_id: int | None
    applied_tactics: int
    total_tactics: int
    failure: Failure | None
    lean_seconds: float
    repeat_of: int | None


class SearchTree:
    def __init__(self, problem_name: str, root_state: ProofState, root_lean_seconds: float) -> None:
        self.problem_name = problem_name
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._node_by_goal_key: dict[tuple[str, ...], int] = {}
        self._wall_clock_timeouts_by_text: dict[str, int] = {}
        self._add_node(None, None, None, None, None, root_state, 0.0, root_lean_seconds)

    @property
    def root(self) -> Node:
        return self.nodes[0]

    def node(self, node_id: int) -> Node:
        return self.nodes[node_id]

    def parent(self, node: Node) -> Node | None:
        return None if node.parent_id is None else self.nodes[node.parent_id]

    def children(self, node: Node) -> list[Node]:
        return [self.nodes[child_id] for child_id in node.child_ids]

    def path(self, node: Node) -> list[Node]:
        reversed_path = [node]
        while (parent := self.parent(reversed_path[-1])) is not None:
            reversed_path.append(parent)
        return reversed_path[::-1]

    def node_with_goals(self, goal_key: tuple[str, ...]) -> Node | None:
        node_id = self._node_by_goal_key.get(goal_key)
        return None if node_id is None else self.nodes[node_id]

    def wall_clock_timeouts(self, text: str) -> int:
        return self._wall_clock_timeouts_by_text.get(text, 0)

    def add_edge(
        self,
        parent: Node,
        *,
        text: str,
        source: StepSource,
        log_probability: float | None,
        prompt_tokens: int,
        generated_tokens: int,
        outcome: EdgeOutcome,
        target_id: int | None = None,
        applied_tactics: int = 0,
        total_tactics: int = 0,
        failure: Failure | None = None,
        lean_seconds: float = 0.0,
        repeat_of: int | None = None,
    ) -> Edge:
        assert parent.expansion_index is not None, parent.node_id
        edge = Edge(
            edge_id=len(self.edges),
            parent_id=parent.node_id,
            expansion_index=parent.expansion_index,
            text=text,
            source=source,
            log_probability=log_probability,
            prompt_tokens=prompt_tokens,
            generated_tokens=generated_tokens,
            outcome=outcome,
            target_id=target_id,
            applied_tactics=applied_tactics,
            total_tactics=total_tactics,
            failure=failure,
            lean_seconds=lean_seconds,
            repeat_of=repeat_of,
        )
        self.edges.append(edge)
        if failure is not None and failure.kind == FailureKind.WALL_CLOCK_TIMEOUT:
            self._wall_clock_timeouts_by_text[text] = self._wall_clock_timeouts_by_text.get(text, 0) + 1
        return edge

    def add_child(
        self,
        parent: Node,
        edge_id: int,
        step: str,
        source: StepSource,
        log_probability: float | None,
        state: ProofState,
        created_seconds: float,
        step_lean_seconds: float,
    ) -> Node:
        child = self._add_node(
            parent, edge_id, step, source, log_probability, state, created_seconds, step_lean_seconds
        )
        parent.child_ids.append(child.node_id)
        return child

    def next_node_id(self) -> int:
        return len(self.nodes)

    def mark_proof_path(self, proved: Node) -> list[Node]:
        path = self.path(proved)
        for node in path:
            node.status = NodeStatus.PROVED
        return path

    def settle_statuses(self) -> None:
        """Expanded nodes that reach no open or proved node, via child or duplicate edges, become failed."""
        predecessors: dict[int, list[int]] = {}
        for edge in self.edges:
            if edge.target_id is not None:
                predecessors.setdefault(edge.target_id, []).append(edge.parent_id)
        pending = [node.node_id for node in self.nodes if node.status in (NodeStatus.OPEN, NodeStatus.PROVED)]
        alive = set(pending)
        while pending:
            for predecessor in predecessors.get(pending.pop(), ()):
                if predecessor not in alive:
                    alive.add(predecessor)
                    pending.append(predecessor)
        for node in self.nodes:
            if node.status == NodeStatus.EXPANDED and node.node_id not in alive:
                node.status = NodeStatus.FAILED

    def _add_node(
        self,
        parent: Node | None,
        edge_id: int | None,
        step: str | None,
        source: StepSource | None,
        log_probability: float | None,
        state: ProofState,
        created_seconds: float,
        step_lean_seconds: float,
    ) -> Node:
        node = Node(
            node_id=len(self.nodes),
            parent_id=None if parent is None else parent.node_id,
            edge_id=edge_id,
            step=step,
            source=source,
            log_probability=log_probability,
            depth=0 if parent is None else parent.depth + 1,
            state=state,
            created_seconds=created_seconds,
            step_lean_seconds=step_lean_seconds,
        )
        self.nodes.append(node)
        # Proved states are never de-duplicated: a proof whose verification failed must not shadow a later one.
        if not state.is_proved:
            self._node_by_goal_key.setdefault(state.goal_key, node.node_id)
        return node
