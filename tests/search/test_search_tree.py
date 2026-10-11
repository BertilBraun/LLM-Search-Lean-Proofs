import pytest
from search_trees import add_child, new_tree, proof_state

from lean_search.lean import LeanError, LeanTimeout, ReplFailure, ReplFailureKind
from lean_search.search import EdgeOutcome, Failure, FailureKind, Node, NodeStatus, SearchTree, StepSource
from lean_search.search.search import ForbiddenSteps


def test_child_depth_is_parent_depth_plus_one() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    grandchild = add_child(tree, child, ("⊢ r",))
    assert grandchild.depth == 2


def test_node_with_whitespace_equal_goals_is_found_for_deduplication() -> None:
    tree = new_tree("x : ℕ\n⊢ x = x + 0")
    child = add_child(tree, tree.root, ("x  : ℕ\n⊢ x =  x",))
    assert tree.node_with_goals(proof_state("x : ℕ\n⊢ x = x").goal_key) is child


def test_goals_in_another_order_are_a_different_state() -> None:
    tree = new_tree("⊢ p", "⊢ q")
    assert tree.node_with_goals(proof_state("⊢ q", "⊢ p").goal_key) is None


def test_proved_states_are_never_deduplicated() -> None:
    tree = new_tree("⊢ p")
    add_child(tree, tree.root, ())
    assert tree.node_with_goals(()) is None


def add_duplicate_edge(tree: SearchTree, parent: Node, target: Node) -> None:
    if parent.expansion_index is None:
        parent.expansion_index = 0
    tree.add_edge(
        parent,
        text="simp",
        source=StepSource.AUTOMATION,
        log_probability=None,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.DUPLICATE,
        target_id=target.node_id,
        applied_tactics=1,
        total_tactics=1,
    )


def test_fully_expanded_subtree_without_open_nodes_fails() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    tree.root.status = child.status = NodeStatus.EXPANDED
    tree.settle_statuses()
    assert [node.status for node in tree.nodes] == [NodeStatus.FAILED, NodeStatus.FAILED]


def test_open_descendant_keeps_its_ancestors_alive() -> None:
    tree = new_tree("⊢ p")
    first = add_child(tree, tree.root, ("⊢ q",))
    add_child(tree, tree.root, ("⊢ r",), step="norm_num")
    tree.root.status = first.status = NodeStatus.EXPANDED
    tree.settle_statuses()
    assert [node.status for node in tree.nodes] == [NodeStatus.EXPANDED, NodeStatus.FAILED, NodeStatus.OPEN]


def test_duplicate_edge_into_an_open_node_keeps_a_node_alive() -> None:
    tree = new_tree("⊢ p")
    first = add_child(tree, tree.root, ("⊢ q",))
    second = add_child(tree, tree.root, ("⊢ r",), step="norm_num")
    add_duplicate_edge(tree, first, second)
    tree.root.status = first.status = NodeStatus.EXPANDED
    tree.settle_statuses()
    assert first.status == NodeStatus.EXPANDED


def test_duplicate_edge_to_itself_does_not_keep_a_node_alive() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    add_duplicate_edge(tree, child, child)
    tree.root.status = child.status = NodeStatus.EXPANDED
    tree.settle_statuses()
    assert child.status == NodeStatus.FAILED


def test_proof_path_is_marked_proved() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    add_child(tree, tree.root, ("⊢ r",), step="norm_num")
    proved = add_child(tree, child, ())
    tree.mark_proof_path(proved)
    assert [node.status for node in tree.nodes] == [
        NodeStatus.PROVED,
        NodeStatus.PROVED,
        NodeStatus.OPEN,
        NodeStatus.PROVED,
    ]


def test_path_runs_from_the_root() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    grandchild = add_child(tree, child, ("⊢ r",))
    assert [node.node_id for node in tree.path(grandchild)] == [0, 1, 2]


def test_wall_clock_timeouts_are_counted_by_step_text() -> None:
    tree = new_tree("⊢ p")
    tree.root.expansion_index = 0
    for _ in range(2):
        tree.add_edge(
            tree.root,
            text="rfl",
            source=StepSource.AUTOMATION,
            log_probability=None,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.FAILED,
            failure=Failure(FailureKind.WALL_CLOCK_TIMEOUT, "killed"),
        )
    assert (tree.wall_clock_timeouts("rfl"), tree.wall_clock_timeouts("simp")) == (2, 0)


@pytest.mark.parametrize(
    ("outcome", "kind"),
    [
        (LeanError("unknown identifier"), FailureKind.ERROR),
        (LeanTimeout("heartbeats", wall_clock=False), FailureKind.HEARTBEAT_TIMEOUT),
        (LeanTimeout("killed", wall_clock=True), FailureKind.WALL_CLOCK_TIMEOUT),
        (ReplFailure(ReplFailureKind.CRASHED, "died"), FailureKind.REPL_FAILURE),
        (ReplFailure(ReplFailureKind.REPLAY_MISMATCH, "goals differ"), FailureKind.REPL_FAILURE),
    ],
)
def test_lean_failures_map_to_failure_kinds(outcome: LeanError | LeanTimeout | ReplFailure, kind: FailureKind) -> None:
    assert Failure.from_lean(outcome).kind == kind


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (FailureKind.ERROR, True),
        (FailureKind.HEARTBEAT_TIMEOUT, True),
        (FailureKind.WALL_CLOCK_TIMEOUT, True),
        (FailureKind.FORBIDDEN, True),
        (FailureKind.REPL_FAILURE, False),
    ],
)
def test_only_the_candidates_own_failures_are_negative_labels(kind: FailureKind, expected: bool) -> None:
    assert Failure(kind, "").is_negative_label == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("exact?", ["exact?"]),
        ("apply?", ["apply?"]),
        ("  rw?", ["rw?"]),
        ("rw?? ", ["rw?"]),
        ("constructor\n· aesop?\n· simp", ["aesop?"]),
        ("simp? says simp only [h]", ["simp?"]),
        ("hint", ["hint"]),
        ("exact List.get? xs 0", []),
        ("have hint₁ : 0 < 2 := by norm_num", []),
        ("nlinarith [sq_nonneg (a - b)]", []),
        ("simp at h", []),
    ],
)
def test_forbidden_steps_match_whole_tactic_names(text: str, expected: list[str]) -> None:
    forbidden = ForbiddenSteps(["exact?", "apply?", "rw?", "simp?", "aesop?", "hint"])
    assert forbidden.find(text) == expected
