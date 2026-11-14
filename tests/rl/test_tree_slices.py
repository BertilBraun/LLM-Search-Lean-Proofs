import json
import random
from pathlib import Path

import pytest

from lean_search.rl.tree_slices import MANIFEST_FILE, slice_by_tokens, write_slices
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.rl.tree_summary import TreeSummary

TOKENS = [5_000, 12_000, 800, 30_000, 7_500, 9_000, 15_000, 2_200, 11_000, 6_400, 20_000, 3_300]


def entry(sequence: int, tokens: int, finished_time: float, proved: bool = False) -> TreeEntry:
    return TreeEntry(
        sequence=sequence,
        problem_name=f"problem_{sequence:02d}",
        phase=1,
        file=f"phase_0001/{sequence:07d}_problem_{sequence:02d}.json.gz",
        proved=proved,
        proofs=int(proved),
        expansions=4,
        policy_version=0,
        difficulty=10.0,
        wall_seconds=60.0,
        # Sequence numbers count starts; finish times are out of that order.
        finished_time=finished_time,
        summary=TreeSummary(generated_tokens=tokens),
    )


ENTRIES = [
    entry(sequence, tokens, 1000.0 + (sequence * 7) % 12, proved=sequence % 3 == 0)
    for sequence, tokens in enumerate(TOKENS)
]


def test_the_slices_partition_the_trees() -> None:
    slices = slice_by_tokens(ENTRIES, 4)
    assert sorted(tree.sequence for members in slices for tree in members) == list(range(len(TOKENS)))


def test_the_slices_token_sums_add_up_to_the_total() -> None:
    slices = slice_by_tokens(ENTRIES, 4)
    assert sum(tree.summary.generated_tokens for members in slices for tree in members) == sum(TOKENS)


def test_the_slices_follow_the_finish_order() -> None:
    times = [tree.finished_time for members in slice_by_tokens(ENTRIES, 4) for tree in members]
    assert times == sorted(times)


def test_the_cut_is_the_same_whatever_the_index_order() -> None:
    shuffled = list(ENTRIES)
    random.Random(3).shuffle(shuffled)
    assert slice_by_tokens(shuffled, 4) == slice_by_tokens(ENTRIES, 4)


def test_equal_trees_split_evenly() -> None:
    equal = [entry(sequence, 1_000, float(sequence)) for sequence in range(8)]
    assert [len(members) for members in slice_by_tokens(equal, 4)] == [2, 2, 2, 2]


def test_each_cut_falls_at_the_tree_boundary_nearest_its_share() -> None:
    """Totals 10, 20, 30, 40 after each tree: the halfway mark 50 lies nearest to 40 of 40 and 100."""
    trees = [entry(sequence, tokens, float(sequence)) for sequence, tokens in enumerate([10, 10, 10, 10, 60])]
    assert [len(members) for members in slice_by_tokens(trees, 2)] == [4, 1]


def test_trees_without_recorded_tokens_are_refused() -> None:
    with pytest.raises(ValueError, match="no generated tokens"):
        slice_by_tokens([entry(0, 0, 0.0)], 2)


def written(tmp_path: Path) -> Path:
    trees = tmp_path / "trees"
    (trees / "phase_0001").mkdir(parents=True)
    for tree in ENTRIES:
        (trees / tree.file).write_bytes(b"tree")
    write_slices(trees, slice_by_tokens(ENTRIES, 4), tmp_path / "slices")
    return tmp_path / "slices"


def test_a_slice_directory_links_its_tree_files(tmp_path: Path) -> None:
    slices = written(tmp_path)
    linked = sorted(path.resolve() for path in (slices / "slice_1").glob("*.json.gz"))
    expected = sorted((tmp_path / "trees" / tree.file).resolve() for tree in slice_by_tokens(ENTRIES, 4)[0])
    assert linked == expected


def test_a_slice_index_reads_back_as_a_tree_store(tmp_path: Path) -> None:
    slices = written(tmp_path)
    store = TreeStore(slices / "slice_2")
    assert all((store.directory / tree.file).is_file() for tree in store.entries)


def test_the_manifest_records_every_slices_tokens(tmp_path: Path) -> None:
    manifest = json.loads((written(tmp_path) / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert (
        sum(record["generated_tokens"] for record in manifest["slices"]) == manifest["generated_tokens"] == sum(TOKENS)
    )


def test_slices_are_cut_once(tmp_path: Path) -> None:
    slices = written(tmp_path)
    with pytest.raises(ValueError, match="exists"):
        write_slices(tmp_path / "trees", slice_by_tokens(ENTRIES, 4), slices)
