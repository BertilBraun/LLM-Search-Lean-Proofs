import dataclasses
import json

import pytest
from graph_trees import GraphBuilder

from lean_search.rl.grpo_groups import RewardConfig, RewardMode, policy_groups
from lean_search.rl.tree_statistics import (
    EdgeKindCounts,
    GraphStatistics,
    SizeHistogram,
    graph_statistics,
    total_statistics,
)
from lean_search.search import StepSource
from lean_search.search.graph_labels import EdgeKind, label_graph
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)

READOUT = RemainingStepsReadout()
REWARDS = RewardConfig()


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
    proof = builder.child(a)
    record = builder.record(proof)
    labels = label_graph(record)
    estimates = recorded_estimates(record, READOUT)
    targets = value_targets(record, labels, estimates, READOUT, ValueTargetConfig())
    groups = policy_groups(record, labels, estimates, targets, REWARDS)
    outcome_groups = policy_groups(
        record, labels, estimates, targets, dataclasses.replace(REWARDS, mode=RewardMode.OUTCOME_ONLY)
    )
    return graph_statistics(record, labels, targets, groups, outcome_groups, REWARDS)


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
        ("dead_end_targets", 1),
        ("proof_graph_targets", 3),
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


def test_size_histogram_buckets() -> None:
    assert SizeHistogram.of([1, 2, 3, 4, 40]).buckets == (1, 2, 1, 0, 0, 1)


def test_run_total_adds_tree_counts() -> None:
    assert total_statistics([statistics(), statistics()]).edges.new_state == 10


def test_run_total_counts_trees() -> None:
    assert total_statistics([statistics(), statistics()]).trees == 2


def test_statistics_serialize_to_json() -> None:
    assert json.loads(json.dumps(dataclasses.asdict(statistics())))["edges"]["transposition"] == 1
