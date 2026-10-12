"""The curriculum over verified known-proof statements (pool v3): a difficulty band that follows the solve rate.

difficulty = proof_steps_weight * (top-level tactics of the verified known proof)
           + root_value_weight * h(root) + characters_weight * (characters of that proof) / 100,
where h(root) is the current value model's estimate, or the proof's tactic count until the root is scored. The
scheduler takes statements at random from the band [low, low + width]. Outcomes of statements fed since the band last
moved are counted; once `window` of them are in, the band moves up by `step` when at least `raise_solve_rate` were
solved and down when fewer than `lower_solve_rate`. When the band holds no statement it moves to the nearest one. It
starts at the easiest statement the automation tactics do not close (those never enter the curriculum).
"""

import bisect
import random
import statistics
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import VerifiedStatement

CHARACTERS_UNIT = 100


@dataclass(frozen=True)
class CurriculumConfig:
    # Under $LEAN_SEARCH_DATA: phase6_pool_v3.py --step verify appends to it while the loop runs.
    verified: str = "expert_iteration/pool_v3/verified.jsonl"
    # The searches start once this many usable statements are verified (the verifier keeps adding during the loop).
    minimum_statements: int = 3000
    proof_steps_weight: float = 0.5
    root_value_weight: float = 0.5
    characters_weight: float = 0.0
    band_width: float = 1.0
    band_step: float = 0.5
    window: int = 100
    raise_solve_rate: float = 0.5
    lower_solve_rate: float = 0.3
    # Roots nearest the band re-scored by each new value model (one prefill each).
    root_value_refresh: int = 4096
    reload_seconds: float = 300.0
    seed: str = "curriculum"


@dataclass(frozen=True)
class CurriculumState:
    band_low: float | None
    # Increases with every band move; outcomes of statements fed earlier do not count.
    generation: int
    outcomes: tuple[bool, ...]


@dataclass(frozen=True)
class CurriculumCounts:
    statements: int
    available: int
    band_low: float | None
    band_high: float | None
    band_available: int
    generation: int
    outcomes: int
    solve_rate: float | None
    roots_scored_by_current_model: int


@dataclass(frozen=True)
class RootToScore:
    name: str
    goals: tuple[str, ...]


