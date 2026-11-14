"""Held-out candidates whose root state nearly repeats a root state of the training data (SFT, reasoning, value).

The training data keeps proof states, not statements, so both sides compare root states: the verified pool's root goals
against the goals of each training proof's first step (`step_index` 0; the value data's `depth` 0). A state is written
as a theorem's binders and conclusion, so that the near-duplicate tokens anonymize its names as for statements.
"""

import json
from collections.abc import Collection, Iterator, Sequence
from pathlib import Path

import numpy

from lean_search.expert_iteration.near_duplicates import MinHasher, matches_any
from lean_search.rl.fixed_sets import CharacterCandidate


def goal_statement(goals: Sequence[str]) -> str:
    """`x y : ℝ`, `h : 0 < x`, `⊢ x * y ≤ 1` as `theorem goal (x y : ℝ) (h : 0 < x) : x * y ≤ 1 := by`."""
    binders = []
    conclusions = []
    for goal in goals:
        entries: list[str] = []
        for line in goal.splitlines():
            if line[:1].isspace() and entries:
                entries[-1] += " " + line.strip()
            elif not line.startswith("case "):
                entries.append(line)
        for entry in entries:
            if entry.startswith("⊢"):
                conclusions.append(entry.removeprefix("⊢").strip())
            else:
                names, _, type_text = entry.partition(" : ")
                binders.append(f"({names} : {type_text.strip()})")
    return f"theorem goal {' '.join(binders)} : {' ∧ '.join(conclusions)} := by"


def root_states(path: Path) -> Iterator[tuple[str, ...]]:
    """The goals of the records at a proof's root; records without goals (e.g. math solutions) are skipped."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("goals") and record.get("step_index", record.get("depth")) == 0:
                yield tuple(record["goals"])


def training_root_states(directories: Sequence[Path]) -> set[tuple[str, ...]]:
    """Every root state of the JSONL files under the directories."""
    return {
        goals for directory in directories for path in sorted(directory.rglob("*.jsonl")) for goals in root_states(path)
    }


def near_training_duplicates(
    candidates: Sequence[CharacterCandidate], training_roots: Collection[tuple[str, ...]], threshold: float
) -> frozenset[str]:
    hasher = MinHasher()
    references = numpy.stack([hasher.signature(goal_statement(goals)) for goals in training_roots])
    queries = numpy.stack([hasher.signature(goal_statement(candidate.root_goals)) for candidate in candidates])
    hits = matches_any(references, queries, threshold)
    return frozenset(candidate.name for candidate, hit in zip(candidates, hits, strict=True) if hit)
