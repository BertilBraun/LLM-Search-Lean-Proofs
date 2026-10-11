from lean_search.lean import ProofState
from lean_search.search import EdgeOutcome, Node, SearchTree, StepSource


def proof_state(*goals: str, tactics: tuple[str, ...] = ()) -> ProofState:
    return ProofState("", "theorem t : True := by", tactics, goals, repl_proof_state=0, session=0)


def add_child(
    tree: SearchTree,
    parent: Node,
    goals: tuple[str, ...],
    step: str = "simp",
    source: StepSource = StepSource.AUTOMATION,
    log_probability: float | None = None,
) -> Node:
    if parent.expansion_index is None:
        parent.expansion_index = 0
    state = proof_state(*goals, tactics=(*parent.state.tactics, step))
    edge = tree.add_edge(
        parent,
        text=step,
        source=source,
        log_probability=log_probability,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.CHILD,
        target_id=tree.next_node_id(),
        applied_tactics=1,
        total_tactics=1,
    )
    return tree.add_child(parent, edge.edge_id, step, source, log_probability, state, 0.0, 0.0)


def new_tree(*goals: str) -> SearchTree:
    return SearchTree("t", proof_state(*goals), 0.0)
