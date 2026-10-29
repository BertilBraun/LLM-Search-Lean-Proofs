"""Held-out pool statements for the fixed targets: the probe set and the gate set (value benchmark), disjoint.

Both come from the curriculum's verified statements (pool v3: a known proof compiled here, the automation sweep alone
does not close it), stratified by the curriculum's difficulty estimate into easy, medium and hard, the same number from
each stratum, in a seeded hash order. The loop never feeds them (`StatementsConfig.held_out`).
"""

import hashlib
import json
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

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
    stratum: Stratum

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


def hash_order(name: str, seed: str) -> bytes:
    return hashlib.sha256(f"{seed}\n{name}".encode()).digest()


def candidates(verified: Iterable[VerifiedStatement], config: FixedSetsConfig) -> list[HeldOutStatement]:
    """The statements the curriculum would feed, with its difficulty estimate."""
    curriculum = Curriculum(config.curriculum, 0)
    curriculum.add(verified, ())
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


def write_fixed_set(path: Path, statements: Sequence[HeldOutStatement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(to_json(statement) + "\n" for statement in statements), encoding="utf-8")
    temporary.replace(path)


def read_fixed_set(path: Path) -> list[HeldOutStatement]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(HeldOutStatement, json.loads(line)) for line in lines if line.strip()]
