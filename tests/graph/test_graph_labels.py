import pytest
from graph_trees import GraphBuilder

from lean_search.search import FailureKind, NodeStatus, StepSource, TreeRecord
from lean_search.search.graph_labels import EdgeKind, GraphLabels, NodeClass, ReachedNode, label_graph


def transposition_into_proof() -> tuple[TreeRecord, dict[str, int]]:
    builder = GraphBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    b = builder.child(builder.root, "⊢ b")
    proof = builder.child(a)
    builder.duplicate(b, a)
    return builder.record(proof), {"r": 0, "a": a.node_id, "b": b.node_id, "proof": proof.node_id}


def commuting_steps() -> tuple[TreeRecord, dict[str, int]]:
    """A then B and B then A reach the same state, which is proved."""
    builder = GraphBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    b = builder.child(builder.root, "⊢ b")
    ab = builder.child(a, "⊢ ab")
    builder.duplicate(b, ab)
    proof = builder.child(ab)
    return builder.record(proof), {"a": a.node_id, "b": b.node_id, "ab": ab.node_id}


def no_progress_graph() -> tuple[TreeRecord, dict[str, int]]:
    builder = GraphBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    c = builder.child(builder.root, "⊢ c")
    d = builder.child(c, "⊢ d")
    builder.duplicate(d, d, text="ring_nf")
    builder.duplicate(d, builder.root, text="simp_all")
    builder.failure(d)
    proof = builder.child(a)
    return builder.record(proof), {"a": a.node_id, "c": c.node_id, "d": d.node_id}


def dead_end_graph() -> tuple[TreeRecord, dict[str, int]]:
    builder = GraphBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    builder.duplicate(dead, dead)
    leads_to_dead = builder.child(builder.root, "⊢ leads to dead")
    builder.duplicate(leads_to_dead, dead)
    leads_to_open = builder.child(builder.root, "⊢ leads to open")
    open_node = builder.child(builder.root, "⊢ open")
    builder.duplicate(leads_to_open, open_node)
    repl_failure = builder.child(builder.root, "⊢ repl failure")
    builder.failure(repl_failure, FailureKind.REPL_FAILURE)
    return builder.record(), {
        "dead": dead.node_id,
        "leads to dead": leads_to_dead.node_id,
        "leads to open": leads_to_open.node_id,
        "open": open_node.node_id,
        "repl failure": repl_failure.node_id,
    }


def class_of(labels: GraphLabels, node_id: int) -> NodeClass:
    return labels.node_classes[node_id]


def test_duplicate_into_another_branch_is_a_transposition() -> None:
    record, _ = transposition_into_proof()
    assert label_graph(record).edges[3].kind == EdgeKind.TRANSPOSITION


def test_transposition_into_a_proof_puts_the_source_on_the_proof_graph() -> None:
    record, ids = transposition_into_proof()
    assert class_of(label_graph(record), ids["b"]) == NodeClass.PROOF_GRAPH


def test_transposition_source_needs_one_more_step_than_its_target() -> None:
    record, ids = transposition_into_proof()
    assert label_graph(record).remaining_steps[ids["b"]] == 2


@pytest.mark.parametrize(("name", "steps"), [("a", 2), ("b", 2), ("ab", 1)])
def test_both_orders_of_commuting_steps_reach_the_proof(name: str, steps: int) -> None:
    record, ids = commuting_steps()
    assert label_graph(record).remaining_steps[ids[name]] == steps


def test_root_steps_are_the_shortest_route() -> None:
    record, _ = commuting_steps()
    assert label_graph(record).remaining_steps[0] == 3


@pytest.mark.parametrize(
    ("edge_index", "kind"),
    [(3, EdgeKind.NO_PROGRESS), (4, EdgeKind.BACK_TO_ANCESTOR), (5, EdgeKind.LEAN_ERROR)],
)
def test_no_progress_edge_kinds(edge_index: int, kind: EdgeKind) -> None:
    record, _ = no_progress_graph()
    assert label_graph(record).edges[edge_index].kind == kind


def test_back_edge_to_a_proved_ancestor_is_no_route_to_the_proof() -> None:
    record, ids = no_progress_graph()
    assert label_graph(record).remaining_steps[ids["d"]] is None


def test_node_with_only_no_progress_and_errors_is_a_dead_end() -> None:
    record, ids = no_progress_graph()
    assert class_of(label_graph(record), ids["d"]) == NodeClass.DEAD_END


