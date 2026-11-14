"""The loop's finished search trees: one gzipped TreeRecord per search under trees/phase_<k>/, and an index.

A tree belongs to the phase that was collecting when its search finished (its entry also names the one when it
started); a phase trains on its own directory. The
index (trees/index.jsonl, one `TreeEntry` per tree) is what a restart reads back: per-phase counts, the statements
already searched, the curriculum outcomes and each tree's `TreeSummary` (trainable groups, budget and health signals).
Tree files are written to a temporary name and renamed, so a crash never leaves a truncated tree for the trainer.

Searches that end without a tree in the store are recorded in trees/searches_without_tree.jsonl with their generated
tokens (`SearchWithoutTree`): those that finished count towards a phase's generated tokens like the kept trees (the
budget is what a run sampled), those lost to a server failure or a stop are logged only (a failed statement is fed
again). Both files are append-only, so the counts a restart recomputes from them are the ones before it.
"""

import gzip
import json
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.rl.tree_summary import TreeSummary
from lean_search.search.records import TreeRecord, from_json_object, read_tree, to_json

INDEX_FILE = "index.jsonl"
WITHOUT_TREE_FILE = "searches_without_tree.jsonl"


@dataclass(frozen=True)
class TreeEntry:
    sequence: int
    problem_name: str
    phase: int
    # Relative to the trees directory.
    file: str
    proved: bool
    proofs: int
    expansions: int
    # The published version when the search finished; each expansion's texts record the version that sampled them.
    policy_version: int
    difficulty: float | None
    wall_seconds: float
    finished_time: float
    summary: TreeSummary = field(default_factory=TreeSummary)
    # The phase collecting when the search started (0: not recorded, read as `phase`), and the seconds of it the
    # searches were paused.
    started_phase: int = 0
    paused_seconds: float = 0.0
    # The curriculum fed a verified statement; None: no curriculum.
    verified: bool | None = None

    @property
    def start_phase(self) -> int:
        return self.started_phase or self.phase

    @property
    def active_seconds(self) -> float:
        return max(0.0, self.wall_seconds - self.paused_seconds)


class SearchEnd(StrEnum):
    # Finished, its summary failed (`GrpoLoop.keep_tree`): left out of the store and of training.
    SUMMARY_FAILED = "summary_failed"
    # Finished without a tree: its proof of the renamed statement failed against the original (`search_problem`).
    NO_TREE = "no_tree"
    # Lost: a policy or value server failed the search, or a stop or crash cut it off.
    SERVER_FAILURE = "server_failure"
    STOPPED = "stopped"

    @property
    def counted(self) -> bool:
        """Towards the phase's generated tokens: a finished search's, as a kept tree's."""
        return self in (SearchEnd.SUMMARY_FAILED, SearchEnd.NO_TREE)


@dataclass(frozen=True)
class SearchWithoutTree:
    problem_name: str
    # The phase collecting when the search ended.
    phase: int
    # A finished search's accounting; a lost one's tokens so far.
    generated_tokens: int
    end: SearchEnd
    finished_time: float


def phase_directory_name(phase: int) -> str:
    return f"phase_{phase:04d}"


class TreeStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index = directory / INDEX_FILE
        self.entries: list[TreeEntry] = []
        if self.index.exists():
            with self.index.open(encoding="utf-8") as lines:
                self.entries = [from_json_object(TreeEntry, json.loads(line)) for line in lines if line.strip()]
        self.without_tree_file = directory / WITHOUT_TREE_FILE
        self.without_tree: list[SearchWithoutTree] = []
        if self.without_tree_file.exists():
            with self.without_tree_file.open(encoding="utf-8") as lines:
                self.without_tree = [
                    from_json_object(SearchWithoutTree, json.loads(line)) for line in lines if line.strip()
                ]

    def phase_directory(self, phase: int) -> Path:
        return self.directory / phase_directory_name(phase)

    def add(
        self,
        record: TreeRecord,
        phase: int,
        policy_version: int,
        difficulty: float | None,
        summary: TreeSummary,
        started_phase: int = 0,
        paused_seconds: float = 0.0,
        verified: bool | None = None,
    ) -> TreeEntry:
        sequence = len(self.entries)
        relative = f"{phase_directory_name(phase)}/{sequence:07d}_{record.problem_name}.json.gz"
        path = self.directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as file:
            file.write(to_json(record))
        os.replace(temporary, path)
        entry = TreeEntry(
            sequence=sequence,
            problem_name=record.problem_name,
            phase=phase,
            file=relative,
            proved=record.result.proved,
            proofs=record.result.accounting.proofs,
            expansions=record.result.accounting.expansions,
            policy_version=policy_version,
            difficulty=difficulty,
            wall_seconds=record.result.accounting.wall_seconds,
            finished_time=time.time(),
            summary=summary,
            started_phase=started_phase,
            paused_seconds=paused_seconds,
            verified=verified,
        )
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(to_json(entry) + "\n")
        self.entries.append(entry)
        return entry

    def add_without_tree(self, problem_name: str, phase: int, generated_tokens: int, end: SearchEnd) -> None:
        record = SearchWithoutTree(problem_name, phase, generated_tokens, end, time.time())
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.without_tree_file.open("a", encoding="utf-8") as handle:
            handle.write(to_json(record) + "\n")
        self.without_tree.append(record)

    def phase_entries(self, phase: int) -> list[TreeEntry]:
        return [entry for entry in self.entries if entry.phase == phase]

    def generated_tokens(self, first_phase: int, last_phase: int) -> int:
        """Of the searches that finished in these phases: the kept trees' and those left out
        (`SearchEnd.counted`)."""
        kept = sum(entry.summary.generated_tokens for entry in self.entries if first_phase <= entry.phase <= last_phase)
        left_out = sum(
            search.generated_tokens
            for search in self.without_tree
            if search.end.counted and first_phase <= search.phase <= last_phase
        )
        return kept + left_out

    def lost_tokens(self, first_phase: int, last_phase: int) -> int:
        """Of the searches a server failure or a stop cut off in these phases: generated, never counted."""
        return sum(
            search.generated_tokens
            for search in self.without_tree
            if not search.end.counted and first_phase <= search.phase <= last_phase
        )

    def server_failure_tokens(self, first_phase: int, last_phase: int) -> int:
        """Of `lost_tokens`, those of searches a server failure cut off (not a stop or restart of the loop)."""
        return sum(
            search.generated_tokens
            for search in self.without_tree
            if search.end == SearchEnd.SERVER_FAILURE and first_phase <= search.phase <= last_phase
        )

    def records(self, phase: int) -> list[TreeRecord]:
        return [read_tree(self.directory / entry.file) for entry in self.phase_entries(phase)]
