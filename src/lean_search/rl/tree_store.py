"""The loop's finished search trees: one gzipped TreeRecord per search under trees/phase_<k>/, and an index.

A tree belongs to the phase that was collecting when its search finished; a phase trains on its own directory. The
index (trees/index.jsonl, one `TreeEntry` per tree) is what a restart reads back: per-phase counts, the statements
already searched, the curriculum outcomes and each tree's `TreeSummary` (trainable groups, budget and health signals).
Tree files are written to a temporary name and renamed, so a crash never leaves a truncated tree for the trainer.
"""

import gzip
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.rl.tree_summary import TreeSummary
from lean_search.search.records import TreeRecord, from_json_object, read_tree, to_json

INDEX_FILE = "index.jsonl"


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

    def phase_directory(self, phase: int) -> Path:
        return self.directory / phase_directory_name(phase)

    def add(
        self,
        record: TreeRecord,
        phase: int,
        policy_version: int,
        difficulty: float | None,
        summary: TreeSummary,
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
        )
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(to_json(entry) + "\n")
        self.entries.append(entry)
        return entry

    def phase_entries(self, phase: int) -> list[TreeEntry]:
        return [entry for entry in self.entries if entry.phase == phase]

    def records(self, phase: int) -> list[TreeRecord]:
        return [read_tree(self.directory / entry.file) for entry in self.phase_entries(phase)]
