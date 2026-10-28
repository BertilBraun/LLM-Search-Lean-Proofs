import pytest
from graph_trees import GraphBuilder

from lean_search.search import Node
from lean_search.search.graph_labels import label_graph
from lean_search.value.ranking import PairKind, RankingConfig, SiblingPair, sibling_pairs

CONFIG = RankingConfig(
    proof_over_expanded_weight=0.5,
    proof_over_never_expanded_weight=0.1,
    half_weight_expanded_nodes=2.0,
)


def grow(builder: GraphBuilder, node: Node, expanded_levels: int) -> None:
    """A chain of `expanded_levels` expanded nodes below `node`, ending in a never-expanded leaf."""
    for level in range(expanded_levels):
        node = builder.child(node, f"⊢ {node.goals[0]} {level}")
    builder.child(node, f"⊢ {node.goals[0]} leaf")


def solved_pairs() -> dict[str, list[SiblingPair]]:
    """Pairs by the other sibling's goal: a dead end, an expanded subtree of two nodes, a never-expanded state."""
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    expanded = builder.child(builder.root, "⊢ expanded")
    grow(builder, expanded, 1)
    builder.child(builder.root, "⊢ never expanded")
    builder.duplicate(builder.root, proof_child)
    proof = builder.child(proof_child)
    record = builder.record(proof)
    by_other: dict[str, list[SiblingPair]] = {}
    for pair in sibling_pairs(label_graph(record), CONFIG):
        by_other.setdefault(record.nodes[pair.other_id].goals[0], []).append(pair)
    return by_other


@pytest.mark.parametrize(
    ("other", "kind"),
    [
        ("⊢ dead", PairKind.PROOF_OVER_EXPANDED),
        ("⊢ expanded", PairKind.PROOF_OVER_EXPANDED),
        ("⊢ never expanded", PairKind.PROOF_OVER_NEVER_EXPANDED),
    ],
)
def test_solved_tree_pairs_the_proof_child_once_with_each_off_graph_sibling(other: str, kind: PairKind) -> None:
    assert [pair.kind for pair in solved_pairs()[other]] == [kind]


@pytest.mark.parametrize(("other", "weight"), [("⊢ dead", 0.5 * 1 / (1 + 2)), ("⊢ expanded", 0.5 * 2 / (2 + 2))])
def test_proof_over_expanded_weight_grows_with_the_sibling_subtree(other: str, weight: float) -> None:
    assert solved_pairs()[other][0].weight == pytest.approx(weight)


def test_never_expanded_pairs_are_dropped_at_weight_zero() -> None:
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    builder.child(builder.root, "⊢ never expanded")
    proof = builder.child(proof_child)
    pairs = sibling_pairs(label_graph(builder.record(proof)), RankingConfig())
    assert pairs == []


def test_unsolved_tree_gives_no_pairs() -> None:
    builder = GraphBuilder("⊢ r")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    large = builder.child(builder.root, "⊢ large")
    grow(builder, large, 2)
    builder.child(builder.root, "⊢ never expanded")
    assert sibling_pairs(label_graph(builder.record()), CONFIG) == []


def test_identical_states_reached_twice_give_one_pair() -> None:
    builder = GraphBuilder("⊢ r")
    proof_child = builder.child(builder.root, "⊢ proof child")
    dead = builder.child(builder.root, "⊢ dead")
    builder.failure(dead)
    builder.duplicate(builder.root, dead)
    proof = builder.child(proof_child)
    assert len(sibling_pairs(label_graph(builder.record(proof)), CONFIG)) == 1
