"""Held-out candidates whose root state nearly repeats a root state of the training data (SFT, reasoning, value), and
pool statements that nearly repeat a drawn one (its twins, which the curriculum must not feed either).

The training data keeps proof states, not statements, so both sides compare root states: the verified pool's root goals
against each training proof's earliest recorded state (`step_index`, the value data's `depth`; 0 where recorded). A
state is written as a theorem's binders and conclusion, the hypotheses in a fixed order, so that the near-duplicate
tokens anonymize its names as for statements and a reordering of the hypotheses changes nothing. Two states match when
their anonymized token strings are equal or their MinHash signatures agree on at least the threshold's share.
"""

import dataclasses
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy

from lean_search.corpora.decontamination import anonymized_statement_tokens
from lean_search.expert_iteration.near_duplicates import MinHasher, exhaustive_matches, matches_any
from lean_search.rl.fixed_sets import (
    CharacterCandidate,
    CharacterSelection,
    CharacterStrataConfig,
    Exclusions,
    select_by_characters,
)


def is_hypothesis(names: str) -> bool:
    return all(name.startswith("h") or name == "this" for name in names.split())


def anonymized_type(variable_binders: str, type_text: str) -> str:
    """A hypothesis's type with the variables named by their position (as the near-duplicate tokens name them), so
    that renaming the variables does not change it."""
    return " ".join(anonymized_statement_tokens(f"theorem t {variable_binders} (h : {type_text}) := by"))


def goal_statement(goals: Sequence[str]) -> str:
    """`x y : ℝ`, `h : 0 < x`, `⊢ x * y ≤ 1` as `theorem goal (x y : ℝ) (h : 0 < x) : x * y ≤ 1 := by`: the variables
    in their order, then the hypotheses (names starting with h, or `this`) ordered by their types with the variables
    anonymized, so neither reordering the hypotheses nor renaming the variables changes the order."""
    variables = []
    hypotheses = []
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
                continue
            names, _, type_text = entry.partition(" : ")
            (hypotheses if is_hypothesis(names) else variables).append((type_text.strip(), names))
    variable_binders = " ".join(f"({names} : {type_text})" for type_text, names in variables)
    ordered = sorted(hypotheses, key=lambda hypothesis: anonymized_type(variable_binders, hypothesis[0]))
    binders = " ".join(f"({names} : {type_text})" for type_text, names in [*variables, *ordered])
    return f"theorem goal {binders} : {' ∧ '.join(conclusions)} := by"


@dataclass(frozen=True)
class ProofRecord:
    proof: str
    position: int
    goals: tuple[str, ...]


def proof_records(path: Path) -> Iterator[ProofRecord]:
    """Records with goals, their proof and their position in it (SFT and reasoning: `proof_identifier`, `step_index`;
    value: `identifier`, `depth`); others (math solutions, chunks) are skipped."""
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            proof = record.get("proof_identifier", record.get("identifier"))
            position = record.get("step_index", record.get("depth"))
            if record.get("goals") and proof is not None and position is not None:
                yield ProofRecord(proof, position, tuple(record["goals"]))


@dataclass(frozen=True)
class TrainingRoots:
    # Each training proof's earliest recorded state, distinct.
    states: tuple[tuple[str, ...], ...]
    # Per directory, in the given order: its records with goals, and its proofs.
    records: tuple[int, ...]
    proofs: tuple[int, ...]


def training_roots(directories: Sequence[Path]) -> TrainingRoots:
    """Raises ValueError for a directory that does not exist or holds no record with goals."""
    earliest: dict[str, ProofRecord] = {}
    records = []
    proofs = []
    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f"No training data directory {directory}.")
        count = 0
        seen = set()
        for path in sorted(directory.rglob("*.jsonl")):
            for record in proof_records(path):
                count += 1
                seen.add(record.proof)
                known = earliest.get(record.proof)
                if known is None or record.position < known.position:
                    earliest[record.proof] = record
        if not count:
            raise ValueError(f"No training record with goals under {directory}.")
        records.append(count)
        proofs.append(len(seen))
    states = sorted({record.goals for record in earliest.values()})
    return TrainingRoots(tuple(states), tuple(records), tuple(proofs))


@dataclass(frozen=True)
class Fingerprints:
    """Per state, aligned with the states given: the anonymized token string and the MinHash signature."""

    keys: tuple[str, ...]
    signatures: numpy.ndarray

    def subset(self, indices: Sequence[int]) -> "Fingerprints":
        return Fingerprints(tuple(self.keys[index] for index in indices), self.signatures[list(indices)])


def fingerprints(states: Sequence[Sequence[str]]) -> Fingerprints:
    hasher = MinHasher()
    statements = [goal_statement(goals) for goals in states]
    keys = tuple(" ".join(anonymized_statement_tokens(statement)) for statement in statements)
    return Fingerprints(keys, numpy.stack([hasher.signature(statement) for statement in statements]))


def lsh_duplicates(queries: Fingerprints, references: Fingerprints, threshold: float) -> list[bool]:
    """Equal keys, or a reference LSH proposes reaching the threshold (fast; misses some pairs near it)."""
    keys = set(references.keys)
    near = matches_any(references.signatures, queries.signatures, threshold)
    return [key in keys or hit for key, hit in zip(queries.keys, near, strict=True)]


def exhaustive_duplicates(queries: Fingerprints, references: Fingerprints, threshold: float) -> list[bool]:
    """Equal keys, or any reference reaching the threshold, every pair compared."""
    keys = set(references.keys)
    near = exhaustive_matches(references.signatures, queries.signatures, threshold)
    return [key in keys or hit for key, hit in zip(queries.keys, near, strict=True)]


def names_where(candidates: Sequence[CharacterCandidate], hits: Sequence[bool]) -> frozenset[str]:
    return frozenset(candidate.name for candidate, hit in zip(candidates, hits, strict=True) if hit)


def select_clear_of_training(
    candidates: Sequence[CharacterCandidate],
    candidate_prints: Fingerprints,
    training_prints: Fingerprints,
    config: CharacterStrataConfig,
    exclusions: Exclusions,
) -> CharacterSelection:
    """The draw, then every drawn statement compared with every training root; hits are dropped and their bands
    drawn on (the next statements in the hash order), until no drawn statement matches."""
    position = {candidate.name: index for index, candidate in enumerate(candidates)}
    checked: set[str] = set()
    hits: set[str] = set()
    while True:
        drawn = dataclasses.replace(exclusions, drawn_near_training_duplicates=frozenset(hits))
        selection = select_by_characters(candidates, config, drawn)
        new = [position[statement.name] for statement in selection.statements if statement.name not in checked]
        if not new:
            return selection
        matched = exhaustive_duplicates(candidate_prints.subset(new), training_prints, config.near_duplicate_threshold)
        checked.update(candidates[index].name for index in new)
        hits.update(candidates[index].name for index, hit in zip(new, matched, strict=True) if hit)


def pool_twins(
    candidates: Sequence[CharacterCandidate],
    candidate_prints: Fingerprints,
    drawn: frozenset[str],
    threshold: float,
) -> list[CharacterCandidate]:
    """The candidates outside `drawn` whose root state matches a drawn one's, every pair compared."""
    drawn_indices = [index for index, candidate in enumerate(candidates) if candidate.name in drawn]
    other_indices = [index for index, candidate in enumerate(candidates) if candidate.name not in drawn]
    matched = exhaustive_duplicates(
        candidate_prints.subset(other_indices), candidate_prints.subset(drawn_indices), threshold
    )
    return [candidates[index] for index, hit in zip(other_indices, matched, strict=True) if hit]
