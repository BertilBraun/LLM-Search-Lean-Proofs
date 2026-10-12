from pathlib import Path

from loop_fixtures import attempt, solved_tree

from lean_search.expert_iteration.shards import (
    ATTEMPTS_FILE,
    Decision,
    ShardWriter,
    all_attempts,
    closed_shards,
    read_attempt_tree,
    read_attempts,
    read_shard_summary,
    recover_open_shards,
)
from lean_search.search.records import to_json


def write_attempts(writer: ShardWriter, names: list[str], version: int = 0) -> None:
    for name in names:
        writer.write(attempt(name, version=version, proved=True, decision=Decision.SOLVED), solved_tree(name))


def test_an_attempt_and_its_tree_read_back(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    write_attempts(writer, ["a.x"])
    writer.close()
    (shard,) = closed_shards(tmp_path)
    (written,) = read_attempts(shard)
    assert read_attempt_tree(shard, written).problem_name == "a.x"


def test_shards_rotate_after_their_attempt_limit(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=2, max_seconds=1e9)
    write_attempts(writer, ["a.1", "a.2", "a.3"])
    writer.close()
    assert [read_shard_summary(shard).attempts for shard in closed_shards(tmp_path)] == [2, 1]


def test_an_open_shard_is_not_closed(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    write_attempts(writer, ["a.1"])
    assert closed_shards(tmp_path) == []


def test_a_shard_records_the_versions_of_its_attempts(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    write_attempts(writer, ["a.1"], version=3)
    write_attempts(writer, ["a.2"], version=4)
    writer.close()
    (shard,) = closed_shards(tmp_path)
    assert read_shard_summary(shard).versions == (3, 4)


def test_recovery_closes_a_shard_without_the_line_a_kill_cut(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    write_attempts(writer, ["a.1"])
    assert writer.shard is not None
    with (writer.shard / ATTEMPTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(to_json(attempt("a.2"))[:50])
    (summary,) = recover_open_shards(tmp_path)
    assert summary.attempts == 1


def test_the_attempt_log_spans_every_shard_in_order(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=1, max_seconds=1e9)
    write_attempts(writer, ["a.1", "a.2", "a.3"])
    assert [record.problem_name for record in all_attempts(tmp_path)] == ["a.1", "a.2", "a.3"]
