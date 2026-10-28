import dataclasses
import json

import pytest
from graph_trees import GraphBuilder
from tactic_trees import example_tree

from lean_search.rl.grpo_groups import RewardConfig, policy_groups
from lean_search.rl.tree_statistics import (
    EdgeKindCounts,
    GraphStatistics,
    SizeHistogram,
    graph_statistics,
    total_statistics,
)
from lean_search.search import StepSource, TreeRecord
from lean_search.search.graph_labels import EdgeKind, label_graph
from lean_search.search.tactic_labels import policy_tactics
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)

READOUT = RemainingStepsReadout()
REWARDS = RewardConfig()


def statistics_of(record: TreeRecord) -> GraphStatistics:
    labels = label_graph(record)
    estimates = recorded_estimates(record, READOUT)
    targets = value_targets(record, labels, estimates, ValueTargetConfig())
    tactics = policy_tactics(record, labels)
    groups = policy_groups(record, labels, tactics, estimates, REWARDS)
    return graph_statistics(record, labels, targets, tactics, groups)


def statistics() -> GraphStatistics:
    builder = GraphBuilder("⊢ r", root_value=3.0)
    sweep_failure = builder.failure(builder.root, text="omega", source=StepSource.AUTOMATION)
    a = builder.child(builder.root, "⊢ a", value=2.0)
    b = builder.child(builder.root, "⊢ b", value=2.5)
    builder.duplicate(b, a)
    builder.duplicate(b, b)
    builder.repeat(builder.root, sweep_failure)
    dead = builder.child(builder.root, "⊢ dead", value=1.0)
    builder.failure(dead)
    builder.child(builder.root, "⊢ never", value=5.0)
    proof = builder.child(a, tactics=3)
    return statistics_of(builder.record(proof))


@pytest.mark.parametrize(
    ("field", "count"),
    [
        ("transpositions_into_proof_graph", 1),
        ("off_path_transpositions_into_proof_path", 1),
        ("off_path_proof_graph_nodes", 1),
        ("proof_path_nodes", 3),
        ("dead_ends", 1),
        ("never_expanded_nodes", 1),
        ("repeats_of_failed_automation", 1),
        ("off_graph_targets", 1),
        ("expanded_without_target", 0),
        ("proof_graph_targets", 3),
        ("groups", 3),
        ("proofs", 1),
        ("proof_tactics", 4),
        ("proof_blocks", 2),
    ],
)
def test_tree_counts(field: str, count: int) -> None:
    assert getattr(statistics(), field) == count


@pytest.mark.parametrize(
    ("kind", "count"),
    [(EdgeKind.LEAN_ERROR, 2), (EdgeKind.NEW_STATE, 5), (EdgeKind.TRANSPOSITION, 1), (EdgeKind.NO_PROGRESS, 1)],
)
def test_edge_kind_counts(kind: EdgeKind, count: int) -> None:
    assert getattr(statistics().edges, kind.value) == count


def test_edge_kind_counts_cover_every_kind() -> None:
    assert {field.name for field in dataclasses.fields(EdgeKindCounts)} == {kind.value for kind in EdgeKind}


@pytest.mark.parametrize(
    ("field", "count"),
    [("proof_graph", 6), ("off_graph", 1), ("unknown", 2), ("no_progress", 1), ("redundant_hypothesis", 1)],
)
def test_policy_tactic_counts_of_the_example(field: str, count: int) -> None:
    assert getattr(statistics_of(example_tree()).policy_tactics, field) == count


def test_group_tactics_count_only_the_groups() -> None:
    example = statistics_of(example_tree())
    assert example.policy_tactics.failing - example.group_tactics.failing == 1


def test_size_histogram_buckets() -> None:
    assert SizeHistogram.of([1, 2, 3, 4, 40]).buckets == (1, 2, 1, 0, 0, 1)


def test_run_total_adds_tree_counts() -> None:
    assert total_statistics([statistics(), statistics()]).edges.new_state == 10


def test_run_total_adds_tactic_counts() -> None:
    assert total_statistics([statistics(), statistics()]).policy_tactics.total == 2 * statistics().policy_tactics.total


def test_statistics_serialize_to_json() -> None:
    assert json.loads(json.dumps(dataclasses.asdict(statistics())))["edges"]["transposition"] == 1


def test_harvest_counts_the_proofs_after_the_first() -> None:
    builder = GraphBuilder("⊢ p")
    first = builder.child(builder.root, text="close")
    second_state = builder.child(builder.root, "⊢ q", text="detour")
    second = builder.child(second_state, text="close too")
    builder.tree.mark_proof_path(second)
    record = builder.record(first)
    accounting = dataclasses.replace(record.result.accounting, expansions=2, harvest_expansions=1, proofs=2)
    record = dataclasses.replace(record, result=dataclasses.replace(record.result, accounting=accounting))
    assert (statistics_of(record).harvest_proofs, statistics_of(record).proofs) == (1, 2)
