"""Held-out pool statements for the fixed targets: the probe set and the gate set (value benchmark), disjoint.

Both come from the curriculum's verified statements (pool v3: a known proof compiled here, the automation sweep alone
does not close it), stratified by the curriculum's difficulty estimate into easy, medium and hard, the same number from
each stratum, in a seeded hash order. The loop never feeds them (`StatementsConfig.held_out`).

A set stratified by characters (`CharacterStrataConfig`, the follow-up's probe v2) takes configured counts from bands of
the shortest known proof's length in characters, in a seeded hash order within each band, after dropping statements of
the existing fixed sets, those of the held-out states and near-duplicates of the training data (`Exclusions`).
"""

import bisect
import hashlib
import json
import math
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.decontamination import canonical_statement
from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem
from lean_search.expert_iteration.curriculum import Curriculum, CurriculumConfig
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.expert_iteration.pool import pool_problem, problem_name
from lean_search.search.records import from_json_object, to_json


class Stratum(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True)
class HeldOutStatement:
    statement: StatementRecord
    difficulty: float
    # A `Stratum`, or a character band such as "500-999" (`character_stratum`).
    stratum: str

    @property
    def name(self) -> str:
        return problem_name(self.statement)

    @property
    def problem(self) -> Problem:
        return pool_problem(self.statement)


@dataclass(frozen=True)
class FixedSetsConfig:
    # The verified statements and the difficulty weights; without root values the difficulty is the known proof's
    # weighted tactic count, as the curriculum's before the value model scored the root.
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)
    # Difficulty from which a statement is medium, and hard.
    medium_from: float = 2.0
    hard_from: float = 4.0
    probe_per_stratum: int = 167
    gate_per_stratum: int = 134
    seed: str = "grpo-fixed-sets"
    # Under $LEAN_SEARCH_DATA.
    probe_set: str = "grpo/fixed_sets/probe.jsonl"
    gate_set: str = "grpo/fixed_sets/gate.jsonl"
    # The overfit test's fixed statements (`select_overfit_set`), disjoint from the probe and the gate.
    overfit_per_stratum: int = 100
    overfit_set: str = "grpo/fixed_sets/overfit_300.jsonl"


@dataclass(frozen=True)
class FixedSets:
    probe: tuple[HeldOutStatement, ...]
    gate: tuple[HeldOutStatement, ...]


def stratum(difficulty: float, config: FixedSetsConfig) -> Stratum:
    if difficulty >= config.hard_from:
        return Stratum.HARD
    if difficulty >= config.medium_from:
        return Stratum.MEDIUM
    return Stratum.EASY


def stratum_order(label: str) -> tuple[float, str]:
    """Numbered labels ("500-999", "5+") by their low end, then the others ("easy", "unknown", ...) by name."""
    low = re.match(r"\d+(?:\.\d+)?", label)
    return (float(low.group()) if low else math.inf, label)


def hash_order(name: str, seed: str) -> bytes:
    return hashlib.sha256(f"{seed}\n{name}".encode()).digest()


def usable_curriculum(verified: Iterable[VerifiedStatement], config: CurriculumConfig) -> Curriculum:
    """A curriculum holding the statements it would feed (verified, not closed by the automation alone)."""
    curriculum = Curriculum(config, 0)
    curriculum.add(verified, ())
    return curriculum


def candidates(verified: Iterable[VerifiedStatement], config: FixedSetsConfig) -> list[HeldOutStatement]:
    """The statements the curriculum would feed, with its difficulty estimate."""
    curriculum = usable_curriculum(verified, config.curriculum)
    held_out = []
    for name, entry in sorted(curriculum.statements.items()):
        difficulty = curriculum.difficulty(name)
        held_out.append(HeldOutStatement(entry.statement, difficulty, stratum(difficulty, config)))
    return held_out


def select_fixed_sets(verified: Iterable[VerifiedStatement], config: FixedSetsConfig) -> FixedSets:
    """Per stratum, the probe takes the first statements of one hash order and the gate the next ones of another."""
    by_stratum: dict[Stratum, list[HeldOutStatement]] = {name: [] for name in Stratum}
    for candidate in candidates(verified, config):
        by_stratum[candidate.stratum].append(candidate)
    probe: list[HeldOutStatement] = []
    gate: list[HeldOutStatement] = []
    for members in by_stratum.values():
        ordered = sorted(members, key=lambda member: hash_order(member.name, f"{config.seed}/probe"))
        probe += ordered[: config.probe_per_stratum]
        rest = sorted(
            ordered[config.probe_per_stratum :], key=lambda member: hash_order(member.name, f"{config.seed}/gate")
        )
        gate += rest[: config.gate_per_stratum]
    return FixedSets(tuple(probe), tuple(gate))


def select_overfit_set(
    verified: Iterable[VerifiedStatement], config: FixedSetsConfig, excluded: Collection[str]
) -> tuple[HeldOutStatement, ...]:
    """Per stratum, the first statements of a third hash order outside the probe and gate sets."""
    available = [candidate for candidate in candidates(verified, config) if candidate.name not in excluded]
    chosen: list[HeldOutStatement] = []
    for name in Stratum:
        members = [candidate for candidate in available if candidate.stratum == name]
        members.sort(key=lambda member: hash_order(member.name, f"{config.seed}/overfit"))
        chosen += members[: config.overfit_per_stratum]
    return tuple(chosen)


