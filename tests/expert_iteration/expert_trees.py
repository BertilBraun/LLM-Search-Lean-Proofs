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

PROBLEM = "lean_workbook.t"


def proof_state(*goals: str) -> ProofState:
    return ProofState("", "theorem t : True := by", (), goals, repl_proof_state=0, session=0)


class TreeBuilder:
    """Search trees through SearchTree's own API; a node with an attempt counts as expanded."""

    def __init__(self, *root_goals: str, problem_name: str = PROBLEM) -> None:
        self.tree = SearchTree(problem_name, proof_state(*root_goals), 0.0)

    @property
    def root(self) -> Node:
        return self.tree.root

    def expand(self, node: Node) -> None:
        node.expansion_index = 0
        if node.status == NodeStatus.OPEN:
            node.status = NodeStatus.EXPANDED

    def child(
        self,
        parent: Node,
        *goals: str,
        step: str | None = None,
        source: StepSource = StepSource.POLICY,
        log_probability: float | None = -1.0,
    ) -> Node:
        self.expand(parent)
        text = step or f"step {self.tree.next_node_id()}"
        edge = self.tree.add_edge(
            parent,
            text=text,
            source=source,
            log_probability=log_probability,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.CHILD,
            target_id=self.tree.next_node_id(),
            applied_tactics=1,
            total_tactics=1,
        )
        return self.tree.add_child(parent, edge.edge_id, text, source, log_probability, proof_state(*goals), 0.0, 0.0)

    def duplicate(self, parent: Node, target: Node, step: str, log_probability: float = -1.0) -> None:
        self.expand(parent)
        self.tree.add_edge(
            parent,
            text=step,
            source=StepSource.POLICY,
            log_probability=log_probability,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.DUPLICATE,
            target_id=target.node_id,
            applied_tactics=1,
            total_tactics=1,
        )

    def failure(
        self,
        parent: Node,
        step: str,
        kind: FailureKind = FailureKind.ERROR,
        source: StepSource = StepSource.POLICY,
        log_probability: float | None = -1.0,
    ) -> None:
        self.expand(parent)
        self.tree.add_edge(
            parent,
            text=step,
            source=source,
            log_probability=log_probability,
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
            problem_name=self.tree.problem_name,
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
