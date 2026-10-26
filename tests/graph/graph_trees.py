from lean_search.lean import ProofState
from lean_search.search import (
    Accounting,
    Edge,
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


class GraphBuilder:
    """Search graphs through SearchTree's own API; a node with an attempt counts as fully expanded."""

    def __init__(self, *root_goals: str, root_value: float | None = None) -> None:
        self.tree = SearchTree("t", proof_state(*root_goals), 0.0)
        self.tree.root.value_estimate = root_value
        self.expansions = 0

    @property
    def root(self) -> Node:
        return self.tree.root

    def expand(self, node: Node) -> None:
        if node.expansion_index is None:
            node.expansion_index = self.expansions
            self.expansions += 1
        if node.status == NodeStatus.OPEN:
            node.status = NodeStatus.EXPANDED

    def edge(
        self,
        parent: Node,
        outcome: EdgeOutcome,
        *,
        text: str,
        source: StepSource,
        target_id: int | None = None,
        failure: Failure | None = None,
        applied_tactics: int = 1,
        total_tactics: int = 1,
        repeat_of: int | None = None,
        sample_count: int = 1,
    ) -> Edge:
        self.expand(parent)
        return self.tree.add_edge(
            parent,
            text=text,
            source=source,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=outcome,
            target_id=target_id,
            applied_tactics=applied_tactics,
            total_tactics=total_tactics,
            failure=failure,
            repeat_of=repeat_of,
            sample_count=sample_count,
        )

    def child(
        self,
        parent: Node,
        *goals: str,
        value: float | None = None,
        text: str | None = None,
        source: StepSource = StepSource.POLICY,
        failure_after: int | None = None,
        sample_count: int = 1,
    ) -> Node:
        """`failure_after`: the block's first n tactics applied, then the next one failed."""
        step = text or f"step {self.tree.next_node_id()}"
        edge = self.edge(
            parent,
            EdgeOutcome.CHILD,
            text=step,
            source=source,
            target_id=self.tree.next_node_id(),
            failure=None if failure_after is None else Failure(FailureKind.ERROR, "failed"),
            applied_tactics=1 if failure_after is None else failure_after,
            total_tactics=1 if failure_after is None else failure_after + 2,
            sample_count=sample_count,
        )
        child = self.tree.add_child(parent, edge.edge_id, step, source, -1.0, proof_state(*goals), 0.0, 0.0)
        child.value_estimate = value
        return child

    def duplicate(
        self, parent: Node, target: Node, text: str | None = None, source: StepSource = StepSource.POLICY
    ) -> Edge:
        return self.edge(
            parent,
            EdgeOutcome.DUPLICATE,
            text=text or f"duplicate {len(self.tree.edges)}",
            source=source,
            target_id=target.node_id,
        )

    def failure(
        self,
        parent: Node,
        kind: FailureKind = FailureKind.ERROR,
        text: str | None = None,
        source: StepSource = StepSource.POLICY,
        sample_count: int = 1,
    ) -> Edge:
        return self.edge(
            parent,
            EdgeOutcome.FAILED,
            text=text or f"failure {len(self.tree.edges)}",
            source=source,
            failure=Failure(kind, "failed"),
            applied_tactics=0,
            sample_count=sample_count,
        )

    def unparsed(self, parent: Node) -> Edge:
        """A policy sample without a usable block, recorded as the search does."""
        return self.edge(
            parent,
            EdgeOutcome.REJECTED,
            text="",
            source=StepSource.POLICY,
            failure=Failure(FailureKind.UNPARSED, "The sample has no usable block: truncated."),
            applied_tactics=0,
            total_tactics=0,
        )

    def repeat(self, parent: Node, earlier: Edge, source: StepSource = StepSource.POLICY) -> Edge:
        return self.edge(
            parent,
            EdgeOutcome.REPEATED,
            text=earlier.text,
            source=source,
            applied_tactics=0,
            total_tactics=0,
            repeat_of=earlier.edge_id,
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
