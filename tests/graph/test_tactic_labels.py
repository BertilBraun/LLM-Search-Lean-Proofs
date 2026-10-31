import pytest
from graph_trees import GraphBuilder
from tactic_trees import (
    AFTER_FIRST_HAVE,
    BARE_HAVE,
    CLAIM,
    CONSTRUCTOR,
    CONTEXT,
    COPY,
    E_FIRST_THEN_FAILING,
    ERROR,
    FIRST_THEN_FAILING,
    NO_OP,
    PROOF,
    ROOT,
    TARGET,
    THROUGH_SECOND_HAVE,
    claim_tree,
    example_tree,
)

from lean_search.rl.grpo_groups import RewardConfig
from lean_search.search import TreeRecord
from lean_search.search.graph_labels import NodeClass, label_graph
from lean_search.search.tactic_labels import TacticLabel, TacticLabelCounts, TacticOutcome, policy_tactics

PROOF_GRAPH = TacticLabel.PROOF_GRAPH
OFF_GRAPH = TacticLabel.OFF_GRAPH
UNKNOWN = TacticLabel.UNKNOWN
NO_PROGRESS = TacticLabel.NO_PROGRESS
REDUNDANT = TacticLabel.REDUNDANT_HYPOTHESIS
FAILING = TacticLabel.FAILING
MASKED = TacticLabel.MASKED
UNPROVED_CLAIM = TacticLabel.UNPROVED_CLAIM
MIN_EXPANDED_NODES = RewardConfig().off_graph_min_expanded_nodes


def outcomes(record: TreeRecord, text: str, min_expanded_nodes: int = MIN_EXPANDED_NODES) -> tuple[TacticOutcome, ...]:
    (edge,) = [edge for edge in record.edges if edge.text == text]
    return policy_tactics(record, label_graph(record), min_expanded_nodes)[edge.edge_id]


def labels_of(record: TreeRecord, text: str, min_expanded_nodes: int = MIN_EXPANDED_NODES) -> tuple[TacticLabel, ...]:
    return tuple(outcome.label for outcome in outcomes(record, text, min_expanded_nodes))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PROOF, (PROOF_GRAPH, PROOF_GRAPH, PROOF_GRAPH)),
        (FIRST_THEN_FAILING, (PROOF_GRAPH, FAILING, MASKED)),
        (E_FIRST_THEN_FAILING, (UNKNOWN, FAILING, MASKED)),
        (COPY, (REDUNDANT,)),
        (NO_OP, (NO_PROGRESS,)),
        (ERROR, (FAILING,)),
        ("", (FAILING,)),
        (CONSTRUCTOR, (UNPROVED_CLAIM,)),
        (THROUGH_SECOND_HAVE, (PROOF_GRAPH, PROOF_GRAPH, UNKNOWN)),
    ],
    ids=[
        "proof",
        "same first have",
        "never expanded",
        "redundant",
        "no-op",
        "error",
        "unparsed",
        "dead end adding goals",
        "intermediate state",
    ],
)
def test_tactic_labels_of_the_example(text: str, expected: tuple[TacticLabel, ...]) -> None:
    assert labels_of(example_tree(), text) == expected


def test_closing_tactic_closes_the_goal() -> None:
    assert outcomes(example_tree(), PROOF)[-1].goals_closed == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [(PROOF, (2, 1, 0)), (FIRST_THEN_FAILING, (2, None, None)), (THROUGH_SECOND_HAVE, (2, 1, None))],
    ids=["proof", "same first have", "intermediate state"],
)
def test_proof_graph_tactics_know_their_remaining_steps(text: str, expected: tuple[int | None, ...]) -> None:
    assert tuple(outcome.remaining_steps for outcome in outcomes(example_tree(), text)) == expected


def test_state_on_two_routes_to_the_proof_takes_the_shorter() -> None:
    builder = GraphBuilder("⊢ p")
    long_route = builder.child(builder.root, text="long", tactics=3, tactic_goals=(("⊢ q",), ("⊢ r",), ()))
    builder.tree.mark_proof_path(long_route)
    proof = builder.child(builder.root, text="short", tactics=2, tactic_goals=(("⊢ q",), ()))
    builder.child(builder.root, "⊢ s", text="detour", tactics=2, tactic_goals=(("⊢ q",), ("⊢ s",)))
    assert outcomes(builder.record(proof), "detour")[0].remaining_steps == 1


def test_node_reached_by_an_intermediate_proof_state_joins_the_proof_graph() -> None:
    record = example_tree()
    (node,) = [node for node in record.nodes if node.goals == (AFTER_FIRST_HAVE,)]
    labels = label_graph(record)
    assert (labels.node_classes[node.node_id], labels.remaining_steps[node.node_id]) == (NodeClass.PROOF_GRAPH, 2)


def test_tactic_returning_to_the_state_before_the_block_makes_no_progress() -> None:
    builder = GraphBuilder("⊢ p")
    builder.duplicate(
        builder.root, builder.root, text="intro\nrevert", tactics=2, tactic_goals=(("h : q\n⊢ r",), ("⊢ p",))
    )
    assert labels_of(builder.record(), "intro\nrevert") == (UNKNOWN, NO_PROGRESS)


def test_tactic_back_to_an_ancestor_makes_no_progress() -> None:
    builder = GraphBuilder("⊢ p")
    child = builder.child(builder.root, "h : q\n⊢ r", text="intro")
    builder.duplicate(child, builder.root, text="revert h")
    assert labels_of(builder.record(), "revert h") == (NO_PROGRESS,)


