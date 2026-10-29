"""Where the loop's statements come from: the curriculum over verified pool statements, or a fixed list (overfit test)."""

import json
import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import Curriculum, CurriculumConfig, CurriculumState
from lean_search.expert_iteration.known_proofs import read_index, read_verified
from lean_search.expert_iteration.pool import pool_problem, problem_name
from lean_search.expert_iteration.pool_search import PRELOADED_HEADER_SHARE, common_headers
from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.monitoring.families import BandOutcome, CurriculumPhase
from lean_search.rl.fixed_sets import HeldOutStatement
from lean_search.rl.tree_store import TreeEntry
from lean_search.search.records import from_json_object

# Difficulty bands of the curriculum family: [0, 1), [1, 2), ..., and everything from the last one on.
DIFFICULTY_BAND_COUNT = 6


@dataclass(frozen=True)
class FedStatement:
    statement: StatementRecord
    difficulty: float | None

    @property
    def name(self) -> str:
        return problem_name(self.statement)


class StatementSource(Protocol):
    def next_statement(self) -> FedStatement | None:
        """The next statement to search, or None when none is available right now."""
        ...

    def record_outcome(self, name: str, solved: bool) -> None: ...

    def abandon(self, name: str) -> None:
        """A search that ended without an outcome (a server failed, the loop stopped)."""
        ...

    def refresh(self) -> list[str]:
        """Reads what changed on disk (e.g. newly verified statements); returns log messages."""
        ...

    def phase_record(self, entries: Sequence[TreeEntry]) -> CurriculumPhase:
        """The curriculum family's line for a phase whose finished trees are `entries`."""
        ...

    def headers(self) -> list[str]:
        """Headers common enough to import into every REPL up front."""
        ...


def difficulty_band(difficulty: float | None) -> str:
    if difficulty is None:
        return "unknown"
    low = max(0, min(DIFFICULTY_BAND_COUNT - 1, math.floor(difficulty)))
    return f"{low}+" if low == DIFFICULTY_BAND_COUNT - 1 else f"{low}-{low + 1}"


def outcomes_by_band(entries: Sequence[TreeEntry]) -> dict[str, BandOutcome]:
    counts: dict[str, list[int]] = {}
    for entry in entries:
        attempts_and_solved = counts.setdefault(difficulty_band(entry.difficulty), [0, 0])
        attempts_and_solved[0] += 1
        attempts_and_solved[1] += entry.proved
    return {band: BandOutcome(attempts, solved) for band, (attempts, solved) in sorted(counts.items())}


class CurriculumStatements:
    """Each verified statement once per loop, from the band the solve rate moves; held-out sets never."""

    def __init__(
        self,
        config: CurriculumConfig,
        data_root: Path,
        state_path: Path,
        held_out: Collection[str],
        searched: Collection[str],
    ) -> None:
        self.config = config
        self.data_root = data_root
        self.state_path = state_path
        self.curriculum = Curriculum(config, 0)
        self.verified_offset = 0
        self.unavailable = set(held_out) | set(searched)
        self.read_verified()
        if config.unverified:
            self.curriculum.add_unverified(read_index(data_root / config.unverified), self.unavailable)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.curriculum.restore(from_json_object(CurriculumState, state))

    def read_verified(self) -> int:
        records, self.verified_offset = read_verified(self.data_root / self.config.verified, self.verified_offset)
        return len(self.curriculum.add(records, self.unavailable))

    def next_statement(self) -> FedStatement | None:
        statement = self.curriculum.next_statement()
        if statement is None:
            return None
        name = problem_name(statement)
        self.unavailable.add(name)
        return FedStatement(statement, self.curriculum.difficulty(name))

    def record_outcome(self, name: str, solved: bool) -> None:
        self.curriculum.record_outcome(name, solved)
        write_json_atomically(self.state_path, self.curriculum.state())

    def abandon(self, name: str) -> None:
        # The curriculum feeds each statement once per loop; a rare server failure costs that statement.
        pass

    def refresh(self) -> list[str]:
        added = self.read_verified()
        messages = self.curriculum.take_messages()
        return [*messages, f"{added:,} newly verified statements joined the curriculum"] if added else messages

    def phase_record(self, entries: Sequence[TreeEntry]) -> CurriculumPhase:
        counts = self.curriculum.counts()
        return CurriculumPhase(
            band_low=counts.band_low or 0.0,
            band_high=counts.band_high or 0.0,
            pool_statements=counts.statements,
            verified_statements=counts.verified_statements,
            by_difficulty=outcomes_by_band(entries),
        )

    def headers(self) -> list[str]:
        statements = [entry.statement for entry in self.curriculum.statements.values()]
        return common_headers([pool_problem(statement) for statement in statements], PRELOADED_HEADER_SHARE)


class FixedStatements:
    """A fixed list in a cycle: a statement comes again as soon as its previous search finished."""

    def __init__(self, statements: Sequence[HeldOutStatement]) -> None:
        self.statements = list(statements)
        self.position = 0
        self.running: set[str] = set()

    def next_statement(self) -> FedStatement | None:
        for offset in range(len(self.statements)):
            candidate = self.statements[(self.position + offset) % len(self.statements)]
            if candidate.name not in self.running:
                self.position = (self.position + offset + 1) % len(self.statements)
                self.running.add(candidate.name)
                return FedStatement(candidate.statement, candidate.difficulty)
        return None

    def record_outcome(self, name: str, solved: bool) -> None:
        self.running.discard(name)

    def abandon(self, name: str) -> None:
        self.running.discard(name)

    def refresh(self) -> list[str]:
        return []

    def phase_record(self, entries: Sequence[TreeEntry]) -> CurriculumPhase:
        count = len(self.statements)
        return CurriculumPhase(0.0, 0.0, count, count, by_difficulty=outcomes_by_band(entries))

    def headers(self) -> list[str]:
        return common_headers([statement.problem for statement in self.statements], PRELOADED_HEADER_SHARE)
