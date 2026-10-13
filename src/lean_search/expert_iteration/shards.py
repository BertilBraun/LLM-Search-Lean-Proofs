"""The searches' output: append-only shards of search stages and their trees, each stage tagged with its model.

A shard is a directory shards/<sequence>/ with attempts.jsonl (one AttemptRecord per search stage, written after the
stage's tree) and trees/<problem>.s<stage>.json.gz (plus .reasoning.json.gz with the thoughts behind each step when
the policy thinks). A search that escalates to a further stage writes a record per stage; only its last record carries
the tree. A shard is open while an OPEN marker exists and immutable once closed (summary.json written, marker removed);
readers use closed shards only. A shard left open by a crash is closed on the next start, without a line a kill cut
short.
"""

import dataclasses
import datetime
import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.thinking import TreeReasoning, read_reasoning, write_reasoning
from lean_search.search import StopReason, TreeRecord, read_tree, write_tree
from lean_search.search.records import from_json_object, to_json

OPEN_MARKER = "OPEN"
ATTEMPTS_FILE = "attempts.jsonl"
SUMMARY_FILE = "summary.json"


class Decision(StrEnum):
    SOLVED = "solved"
    # The search continues with the next stage's budget on the same tree.
    ESCALATED = "escalated"
    RETIRED_LOAD_FAILURE = "retired_load_failure"
    RETIRED_LAST_STAGE = "retired_last_stage"
    # Every open state was expanded without a proof.
    RETIRED_DEAD = "retired_dead"
    RETIRED_UNPROMISING = "retired_unpromising"


@dataclass(frozen=True)
class AttemptRecord:
    """One stage of a statement's search: costs are the stage's own, sizes are the tree's so far."""

    problem_name: str
    source: str
    stage: int
    # The published version when the stage started.
    model_version: int
    # The stage's total budget (over all stages so far).
    max_expansions: int
    started_at: str
    finished_at: str
    # The first proof was found in this stage.
    proved: bool
    stop_reason: StopReason
    proof_steps: int
    # Expansions of this stage, without harvesting.
    expansions: int
    total_expansions: int
    nodes: int
    wall_seconds: float
    lean_seconds: float
    prompt_tokens: int
    generated_tokens: int
    value_prompt_tokens: int
    # The value model's h at the root; None without a value model.
    root_value: float | None
    best_frontier_value: float | None
    frontier_exhausted: bool
    max_depth: int
    # Further proofs and expansions after the first proof (harvesting near-complete states).
    harvested_proofs: int
    harvest_expansions: int
    decision: Decision
    # Relative to the shard directory, on a search's last record only; None when the statement did not start.
    tree_file: str | None
    reasoning_file: str | None = None
    # Whether the curriculum fed the statement with its known proof verified here; None for the open pool.
    certified: bool | None = None

    @property
    def proofs(self) -> int:
        return self.proved + self.harvested_proofs


@dataclass(frozen=True)
class ShardSummary:
    name: str
    attempts: int
    proofs: int
    versions: tuple[int, ...]
    opened_at: str
    closed_at: str


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def tree_file_name(problem_name: str, stage: int) -> str:
    return f"trees/{problem_name}.s{stage}.json.gz"


def reasoning_file_name(problem_name: str, stage: int) -> str:
    return f"trees/{problem_name}.s{stage}.reasoning.json.gz"


def read_attempts(shard: Path) -> list[AttemptRecord]:
    """Complete lines only: a kill can cut the last line short."""
    path = shard / ATTEMPTS_FILE
    if not path.exists():
        return []
    attempts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            attempts.append(from_json_object(AttemptRecord, json.loads(line)))
        except json.JSONDecodeError:
            continue
    return attempts


def read_attempt_tree(shard: Path, attempt: AttemptRecord) -> TreeRecord:
    assert attempt.tree_file is not None, attempt.problem_name
    return read_tree(shard / attempt.tree_file)


def read_attempt_reasoning(shard: Path, attempt: AttemptRecord) -> TreeReasoning | None:
    return None if attempt.reasoning_file is None else read_reasoning(shard / attempt.reasoning_file)


