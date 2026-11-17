import dataclasses
import json
import random
from pathlib import Path

import pytest

from lean_search.rl.tree_slices import MANIFEST_FILE, character_band, slice_by_tokens, write_slices
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
        difficulty=5.0 + 4 * sequence,
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
    write_slices(trees, slice_by_tokens(ENTRIES, 4), tmp_path / "slices", len(ENTRIES))
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
        write_slices(tmp_path / "trees", slice_by_tokens(ENTRIES, 4), slices, len(ENTRIES))


@pytest.mark.parametrize(
    ("difficulty", "band"), [(4.99, "0-499"), (15.0, "1500-1999"), (45.0, "4500+"), (None, "unknown")]
)
def test_a_trees_character_band_is_its_difficulty_times_100(difficulty: float | None, band: str) -> None:
    assert character_band(dataclasses.replace(entry(0, 1, 0.0), difficulty=difficulty)) == band


def manifest_slices(tmp_path: Path) -> list[dict]:
    return json.loads((written(tmp_path) / MANIFEST_FILE).read_text(encoding="utf-8"))["slices"]


def test_the_manifest_counts_every_slices_trees_by_character_band(tmp_path: Path) -> None:
    records = manifest_slices(tmp_path)
    by_band = [sum(count["trees"] for count in record["by_character_band"]) for record in records]
    assert by_band == [record["trees"] for record in records]


def test_the_manifest_records_each_slices_difficulty_range(tmp_path: Path) -> None:
    first = manifest_slices(tmp_path)[0]
    members = slice_by_tokens(ENTRIES, 4)[0]
    expected = (min(tree.difficulty for tree in members), max(tree.difficulty for tree in members))
    assert (first["difficulty_low"], first["difficulty_high"]) == expected


def test_a_statement_searched_again_counts_as_seen_before(tmp_path: Path) -> None:
    trees = tmp_path / "trees"
    (trees / "phase_0001").mkdir(parents=True)
    repeated = [dataclasses.replace(tree, problem_name="same") for tree in ENTRIES]
    for tree in repeated:
        (trees / tree.file).write_bytes(b"tree")
    manifest = write_slices(trees, slice_by_tokens(repeated, 2), tmp_path / "slices", len(repeated))
    assert [record.statements_seen_before for record in manifest.slices] == [0, 1]


def test_one_slice_holds_every_tree_in_finish_order() -> None:
    (members,) = slice_by_tokens(ENTRIES, 1)
    assert list(members) == sorted(ENTRIES, key=lambda tree: tree.finished_time)


def test_one_slice_links_every_tree_and_records_them_all(tmp_path: Path) -> None:
    trees = tmp_path / "trees"
    (trees / "phase_0001").mkdir(parents=True)
    for tree in ENTRIES:
        (trees / tree.file).write_bytes(b"tree")
    manifest = write_slices(trees, slice_by_tokens(ENTRIES, 1), tmp_path / "slices", len(ENTRIES))
    linked = len(list((tmp_path / "slices" / "slice_1").glob("*.json.gz")))
    assert (linked, manifest.trees, manifest.generated_tokens) == (len(ENTRIES), len(ENTRIES), sum(TOKENS))


CLASH = [ENTRIES[0], dataclasses.replace(ENTRIES[1], file=ENTRIES[0].file.replace("phase_0001", "phase_0002"))]


def test_trees_of_one_name_in_one_slice_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="share one"):
        write_slices(tmp_path / "trees", slice_by_tokens(CLASH, 1), tmp_path / "slices", len(CLASH))


def test_trees_of_one_name_in_different_slices_are_linked(tmp_path: Path) -> None:
    trees = tmp_path / "trees"
    for tree in CLASH:
        (trees / tree.file).parent.mkdir(parents=True, exist_ok=True)
        (trees / tree.file).write_bytes(b"tree")
    manifest = write_slices(trees, slice_by_tokens(CLASH, 2), tmp_path / "slices", len(CLASH))
    assert manifest.trees == 2