@dataclass(frozen=True)
class CharacterStrataConfig:
    # The verified statements; each statement's recorded difficulty is this curriculum's (the follow-up's: characters
    # / 100). Only usable ones count, as in `candidates`.
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)
    # Upper ends (exclusive) of the character bands but the last, which is open: 0-499, 500-999, ..., 4500+.
    edges: tuple[int, ...] = (500, 1000, 1500, 2000, 3000, 4500)
    # Statements per band, one more entry than `edges`.
    counts: tuple[int, ...] = (150, 250, 350, 350, 400, 300, 200)
    seed: str = "grpo-probe-v2"
    # Under $LEAN_SEARCH_DATA: the set written, and the fixed sets it shares no statement with.
    output: str = "grpo/fixed_sets/probe_v2.jsonl"
    excluded_sets: tuple[str, ...] = (
        "grpo/fixed_sets/probe.jsonl",
        "grpo/fixed_sets/gate.jsonl",
        "grpo/fixed_sets/overfit_300.jsonl",
    )
    # Under $LEAN_SEARCH_RUNS: the loop's held-out states (`evaluation.held_out_states_file`), kept out by statement;
    # empty: none.
    held_out_states_file: str = "phase5_eval_visible_student_v2_visible/states.jsonl"
    # A candidate whose root state reaches this estimated Jaccard with a root state of the training data is dropped
    # (pool v3's near-duplicate threshold).
    near_duplicate_threshold: float = 0.7


def validate_character_strata(config: CharacterStrataConfig) -> None:
    edges = config.edges
    if not edges or edges[0] <= 0 or any(low >= high for low, high in zip(edges, edges[1:], strict=False)):
        raise ValueError("edges must be positive and increasing.")
    if len(config.counts) != len(edges) + 1 or any(count < 0 for count in config.counts):
        raise ValueError("counts needs one count (>= 0) per band: one more than edges.")


def character_stratum(characters: int, edges: Sequence[int]) -> str:
    index = bisect.bisect_right(edges, characters)
    low = 0 if index == 0 else edges[index - 1]
    return f"{low}+" if index == len(edges) else f"{low}-{edges[index] - 1}"


def character_strata(edges: Sequence[int]) -> list[str]:
    return [character_stratum(low, edges) for low in (0, *edges)]


@dataclass(frozen=True)
class CharacterCandidate:
    held_out: HeldOutStatement
    root_goals: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.held_out.name


def character_candidates(
    verified: Iterable[VerifiedStatement], config: CharacterStrataConfig
) -> list[CharacterCandidate]:
    curriculum = usable_curriculum(verified, config.curriculum)
    return [
        CharacterCandidate(
            HeldOutStatement(
                entry.statement, curriculum.difficulty(name), character_stratum(entry.proof_characters, config.edges)
            ),
            entry.root_goals,
        )
        for name, entry in sorted(curriculum.statements.items())
    ]


def same_statements(candidates: Iterable[CharacterCandidate], formal_statements: Iterable[str]) -> frozenset[str]:
    """The candidates whose statement is one of `formal_statements` up to whitespace and comments."""
    canonical = {canonical_statement(statement) for statement in formal_statements}
    return frozenset(
        candidate.name
        for candidate in candidates
        if canonical_statement(candidate.held_out.statement.formal_statement) in canonical
    )


@dataclass(frozen=True)
class Exclusions:
    # Candidates (by name) in an existing fixed set, with a held-out state's statement, nearly repeating training data.
    fixed_sets: frozenset[str]
    held_out_states: frozenset[str]
    near_training_duplicates: frozenset[str]


@dataclass(frozen=True)
class StratumDraw:
    stratum: str
    candidates: int
    # Dropped before the draw, each candidate under the first of these reasons that applies.
    in_fixed_sets: int
    held_out_states: int
    near_training_duplicates: int
    chosen: int


@dataclass(frozen=True)
class CharacterSelection:
    statements: tuple[HeldOutStatement, ...]
    strata: tuple[StratumDraw, ...]


def select_by_characters(
    candidates: Sequence[CharacterCandidate], config: CharacterStrataConfig, exclusions: Exclusions
) -> CharacterSelection:
    """Per band, the first `counts` statements of one hash order among the candidates no exclusion drops."""
    chosen: list[HeldOutStatement] = []
    draws = []
    for stratum, count in zip(character_strata(config.edges), config.counts, strict=True):
        members = [candidate.held_out for candidate in candidates if candidate.held_out.stratum == stratum]
        in_fixed_sets = [member for member in members if member.name in exclusions.fixed_sets]
        rest = [member for member in members if member.name not in exclusions.fixed_sets]
        held_out_states = [member for member in rest if member.name in exclusions.held_out_states]
        rest = [member for member in rest if member.name not in exclusions.held_out_states]
        near = [member for member in rest if member.name in exclusions.near_training_duplicates]
        available = [member for member in rest if member.name not in exclusions.near_training_duplicates]
        if len(available) < count:
            raise ValueError(f"Band {stratum} has {len(available)} statements left, fewer than its count {count}.")
        available.sort(key=lambda member: hash_order(member.name, config.seed))
        chosen += available[:count]
        draws.append(StratumDraw(stratum, len(members), len(in_fixed_sets), len(held_out_states), len(near), count))
    return CharacterSelection(tuple(chosen), tuple(draws))


def write_fixed_set(path: Path, statements: Sequence[HeldOutStatement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(to_json(statement) + "\n" for statement in statements), encoding="utf-8")
    temporary.replace(path)


def read_fixed_set(path: Path) -> list[HeldOutStatement]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(HeldOutStatement, json.loads(line)) for line in lines if line.strip()]
