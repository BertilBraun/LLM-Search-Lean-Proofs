from expert_trees import TreeBuilder

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.preferences import NodePairs, RejectionKind, dead_node_ids, node_pairs
from lean_search.expert_iteration.proofs import found_proof
from lean_search.search import FailureKind, Node, StepSource, TreeRecord

CONFIG = PreferenceConfig(max_pairs_per_node=4, policy_steps_only=True, dead_subtrees=True)


def pairs_at_root(builder: TreeBuilder, on_path: Node, config: PreferenceConfig = CONFIG) -> NodePairs:
    proved = builder.child(on_path, step="linarith")
    record = builder.record(proved)
    proof = found_proof("round_0", record)
    assert proof is not None
    return node_pairs(record, proof, config)[0]


def rejections(pairs: NodePairs) -> list[tuple[str, str, str]]:
    return [(pair.chosen, pair.rejected, pair.rejection) for pair in pairs.pairs]


def test_a_sibling_lean_rejected_is_paired_against_the_on_path_step() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "exact foo")
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert rejections(pairs_at_root(builder, on_path)) == [("intro x", "exact foo", RejectionKind.ERROR)]


def test_a_sibling_that_timed_out_is_a_timeout_rejection() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "nlinarith [big]", FailureKind.HEARTBEAT_TIMEOUT)
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert [pair.rejection for pair in pairs_at_root(builder, on_path).pairs] == [RejectionKind.TIMEOUT]


def test_an_infrastructure_failure_is_never_rejected() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "simp", FailureKind.REPL_FAILURE)
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert pairs_at_root(builder, on_path).pairs == ()


def test_a_sibling_leading_into_a_dead_subtree_is_rejected() -> None:
    builder = TreeBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ false", step="exfalso")
    builder.failure(dead, "simp")
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert rejections(pairs_at_root(builder, on_path)) == [("intro x", "exfalso", RejectionKind.DEAD)]


def test_a_sibling_on_the_frontier_is_not_rejected() -> None:
    builder = TreeBuilder("⊢ r")
    builder.child(builder.root, "⊢ unexplored", step="constructor")
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert pairs_at_root(builder, on_path).pairs == ()


def test_dead_subtrees_can_be_left_out() -> None:
    builder = TreeBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ false", step="exfalso")
    builder.failure(dead, "simp")
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    config = PreferenceConfig(max_pairs_per_node=4, policy_steps_only=True, dead_subtrees=False)
    assert pairs_at_root(builder, on_path, config).pairs == ()


def test_the_cap_keeps_the_most_likely_rejections() -> None:
    builder = TreeBuilder("⊢ r")
    for index, log_probability in enumerate((-5.0, -1.0, -3.0, -0.5)):
        builder.failure(builder.root, f"bad {index}", log_probability=log_probability)
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    config = PreferenceConfig(max_pairs_per_node=2, policy_steps_only=True, dead_subtrees=True)
    assert [pair.rejected for pair in pairs_at_root(builder, on_path, config).pairs] == ["bad 3", "bad 1"]


def test_rejections_the_policy_preferred_are_counted() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "likely", log_probability=-0.5)
    builder.failure(builder.root, "unlikely", log_probability=-4.0)
    on_path = builder.child(builder.root, "⊢ s", step="intro x", log_probability=-2.0)
    assert pairs_at_root(builder, on_path).rejected_more_likely == 1


def test_automation_siblings_are_not_rejected_for_the_policy() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "linarith", source=StepSource.AUTOMATION, log_probability=None)
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert pairs_at_root(builder, on_path).pairs == ()


def test_automation_steps_on_the_path_give_no_pairs() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "exact foo")
    on_path = builder.child(builder.root, "⊢ s", step="norm_num", source=StepSource.AUTOMATION, log_probability=None)
    proved = builder.child(on_path, step="linarith")
    record = builder.record(proved)
    proof = found_proof("round_0", record)
    assert proof is not None
    assert [pairs.step_index for pairs in node_pairs(record, proof, CONFIG)] == [1]


def test_pairs_share_the_prompt_of_their_node() -> None:
    builder = TreeBuilder("x : ℕ\n⊢ r x")
    builder.failure(builder.root, "exact foo")
    builder.failure(builder.root, "exact bar")
    on_path = builder.child(builder.root, "⊢ s", step="intro x")
    assert {pair.goals for pair in pairs_at_root(builder, on_path).pairs} == {("x : ℕ\n⊢ r x",)}


def dead_and_alive_tree() -> TreeRecord:
    builder = TreeBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ false")
    builder.failure(dead, "simp")
    builder.child(builder.root, "⊢ open")
    return builder.record()


def test_dead_nodes_are_the_fully_expanded_ones_without_a_way_out() -> None:
    assert dead_node_ids(dead_and_alive_tree()) == frozenset({1})
