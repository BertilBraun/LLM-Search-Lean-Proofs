import pytest
from graph_trees import GraphBuilder

from lean_search.search import Node
from lean_search.search.graph_labels import label_graph
from lean_search.value.ranking import PairKind, RankingConfig, SiblingPair, sibling_pairs

CONFIG = RankingConfig(
    proof_over_dead_end_weight=1.0,
    proof_over_expanded_weight=0.5,
    proof_over_never_expanded_weight=0.1,
    expanded_over_dead_end_weight=0.5,
    half_weight_expanded_nodes=2.0,
    minimum_expanded_nodes=3,
)


def grow(builder: GraphBuilder, node: Node, expanded_levels: int) -> None:
    """A chain of `expanded_levels` expanded nodes below `node`, ending in a never-expanded leaf."""
    for level in range(expanded_levels):
        node = builder.child(node, f"⊢ {node.goals[0]} {level}")
    builder.child(node, f"⊢ {node.goals[0]} leaf")


def solved_pairs() -> dict[PairKind, list[SiblingPair]]:
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    expanded = builder.child(builder.root, "⊢ expanded")
    grow(builder, expanded, 1)
    builder.child(builder.root, "⊢ never expanded")
    builder.duplicate(builder.root, proof_child)
    proof = builder.child(proof_child)
    pairs = sibling_pairs(label_graph(builder.record(proof)), CONFIG)
    by_kind: dict[PairKind, list[SiblingPair]] = {}
    for pair in pairs:
        by_kind.setdefault(pair.kind, []).append(pair)
    return by_kind


@pytest.mark.parametrize(
    "kind", [PairKind.PROOF_OVER_DEAD_END, PairKind.PROOF_OVER_EXPANDED, PairKind.PROOF_OVER_NEVER_EXPANDED]
)
def test_solved_tree_pairs_the_proof_child_once_with_each_sibling_class(kind: PairKind) -> None:
    assert len(solved_pairs()[kind]) == 1


def test_solved_tree_has_no_expanded_over_dead_end_pair_by_default() -> None:
    assert PairKind.EXPANDED_OVER_DEAD_END not in solved_pairs()


def test_proof_over_expanded_weight_grows_with_the_subtree() -> None:
    assert solved_pairs()[PairKind.PROOF_OVER_EXPANDED][0].weight == pytest.approx(0.5 * 2 / (2 + 2))


def test_never_expanded_pairs_are_dropped_at_weight_zero() -> None:
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    builder.child(builder.root, "⊢ never expanded")
    proof = builder.child(proof_child)
    pairs = sibling_pairs(label_graph(builder.record(proof)), RankingConfig())
    assert pairs == []


def unsolved_pairs() -> list[SiblingPair]:
    builder = GraphBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    large = builder.child(builder.root, "⊢ large")
    grow(builder, large, 2)
    small = builder.child(builder.root, "⊢ small")
    grow(builder, small, 0)
    builder.child(builder.root, "⊢ never expanded")
    return sibling_pairs(label_graph(builder.record()), CONFIG)


def test_unsolved_tree_ranks_only_large_expanded_subtrees_over_dead_ends() -> None:
    assert [(pair.kind, pair.preferred_id, pair.other_id) for pair in unsolved_pairs()] == [
        (PairKind.EXPANDED_OVER_DEAD_END, 2, 1)
    ]


def test_identical_states_reached_twice_give_one_pair() -> None:
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    builder.duplicate(builder.root, dead)
    proof = builder.child(proof_child)
    assert len(sibling_pairs(label_graph(builder.record(proof)), CONFIG)) == 1
