from pathlib import Path

import pytest
from value_trees import TreeBuilder

from lean_search.corpora.records import DataSplit, TracedStep
from lean_search.search import FailureKind, NodeStatus, TreeRecord
from lean_search.value.labels import (
    LabelCounts,
    LabelKind,
    TreeLabelConfig,
    ValueExample,
    label_counts,
    merge_duplicates,
    read_examples,
    traced_examples,
    tree_examples,
    write_examples,
)

CONFIG = TreeLabelConfig(at_least_weight=0.25, dead_weight=0.5)


def labels_by_goal(record: TreeRecord) -> dict[str, tuple[LabelKind, int]]:
    return {example.goals[0]: (example.kind, example.steps) for example in tree_examples(record, "run", CONFIG)}


def solved_tree() -> TreeRecord:
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    proof = builder.child(a)
    builder.child(builder.root, "⊢ b")
    c = builder.child(builder.root, "⊢ c")
    builder.child(c, "⊢ d")
    e = builder.child(builder.root, "⊢ e")
    builder.failure(e)
    builder.failure(e, FailureKind.HEARTBEAT_TIMEOUT)
    f = builder.child(builder.root, "⊢ f")
    builder.duplicate(f, a)
    g = builder.child(builder.root, "⊢ g")
    builder.failure(g, FailureKind.REPL_FAILURE)
    return builder.record(proof)


@pytest.mark.parametrize(
    ("goal", "label"),
    [
        ("⊢ r", (LabelKind.EXACT, 2)),
        ("⊢ a", (LabelKind.EXACT, 1)),
        ("⊢ b", (LabelKind.AT_LEAST, 1)),
        ("⊢ c", (LabelKind.AT_LEAST, 2)),
        ("⊢ d", (LabelKind.AT_LEAST, 1)),
        ("⊢ e", (LabelKind.DEAD, 0)),
        ("⊢ f", (LabelKind.EXACT, 2)),
        ("⊢ g", (LabelKind.AT_LEAST, 1)),
    ],
)
def test_solved_tree_labels(goal: str, label: tuple[LabelKind, int]) -> None:
    assert labels_by_goal(solved_tree())[goal] == label


def test_proved_states_get_no_label() -> None:
    record = solved_tree()
    assert len(tree_examples(record, "run", CONFIG)) == sum(1 for node in record.nodes if node.goals)


def test_infrastructure_failures_keep_a_failed_node_censored() -> None:
    record = solved_tree()
    (node,) = (node for node in record.nodes if node.goals == ("⊢ g",))
    assert (node.status, labels_by_goal(record)["⊢ g"][0]) == (NodeStatus.FAILED, LabelKind.AT_LEAST)


@pytest.mark.parametrize(("goal", "weight"), [("⊢ r", 1.0), ("⊢ b", 0.25), ("⊢ e", 0.5)])
def test_labels_carry_their_kinds_weight(goal: str, weight: float) -> None:
    examples = tree_examples(solved_tree(), "run", CONFIG)
    assert next(example.weight for example in examples if example.goals == (goal,)) == weight


def test_exact_label_takes_the_fewest_edges_over_duplicate_edges() -> None:
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    b = builder.child(a, "⊢ b")
    c = builder.child(b, "⊢ c")
    proof = builder.child(c)
    shortcut = builder.child(builder.root, "⊢ x")
    builder.duplicate(shortcut, c)
    assert labels_by_goal(builder.record(proof))["⊢ r"] == (LabelKind.EXACT, 3)


def test_duplicate_edge_into_an_open_node_keeps_the_parent_alive() -> None:
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    b = builder.child(builder.root, "⊢ b")
    builder.duplicate(a, b)
    assert labels_by_goal(builder.record())["⊢ a"] == (LabelKind.AT_LEAST, 2)


def test_duplicate_edge_back_to_an_alive_ancestor_keeps_a_node_alive() -> None:
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    builder.duplicate(a, builder.root)
    builder.child(builder.root, "⊢ b")
    assert labels_by_goal(builder.record())["⊢ a"] == (LabelKind.AT_LEAST, 3)


def test_exhausted_tree_is_dead_from_the_root() -> None:
    builder = TreeBuilder("⊢ r")
    for goal in ("⊢ a", "⊢ b"):
        builder.failure(builder.child(builder.root, goal))
    assert labels_by_goal(builder.record())["⊢ r"] == (LabelKind.DEAD, 0)


