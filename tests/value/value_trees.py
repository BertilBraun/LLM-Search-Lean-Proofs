from lean_search.lean import ProofState
from lean_search.search import (
    Accounting,
    EdgeOutcome,
    Failure,
    FailureKind,
    Node,
    NodeStatus,
    SearchResult,
    SearchTree,
    StepSource,
    StopReason,
    TreeRecord,
    tree_record,
)


def proof_state(*goals: str) -> ProofState:
    return ProofState("", "theorem t : True := by", (), goals, repl_proof_state=0, session=0)


class TreeBuilder:
    """Builds search trees through SearchTree's own API; a node with an attempt counts as expanded."""

    def __init__(self, *root_goals: str) -> None:
        self.tree = SearchTree("t", proof_state(*root_goals), 0.0)

    @property
    def root(self) -> Node:
        return self.tree.root

    def expand(self, node: Node) -> None:
        node.expansion_index = 0
        if node.status == NodeStatus.OPEN:
            node.status = NodeStatus.EXPANDED

    def child(self, parent: Node, *goals: str) -> Node:
        self.expand(parent)
        edge = self.tree.add_edge(
            parent,
            text=f"step {self.tree.next_node_id()}",
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.CHILD,
            target_id=self.tree.next_node_id(),
            applied_tactics=1,
            total_tactics=1,
        )
        return self.tree.add_child(
            parent, edge.edge_id, edge.text, StepSource.POLICY, -1.0, proof_state(*goals), 0.0, 0.0
        )

    def duplicate(self, parent: Node, target: Node) -> None:
        self.expand(parent)
        self.tree.add_edge(
            parent,
            text=f"duplicate of {target.node_id}",
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.DUPLICATE,
            target_id=target.node_id,
            applied_tactics=1,
            total_tactics=1,
        )

    def failure(self, parent: Node, kind: FailureKind = FailureKind.ERROR) -> None:
        self.expand(parent)
        self.tree.add_edge(
            parent,
            text="bad step",
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.FAILED,
            failure=Failure(kind, "failed"),
        )

    def record(self, proved: Node | None = None) -> TreeRecord:
        if proved is not None:
            self.tree.mark_proof_path(proved)
        self.tree.settle_statuses()
        result = SearchResult(
            problem_name="t",
            proved=proved is not None,
            stop_reason=StopReason.PROVED if proved is not None else StopReason.EXPANSION_BUDGET,
            proof=None,
            proof_steps=(),
            proof_sources=(),
            accounting=Accounting(),
            solved_at=None,
            verification_failures=0,
            max_depth_reached=max(node.depth for node in self.tree.nodes),
        )
        return tree_record(self.tree, "theorem t : True := by", result)
