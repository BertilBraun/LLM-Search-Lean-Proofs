"""The curriculum over known-proof statements (pool v3): a difficulty band that follows the solve rate.

difficulty = proof_steps_weight * (top-level tactics of the shortest known proof)
           + root_value_weight * h(root) + characters_weight * (characters of that proof) / 100,
where h(root) is the current value model's estimate, or the proof's tactic count until the root is scored (roots are
known, and scored, for verified statements). Statements whose known proof compiled here are verified; the others
(most of the pool: verification is slow) are fed as well and certified or taken out when the verifier reaches them,
and every outcome is counted by kind so their solve rates can be compared. The scheduler takes statements at random
from the band [low, low + width]. The first `window` statements fed since the band last moved are its cohort; once
`judged_share` of them finished, the ones still running counted unsolved (solved searches finish much sooner than
unsolved ones, so the first outcomes to arrive alone would overstate the solve rate), the band moves up by `step`
when at least `raise_solve_rate` were solved (by `fast_band_step` at `fast_raise_solve_rate`) and down when fewer than
`lower_solve_rate`. A cohort statement that ends
without an outcome (abandoned) leaves room for the next one fed. When the band holds no statement it moves to the
nearest one. Statements the automation tactics alone close never enter.
"""

import bisect
import math
import random
import statistics
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import IndexedStatement, VerifiedStatement
from lean_search.expert_iteration.pool import problem_name

CHARACTERS_UNIT = 100


@dataclass(frozen=True)
class CurriculumConfig:
    # Under $LEAN_SEARCH_DATA: phase6_pool_v3.py --step verify appends to it while the loop runs.
    verified: str = "expert_iteration/pool_v3/verified.jsonl"
    # Known-proof statements not verified yet (phase6_pool_v3.py --step index), fed as well (86-98% verify); a
    # verification later certifies them or takes them out. Empty feeds verified statements only.
    unverified: str = "expert_iteration/pool_v3/index.jsonl"
    # The searches start once this many usable statements are verified (the verifier keeps adding during the loop).
    minimum_statements: int = 3000
    proof_steps_weight: float = 0.5
    root_value_weight: float = 0.5
    characters_weight: float = 0.0
    band_width: float = 1.0
    band_step: float = 0.5
    window: int = 50
    # The cohort's slowest searches can outlast a phase and its pause; below 1 the last ones count as unsolved.
    judged_share: float = 1.0
    raise_solve_rate: float = 0.5
    # Far above the target the band moves in bigger steps, so compute goes to statements near the 50% frontier.
    fast_raise_solve_rate: float = 0.8
    fast_band_step: float = 1.5
    lower_solve_rate: float = 0.3
    # Roots nearest the band re-scored by each new value model (one prefill each).
    root_value_refresh: int = 4096
    reload_seconds: float = 300.0
    seed: str = "curriculum"


@dataclass(frozen=True)
class CurriculumStatement:
    statement: StatementRecord
    proof_tactics: int
    proof_characters: int
    # Known for verified statements only.
    root_goals: tuple[str, ...]
    verified: bool

    @property
    def name(self) -> str:
        return problem_name(self.statement)


@dataclass(frozen=True)
class CurriculumState:
    band_low: float | None
    # Increases with every band move; outcomes of statements fed earlier do not count.
    generation: int
    # The finished cohort's outcomes; empty while any cohort statement still ran, so a restart starts a new cohort.
    outcomes: tuple[bool, ...]


@dataclass(frozen=True)
class KindOutcomes:
    fed: int
    finished: int
    solved: int

    @property
    def solve_rate(self) -> float | None:
        return self.solved / self.finished if self.finished else None


@dataclass(frozen=True)
class CurriculumCounts:
    statements: int
    verified_statements: int
    available: int
    band_low: float | None
    band_high: float | None
    band_available: int
    generation: int
    outcomes: int
    solve_rate: float | None
    roots_scored_by_current_model: int
    # Statements fed this session, by whether they were verified when fed.
    verified_outcomes: KindOutcomes
    unverified_outcomes: KindOutcomes