def test_parent_of_a_dead_end_is_expanded_off_graph() -> None:
    record, ids = no_progress_graph()
    assert class_of(label_graph(record), ids["c"]) == NodeClass.EXPANDED_OFF_GRAPH


@pytest.mark.parametrize(
    ("name", "node_class"),
    [
        ("dead", NodeClass.DEAD_END),
        ("leads to dead", NodeClass.DEAD_END),
        ("leads to open", NodeClass.EXPANDED_OFF_GRAPH),
        ("open", NodeClass.NEVER_EXPANDED),
        ("repl failure", NodeClass.EXPANDED_OFF_GRAPH),
    ],
)
def test_dead_end_classes(name: str, node_class: NodeClass) -> None:
    record, ids = dead_end_graph()
    assert class_of(label_graph(record), ids[name]) == node_class


def test_unsolved_tree_has_no_proof_graph() -> None:
    record, _ = dead_end_graph()
    assert not label_graph(record).solved


def test_partially_expanded_node_is_not_a_dead_end() -> None:
    builder = GraphBuilder("⊢ r")
    cut_off = builder.child(builder.root, "⊢ cut off")
    builder.failure(cut_off)
    cut_off.status = NodeStatus.OPEN
    record = builder.record()
    assert class_of(label_graph(record), cut_off.node_id) == NodeClass.EXPANDED_OFF_GRAPH


def test_cycle_of_transpositions_without_new_states_is_dead() -> None:
    builder = GraphBuilder("⊢ r")
    first = builder.child(builder.root, "⊢ first")
    second = builder.child(builder.root, "⊢ second")
    builder.duplicate(first, second)
    builder.duplicate(second, first)
    labels = label_graph(builder.record())
    assert {class_of(labels, first.node_id), class_of(labels, second.node_id)} == {NodeClass.DEAD_END}


def repeated_texts() -> GraphLabels:
    builder = GraphBuilder("⊢ r")
    failed_sweep = builder.failure(builder.root, text="linarith", source=StepSource.AUTOMATION)
    child_sweep_edge_id = len(builder.tree.edges)
    builder.child(builder.root, "⊢ a", text="ring_nf", source=StepSource.AUTOMATION)
    builder.repeat(builder.root, failed_sweep)
    builder.repeat(builder.root, builder.tree.edges[child_sweep_edge_id])
    return label_graph(builder.record())


def test_repeat_of_a_failed_sweep_tactic_is_flagged() -> None:
    assert repeated_texts().edges[2].repeats_failed_automation


def test_repeat_takes_the_outcome_of_the_edge_it_repeats() -> None:
    assert repeated_texts().edges[3].effective_kind == EdgeKind.NEW_STATE


def test_repeat_keeps_its_own_kind() -> None:
    assert repeated_texts().edges[3].kind == EdgeKind.REPEAT


def test_repeat_of_a_new_state_is_not_flagged_as_a_failed_sweep_repeat() -> None:
    assert not repeated_texts().edges[3].repeats_failed_automation


def test_block_failing_after_a_valid_prefix_is_partial() -> None:
    builder = GraphBuilder("⊢ r")
    builder.child(builder.root, "⊢ prefix", failure_after=2)
    assert label_graph(builder.record()).edges[0].partial


def test_unverified_proof_edge() -> None:
    builder = GraphBuilder("⊢ r")
    unverified = builder.child(builder.root)
    unverified.status = NodeStatus.FAILED
    assert label_graph(builder.record()).edges[0].kind == EdgeKind.UNVERIFIED_PROOF


def test_expanded_descendants_count_each_node_once_at_its_shortest_distance() -> None:
    builder = GraphBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    b = builder.child(builder.root, "⊢ b")
    ab = builder.child(a, "⊢ ab")
    builder.duplicate(b, ab)
    builder.duplicate(ab, builder.root)
    builder.failure(ab)
    labels = label_graph(builder.record())
    assert set(labels.expanded_descendants[0]) == {
        ReachedNode(a.node_id, 1),
        ReachedNode(b.node_id, 1),
        ReachedNode(ab.node_id, 2),
    }


def test_expanded_descendants_skip_back_edges() -> None:
    builder = GraphBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    builder.child(builder.root, "⊢ sibling")
    builder.duplicate(a, builder.root)
    labels = label_graph(builder.record())
    assert labels.expanded_descendants[a.node_id] == ()