def test_a_step_closing_the_goal_with_a_failed_verification_is_a_dead_end() -> None:
    builder = TreeBuilder("⊢ r")
    a = builder.child(builder.root, "⊢ a")
    builder.child(a).status = NodeStatus.FAILED
    assert labels_by_goal(builder.record())["⊢ a"] == (LabelKind.DEAD, 0)


def example(goals: tuple[str, ...], kind: LabelKind, steps: int, identifier: str = "p") -> ValueExample:
    return ValueExample(goals, kind, steps, 1.0, "source", identifier, 0)


@pytest.mark.parametrize(
    ("examples", "kept"),
    [
        ([example(("⊢ x",), LabelKind.EXACT, 5), example(("⊢ x",), LabelKind.EXACT, 2)], (LabelKind.EXACT, 2)),
        ([example(("⊢ x",), LabelKind.DEAD, 0), example(("⊢ x",), LabelKind.EXACT, 7)], (LabelKind.EXACT, 7)),
        ([example(("⊢ x",), LabelKind.AT_LEAST, 3), example(("⊢ x",), LabelKind.DEAD, 0)], (LabelKind.DEAD, 0)),
        ([example(("⊢ x",), LabelKind.AT_LEAST, 2), example(("⊢ x",), LabelKind.AT_LEAST, 4)], (LabelKind.AT_LEAST, 4)),
    ],
)
def test_merge_keeps_the_most_informative_label(examples: list[ValueExample], kept: tuple[LabelKind, int]) -> None:
    (merged,) = merge_duplicates(examples)
    assert (merged.kind, merged.steps) == kept


def test_merge_compares_normalized_goals() -> None:
    examples = [example(("x  : ℕ\n⊢ x = x",), LabelKind.EXACT, 3), example(("x : ℕ\n\n⊢  x = x ",), LabelKind.EXACT, 1)]
    assert len(merge_duplicates(examples)) == 1


def test_merge_keeps_goal_order_significant() -> None:
    examples = [example(("⊢ a", "⊢ b"), LabelKind.EXACT, 3), example(("⊢ b", "⊢ a"), LabelKind.EXACT, 3)]
    assert len(merge_duplicates(examples)) == 2


def traced_step(step_index: int, total_steps: int) -> TracedStep:
    return TracedStep(
        source="lean_workbook",
        proof_identifier="lean_workbook/1",
        statement_identifier="s1",
        split=DataSplit.TRAIN,
        header="import Mathlib",
        formal_statement="theorem t : True := by",
        step_index=step_index,
        total_steps=total_steps,
        remaining_steps=total_steps - step_index,
        goals_before=(f"⊢ goal {step_index}",),
        step="simp",
        goals_after=(),
        previous_steps=(),
        heartbeats=0,
        elapsed_seconds=0.0,
    )


def test_traced_step_is_an_exact_label_of_its_remaining_steps() -> None:
    (traced,) = traced_examples([traced_step(1, 4)])
    assert (traced.goals, traced.kind, traced.steps, traced.depth) == (("⊢ goal 1",), LabelKind.EXACT, 3, 1)


def test_label_counts_bin_exact_and_censored_steps() -> None:
    examples = [
        example(("⊢ a",), LabelKind.EXACT, 1),
        example(("⊢ b",), LabelKind.EXACT, 12),
        example(("⊢ c",), LabelKind.AT_LEAST, 2),
        example(("⊢ d",), LabelKind.DEAD, 0),
    ]
    assert label_counts(examples) == LabelCounts(
        examples=4,
        exact=2,
        at_least=1,
        dead=1,
        exact_bins=(1, 0, 0, 0, 0, 0, 0, 1),
        at_least_bins=(0, 1, 0, 0, 0, 0, 0, 0),
    )


def test_examples_survive_a_round_trip_through_json_lines(tmp_path: Path) -> None:
    examples = [example(("x : ℕ", "⊢ x = x"), LabelKind.AT_LEAST, 2), example(("⊢ y",), LabelKind.DEAD, 0)]
    write_examples(tmp_path / "examples.jsonl", examples)
    assert list(read_examples(tmp_path / "examples.jsonl")) == examples