def is_open(shard: Path) -> bool:
    return (shard / OPEN_MARKER).exists()


def closed_shards(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_dir() and (path / SUMMARY_FILE).exists())


def read_shard_summary(shard: Path) -> ShardSummary:
    return from_json_object(ShardSummary, json.loads((shard / SUMMARY_FILE).read_text(encoding="utf-8")))


def close_shard(shard: Path, opened_at: str) -> ShardSummary:
    attempts = read_attempts(shard)
    # Rewrites the attempts without a cut line, so the closed shard is clean.
    (shard / ATTEMPTS_FILE).write_text("".join(to_json(attempt) + "\n" for attempt in attempts), encoding="utf-8")
    summary = ShardSummary(
        name=shard.name,
        attempts=len(attempts),
        proofs=sum(attempt.proofs for attempt in attempts),
        versions=tuple(sorted({attempt.model_version for attempt in attempts})),
        opened_at=opened_at,
        closed_at=now(),
    )
    temporary = shard / (SUMMARY_FILE + ".tmp")
    temporary.write_text(to_json(summary), encoding="utf-8")
    os.replace(temporary, shard / SUMMARY_FILE)
    (shard / OPEN_MARKER).unlink()
    return summary


def recover_open_shards(directory: Path) -> list[ShardSummary]:
    """Closes shards a crash left open; their complete attempts count, searches cut off are simply redone."""
    if not directory.exists():
        return []
    return [
        close_shard(shard, (shard / OPEN_MARKER).read_text(encoding="utf-8").strip())
        for shard in sorted(directory.iterdir())
        if shard.is_dir() and is_open(shard)
    ]


def all_attempts(directory: Path) -> Iterator[AttemptRecord]:
    """Every attempt of every shard, closed or open, in shard order: the actors' event log."""
    if not directory.exists():
        return
    for shard in sorted(path for path in directory.iterdir() if path.is_dir()):
        yield from read_attempts(shard)


class ShardWriter:
    """Appends attempts to the open shard and rotates it after `max_attempts` attempts or `max_seconds`."""

    def __init__(self, directory: Path, max_attempts: int, max_seconds: float) -> None:
        self.directory = directory
        self.max_attempts = max_attempts
        self.max_seconds = max_seconds
        self.shard: Path | None = None
        self.opened_at = ""
        self.opened_monotonic = 0.0
        self.count = 0
        self.closed: list[ShardSummary] = []

    def write(
        self, attempt: AttemptRecord, tree: TreeRecord | None, reasoning: TreeReasoning | None = None
    ) -> AttemptRecord:
        if self.shard is not None and (
            self.count >= self.max_attempts or time.monotonic() - self.opened_monotonic >= self.max_seconds
        ):
            self.close()
        shard = self.shard if self.shard is not None else self._open()
        if tree is not None:
            attempt = dataclasses.replace(attempt, tree_file=tree_file_name(attempt.problem_name, attempt.stage))
            write_tree(shard / attempt.tree_file, tree)
        if reasoning is not None:
            reasoning_file = reasoning_file_name(attempt.problem_name, attempt.stage)
            attempt = dataclasses.replace(attempt, reasoning_file=reasoning_file)
            write_reasoning(shard / reasoning_file, reasoning)
        with (shard / ATTEMPTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(to_json(attempt) + "\n")
        self.count += 1
        return attempt

    def close(self) -> None:
        if self.shard is not None:
            self.closed.append(close_shard(self.shard, self.opened_at))
            self.shard = None

    def _open(self) -> Path:
        existing = [path for path in self.directory.iterdir() if path.is_dir()] if self.directory.exists() else []
        sequence = max((int(path.name) for path in existing), default=-1) + 1
        shard = self.directory / f"{sequence:06d}"
        (shard / "trees").mkdir(parents=True)
        self.opened_at = now()
        (shard / OPEN_MARKER).write_text(self.opened_at, encoding="utf-8")
        self.shard = shard
        self.opened_monotonic = time.monotonic()
        self.count = 0
        return shard