class Curriculum:
    def __init__(self, config: CurriculumConfig, value_version: int) -> None:
        self.config = config
        self.value_version = value_version
        self.statements: dict[str, VerifiedStatement] = {}
        self.root_values: dict[str, tuple[float, int]] = {}
        self.available: set[str] = set()
        self.ordered: list[tuple[float, str]] = []
        self.ordered_is_current = True
        self.band_low: float | None = None
        self.generation = 0
        self.fed: dict[str, int] = {}
        self.outcomes: deque[bool] = deque(maxlen=config.window)
        self.random = random.Random(config.seed)
        # Band moves since the caller last took them, for its log.
        self.messages: list[str] = []

    def add(self, records: Iterable[VerifiedStatement], started: Collection[str]) -> list[StatementRecord]:
        """Usable records (verified, not closed by automation) join; returns their statements."""
        added = []
        for record in records:
            if not record.verified or record.automation_solved or record.name in self.statements:
                continue
            self.statements[record.name] = record
            if record.name not in started:
                self.available.add(record.name)
            added.append(record.statement)
        self.ordered_is_current = False
        return added

    def mark_started(self, names: Iterable[str]) -> None:
        for name in names:
            if name in self.available:
                self.available.discard(name)
                self.ordered_is_current = False

    def difficulty(self, name: str) -> float:
        record = self.statements[name]
        root_value = self.root_values.get(name, (float(record.proof_tactics), -1))[0]
        return (
            self.config.proof_steps_weight * record.proof_tactics
            + self.config.root_value_weight * root_value
            + self.config.characters_weight * record.proof_characters / CHARACTERS_UNIT
        )

    def band(self) -> tuple[float, float] | None:
        if self.band_low is None:
            return None
        return self.band_low, self.band_low + self.config.band_width

    def next_statement(self) -> StatementRecord | None:
        ordered = self._ordered()
        if not ordered:
            return None
        if self.band_low is None:
            self.band_low = ordered[0][0]
        start, end = self._band_range(ordered)
        if start == end:
            self._move_to_nearest(ordered, start)
            start, end = self._band_range(ordered)
        _, name = ordered.pop(self.random.randrange(start, end))
        self.available.discard(name)
        self.fed[name] = self.generation
        return self.statements[name].statement

    def record_outcome(self, name: str, solved: bool) -> None:
        """Counts the outcome of a statement fed from the current band and moves the band when the rate says so."""
        if self.fed.pop(name, None) != self.generation:
            return
        self.outcomes.append(solved)
        if len(self.outcomes) < self.config.window or self.band_low is None:
            return
        rate = statistics.fmean(self.outcomes)
        if rate >= self.config.raise_solve_rate:
            self._move(self.band_low + self.config.band_step, f"raised (solve rate {rate:.0%})")
        elif rate < self.config.lower_solve_rate:
            ordered = self._ordered()
            floor = ordered[0][0] if ordered else self.band_low
            self._move(max(floor, self.band_low - self.config.band_step), f"lowered (solve rate {rate:.0%})")

    def take_messages(self) -> list[str]:
        messages, self.messages = self.messages, []
        return messages

    def roots_to_score(self, window: int, limit: int) -> list[RootToScore]:
        """Up to `limit` of the `window` statements nearest the band whose root h is an older model's, nearest first."""
        center = (self.band_low or 0.0) + self.config.band_width / 2
        nearest = sorted(self._ordered(), key=lambda entry: abs(entry[0] - center))[:window]
        stale = [name for _, name in nearest if self.root_values.get(name, (0.0, -1))[1] != self.value_version]
        return [RootToScore(name, self.statements[name].root_goals) for name in stale[:limit]]

    def set_root_values(self, values: Mapping[str, float], version: int) -> None:
        for name, value in values.items():
            self.root_values[name] = (value, version)
        self.ordered_is_current = False

    def state(self) -> CurriculumState:
        return CurriculumState(self.band_low, self.generation, tuple(self.outcomes))

    def restore(self, state: CurriculumState) -> None:
        self.band_low = state.band_low
        self.generation = state.generation
        self.outcomes.extend(state.outcomes)

    def counts(self) -> CurriculumCounts:
        ordered = self._ordered()
        band = self.band()
        start, end = self._band_range(ordered) if band is not None else (0, 0)
        return CurriculumCounts(
            statements=len(self.statements),
            available=len(self.available),
            band_low=None if band is None else band[0],
            band_high=None if band is None else band[1],
            band_available=end - start,
            generation=self.generation,
            outcomes=len(self.outcomes),
            solve_rate=statistics.fmean(self.outcomes) if self.outcomes else None,
            roots_scored_by_current_model=sum(
                version == self.value_version for _, version in self.root_values.values()
            ),
        )

    def _ordered(self) -> list[tuple[float, str]]:
        if not self.ordered_is_current:
            self.ordered = sorted((self.difficulty(name), name) for name in self.available)
            self.ordered_is_current = True
        return self.ordered

    def _band_range(self, ordered: list[tuple[float, str]]) -> tuple[int, int]:
        assert self.band_low is not None
        start = bisect.bisect_left(ordered, (self.band_low, ""))
        end = bisect.bisect_right(ordered, (self.band_low + self.config.band_width, "\U0010ffff"))
        return start, end

    def _move_to_nearest(self, ordered: list[tuple[float, str]], position: int) -> None:
        """An empty band jumps to the nearest statement: above it if there is one, else below."""
        assert self.band_low is not None
        nearest = ordered[position][0] if position < len(ordered) else ordered[-1][0] - self.config.band_width
        self._move(nearest, "moved to the nearest statements (the band was empty)")

    def _move(self, band_low: float, reason: str) -> None:
        previous = self.band_low
        self.band_low = band_low
        self.generation += 1
        self.outcomes.clear()
        self.messages.append(f"Curriculum band {reason}: low {previous} -> {band_low:.2f}")
