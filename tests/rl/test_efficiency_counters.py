"""The search efficiency counters reach the phase record, the Lean-load cell and the dashboard's edge counts."""

import dataclasses
import typing

from loop_fakes import solved_tree

from lean_search.data import Problem, Split
from lean_search.rl.lean_load import LeanLoad, load_cell
from lean_search.rl.phase_metrics import search_phase_record
from lean_search.rl.tree_statistics import EdgeKindCounts, GraphStatistics
from lean_search.search import Accounting, SearchResult, StepSource, StopReason, tree_record
from lean_search.search.graph_labels import EdgeKind, EdgeLabel
from lean_search.search.tree import FailureKind

PROBLEM = Problem("t", Split.VALID, "import Mathlib\n", "theorem t : True := by\n", "", "")


def phase_record(accounting: Accounting) -> object:
    result = SearchResult(PROBLEM.name, True, StopReason.PROVED, None, (), (), accounting, None, 0, 1)
    record = tree_record(solved_tree(PROBLEM), PROBLEM.formal_statement, result)
    # The record only carries the statistics along; the counters come from the trees' accounting.
    return search_phase_record([record, record], typing.cast(GraphStatistics, None))


def test_the_phase_record_sums_the_cached_tactics() -> None:
    assert phase_record(Accounting(cached_tactics=3, cache_saved_seconds=1.5)).cached_tactics == 6


def test_the_phase_record_sums_the_skipped_timeouts() -> None:
    assert phase_record(Accounting(skipped_timeouts=2)).skipped_timeouts == 4


def label(kind: EdgeKind, failure: FailureKind | None) -> EdgeLabel:
    return EdgeLabel(0, 0, StepSource.POLICY, "nlinarith", 1, kind, 0, kind, StepSource.POLICY, None, failure, 0, 1)


def test_the_edge_counts_show_skipped_tactics_apart_from_wall_clock_stops() -> None:
    counts = EdgeKindCounts.of(
        [
            label(EdgeKind.WALL_CLOCK_TIMEOUT, FailureKind.WALL_CLOCK_TIMEOUT),
            label(EdgeKind.WALL_CLOCK_TIMEOUT, FailureKind.SKIPPED_TIMEOUT),
            label(EdgeKind.WALL_CLOCK_TIMEOUT, FailureKind.SKIPPED_TIMEOUT),
        ]
    )
    assert (counts.wall_clock_timeout, counts.skipped_timeout) == (1, 2)


LOAD = LeanLoad("all", 10, 4, 2, 1, 100, 50.0, 0.5)


def test_the_load_cell_names_skipped_tactics_beside_the_stops() -> None:
    assert load_cell(dataclasses.replace(LOAD, skipped_timeouts=3)) == "4 (2) + 3 skipped / 1 / 0.50"


def test_the_load_cell_without_skips_reads_as_before() -> None:
    assert load_cell(LOAD) == "4 (2) / 1 / 0.50"


def test_the_phase_record_counts_the_proofs_that_need_the_variant() -> None:
    result = SearchResult(PROBLEM.name, True, StopReason.PROVED, None, (), (), Accounting(), None, 0, 1)
    record = tree_record(solved_tree(PROBLEM), PROBLEM.formal_statement, result)
    proved = [node.node_id for node in record.nodes if node.goals == ()]
    nodes = tuple(
        dataclasses.replace(node, plain_verified=False) if node.node_id in proved else node for node in record.nodes
    )
    phase = search_phase_record([dataclasses.replace(record, nodes=nodes)], typing.cast(GraphStatistics, None))
    assert (phase.plain_checked_proofs, phase.plain_failed_proofs, phase.variant_only_trees) == (1, 1, 1)