@dataclass(frozen=True)
class RootToScore:
    name: str
    goals: tuple[str, ...]


class Curriculum:
    def __init__(self, config: CurriculumConfig, value_version: int) -> None:
        self.config = config
        self.value_version = value_version
        self.statements: dict[str, CurriculumStatement] = {}
        self.root_values: dict[str, tuple[float, int]] = {}
        self.available: set[str] = set()
        # The available statements by difficulty, kept sorted as statements come, go and get scored.
        self.ordered: list[tuple[float, str]] = []
        self.band_low: float | None = None
        self.generation = 0
        self.fed_verified: dict[str, bool] = {}
        self.kind_counts = {True: [0, 0, 0], False: [0, 0, 0]}
        # The band's cohort: statements still running, and the outcomes of those that finished.
        self.cohort_running: set[str] = set()
        self.outcomes: list[bool] = []
        self.random = random.Random(config.seed)
        # Band moves since the caller last took them, for its log.
        self.messages: list[str] = []

    def add(self, records: Iterable[VerifiedStatement], started: Collection[str]) -> list[StatementRecord]:
        """Verification results: usable ones join or are certified, others leave; returns newly added statements."""
        added = []
        for record in records:
            known = self.statements.get(record.name)
            if not record.verified or record.automation_solved:
                if known is not None and not known.verified:
                    self._make_unavailable(record.name)
                continue
            if known is not None and known.verified:
                continue
            self._make_unavailable(record.name)
            self.statements[record.name] = CurriculumStatement(
                record.statement, record.proof_tactics, record.proof_characters, record.root_goals, True
            )
            if record.name not in started:
                self._make_available(record.name)
            if known is None:
                added.append(record.statement)
        return added

    def add_unverified(self, entries: Iterable[IndexedStatement], started: Collection[str]) -> list[StatementRecord]:
        """Known-proof statements not verified yet; ones already present (verified or not) are kept as they are."""
        added = []
        fresh = []
        for entry in entries:
            name = problem_name(entry.statement)
            if name in self.statements:
                continue
            self.statements[name] = CurriculumStatement(
                entry.statement, entry.proof_tactics, entry.proof_characters, (), False
            )
            if name not in started:
                self.available.add(name)
                fresh.append((self.difficulty(name), name))
            added.append(entry.statement)
        self.ordered = sorted([*self.ordered, *fresh])
        return added

    def mark_started(self, names: Iterable[str]) -> None:
        for name in names:
            self._make_unavailable(name)

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

    def is_verified(self, name: str) -> bool:
        return self.statements[name].verified

    def next_statement(self) -> StatementRecord | None:
        ordered = self.ordered
        if not ordered:
            return None
        if self.band_low is None:
            self.band_low = ordered[0][0]
        start, end = self._band_range()
        if start == end:
            self._move_to_nearest(start)
            start, end = self._band_range()
        _, name = ordered.pop(self.random.randrange(start, end))
        self.available.discard(name)
        if len(self.cohort_running) + len(self.outcomes) < self.config.window:
            self.cohort_running.add(name)
        verified = self.statements[name].verified
        self.fed_verified[name] = verified
        self.kind_counts[verified][0] += 1
        return self.statements[name].statement

    def record_outcome(self, name: str, solved: bool) -> None:
        """Counts the outcome of a cohort statement and moves the band once the whole cohort finished."""
        verified = self.fed_verified.pop(name, None)
        if verified is not None:
            self.kind_counts[verified][1] += 1
            self.kind_counts[verified][2] += solved
        if name not in self.cohort_running:
            return
        self.cohort_running.discard(name)
        self.outcomes.append(solved)
        if len(self.outcomes) < math.ceil(self.config.judged_share * self.config.window) or self.band_low is None:
            return
        rate = sum(self.outcomes) / self.config.window
        if rate >= self.config.fast_raise_solve_rate:
            self._move(self.band_low + self.config.fast_band_step, f"raised fast (solve rate {rate:.0%})")
        elif rate >= self.config.raise_solve_rate:
            self._move(self.band_low + self.config.band_step, f"raised (solve rate {rate:.0%})")
        elif rate < self.config.lower_solve_rate:
            floor = self.ordered[0][0] if self.ordered else self.band_low
            self._move(max(floor, self.band_low - self.config.band_step), f"lowered (solve rate {rate:.0%})")
        else:
            self._start_cohort()

    def abandon(self, name: str) -> None:
        """A statement that ended without an outcome; a cohort statement's place goes to the next one fed."""
        self.fed_verified.pop(name, None)
        self.cohort_running.discard(name)

    def take_messages(self) -> list[str]:
        messages, self.messages = self.messages, []
        return messages

    def roots_to_score(self, window: int, limit: int) -> list[RootToScore]:
        """Up to `limit` verified statements of the `window` around the band whose root h is an older model's."""
        center = (self.band_low or 0.0) + self.config.band_width / 2
        position = bisect.bisect_left(self.ordered, (center, ""))
        nearby = self.ordered[max(0, position - window // 2) : position + window // 2]
        stale = [
            name
            for _, name in nearby
            if self.statements[name].verified and self.root_values.get(name, (0.0, -1))[1] != self.value_version
        ]
        return [RootToScore(name, self.statements[name].root_goals) for name in stale[:limit]]

    def set_root_values(self, values: Mapping[str, float], version: int) -> None:
        for name, value in values.items():
            available = name in self.available
            if available:
                self._make_unavailable(name)
            self.root_values[name] = (value, version)
            if available:
                self._make_available(name)

    def state(self) -> CurriculumState:
        # Searches still running are lost in a restart; keeping their finished cohort mates would bias it to the fast.
        outcomes = () if self.cohort_running else tuple(self.outcomes)
        return CurriculumState(self.band_low, self.generation, outcomes)

    def restore(self, state: CurriculumState) -> None:
        self.band_low = state.band_low
        self.generation = state.generation
        self.outcomes = list(state.outcomes)

    def counts(self) -> CurriculumCounts:
        band = self.band()
        start, end = self._band_range() if band is not None else (0, 0)
        return CurriculumCounts(
            statements=len(self.statements),
            verified_statements=sum(statement.verified for statement in self.statements.values()),
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
            verified_outcomes=KindOutcomes(*self.kind_counts[True]),
            unverified_outcomes=KindOutcomes(*self.kind_counts[False]),
        )

    def _make_available(self, name: str) -> None:
        self.available.add(name)
        bisect.insort(self.ordered, (self.difficulty(name), name))

    def _make_unavailable(self, name: str) -> None:
        if name not in self.available:
            return
        self.available.discard(name)
        entry = (self.difficulty(name), name)
        position = bisect.bisect_left(self.ordered, entry)
        if position < len(self.ordered) and self.ordered[position] == entry:
            del self.ordered[position]

    def _band_range(self) -> tuple[int, int]:
        assert self.band_low is not None
        start = bisect.bisect_left(self.ordered, (self.band_low, ""))
        end = bisect.bisect_right(self.ordered, (self.band_low + self.config.band_width, "\U0010ffff"))
        return start, end

    def _move_to_nearest(self, position: int) -> None:
        """An empty band jumps to the nearest statement: above it if there is one, else below."""
        assert self.band_low is not None
        ordered = self.ordered
        nearest = ordered[position][0] if position < len(ordered) else ordered[-1][0] - self.config.band_width
        self._move(nearest, "moved to the nearest statements (the band was empty)")

    def _move(self, band_low: float, reason: str) -> None:
        previous = self.band_low
        self.band_low = band_low
        self.generation += 1
        self._start_cohort()
        self.messages.append(f"Curriculum band {reason}: low {previous} -> {band_low:.2f}")

    def _start_cohort(self) -> None:
        self.cohort_running.clear()
        self.outcomes.clear()
