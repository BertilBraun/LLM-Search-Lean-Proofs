import json
from pathlib import Path

from search_trees import add_child, new_tree

from lean_search.search import (
    Accounting,
    SearchResult,
    StepSource,
    StepStatistics,
    StopReason,
    read_tree,
    tree_record,
    write_tree,
)
from lean_search.search.records import from_json_object, to_json

RESULT = SearchResult(
    problem_name="t",
    proved=True,
    stop_reason=StopReason.PROVED,
    proof="intros\nsimp",
    proof_steps=("intros", "simp"),
    proof_sources=(StepSource.AUTOMATION, StepSource.AUTOMATION),
    accounting=Accounting(expansions=2, nodes=3, lean_seconds=0.5),
    solved_at=Accounting(expansions=2, nodes=3, lean_seconds=0.5),
    verification_failures=0,
    max_depth_reached=2,
    step_statistics=(StepStatistics("simp", attempts=2, children=1, proofs=1),),
)


def test_search_result_round_trips_through_json() -> None:
    assert from_json_object(SearchResult, json.loads(to_json(RESULT))) == RESULT


def test_tree_record_round_trips_through_a_compressed_file(tmp_path: Path) -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="intros")
    add_child(tree, child, ())
    record = tree_record(tree, "theorem t : p := by", RESULT)
    write_tree(tmp_path / "t.json.gz", record)
    assert read_tree(tmp_path / "t.json.gz") == record