def test_old_record_block_on_a_route_to_the_proof_is_on_the_proof_graph() -> None:
    builder = GraphBuilder("⊢ p")
    child = builder.child(builder.root, "⊢ q", text="first\nsecond", tactics=2)
    proof = builder.child(child, text="close")
    assert labels_of(builder.record(proof), "first\nsecond") == (PROOF_GRAPH, PROOF_GRAPH)


def test_old_record_block_off_any_route_knows_only_its_last_state() -> None:
    builder = GraphBuilder("⊢ p")
    other = builder.child(builder.root, "⊢ q", text="first\nsecond", tactics=2)
    builder.failure(other)
    assert labels_of(builder.record(), "first\nsecond") == (UNKNOWN, OFF_GRAPH)


def detour_tree(expanded_nodes: int) -> TreeRecord:
    """A detour off the proof graph: a chain of `expanded_nodes` expanded nodes ending in a live child."""
    builder = GraphBuilder("⊢ p")
    node = builder.child(builder.root, "⊢ q 0", text="detour")
    for index in range(1, expanded_nodes + 1):
        node = builder.child(node, f"⊢ q {index}")
    return builder.record()


@pytest.mark.parametrize(
    ("expanded_nodes", "label"),
    [(1, UNKNOWN), (MIN_EXPANDED_NODES - 1, UNKNOWN), (MIN_EXPANDED_NODES, OFF_GRAPH), (8, OFF_GRAPH)],
)
def test_off_graph_state_needs_enough_expanded_nodes_in_its_subtree(expanded_nodes: int, label: TacticLabel) -> None:
    assert labels_of(detour_tree(expanded_nodes), "detour") == (label,)


def test_dead_end_expanded_once_stays_off_graph() -> None:
    builder = GraphBuilder("⊢ p")
    dead_end = builder.child(builder.root, "⊢ q", text="detour")
    builder.failure(dead_end)
    assert labels_of(builder.record(), "detour") == (OFF_GRAPH,)


def test_unverified_proof_fails_on_its_last_tactic() -> None:
    builder = GraphBuilder("⊢ p")
    builder.child(builder.root, text="sorry_like")
    assert labels_of(builder.record(), "sorry_like") == (FAILING,)


def test_label_counts_cover_every_label() -> None:
    assert TacticLabelCounts.of(TacticLabel).total == len(TacticLabel)


FILLER = f"{CONTEXT}\nh₂ : 0 < (1:ℝ)\n{TARGET}"
LOCAL_FACT = f"{CONTEXT}\nh₂ : 0 < x ^ 2 + 1\n{TARGET}"
FALSE_CLAIM = (f"{CONTEXT}\n⊢ 0 < ((0:ℝ))", f"{CONTEXT}\nh₂ : 0 < ((0:ℝ))\n{TARGET}")


def test_bare_have_whose_claim_is_never_proved_is_an_unproved_claim() -> None:
    assert labels_of(claim_tree(), BARE_HAVE) == (UNPROVED_CLAIM,)


def test_bare_have_on_the_proof_graph_stays_on_it() -> None:
    assert labels_of(claim_tree(on_proof_graph=True), BARE_HAVE) == (PROOF_GRAPH,)


def test_bare_have_whose_claim_a_descendant_proves_is_no_unproved_claim() -> None:
    assert labels_of(claim_tree(proved_below=True), BARE_HAVE) == (UNKNOWN,)


def test_bare_have_whose_claim_the_block_proves_is_no_unproved_claim() -> None:
    builder = GraphBuilder(ROOT)
    text = f"{BARE_HAVE}\nlinear_combination h₁ - h₀\nring_nf"
    after = f"{CONTEXT}\nh₂ : x = -4\n⊢ e = 11"
    builder.child(builder.root, after, text=text, tactics=3, tactic_goals=(CLAIM, (AFTER_FIRST_HAVE,), (after,)))
    record = builder.record(builder.child(builder.root, text="close"))
    assert labels_of(record, text)[0] == UNKNOWN


def single_step_tree(goals: str, proved: bool = False) -> TreeRecord:
    builder = GraphBuilder(ROOT)
    child = builder.child(builder.root, goals, text="have", tactic_goals=((goals,),))
    return builder.record(builder.child(child if proved else builder.root, text="close"))


def test_closed_form_filler_off_the_proof_graph_is_redundant() -> None:
    assert labels_of(single_step_tree(FILLER), "have") == (REDUNDANT,)


def test_hypothesis_mentioning_a_local_variable_is_no_filler() -> None:
    assert labels_of(single_step_tree(LOCAL_FACT), "have") == (UNKNOWN,)


def test_closed_form_hypothesis_on_the_proof_graph_stays_on_it() -> None:
    assert labels_of(single_step_tree(FILLER, proved=True), "have") == (PROOF_GRAPH,)


def test_bare_have_of_a_false_closed_form_claim_is_redundant() -> None:
    builder = GraphBuilder(ROOT)
    builder.child(builder.root, *FALSE_CLAIM, text="have h₂ : 0 < ((0:ℝ))", tactic_goals=(FALSE_CLAIM,))
    record = builder.record(builder.child(builder.root, text="close"))
    assert labels_of(record, "have h₂ : 0 < ((0:ℝ))") == (REDUNDANT,)
