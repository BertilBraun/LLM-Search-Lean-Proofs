"""Which statement the searches take next, at which pass, and what happens to it after an attempt.

Fresh statements come from the pool in its order, drawn across sources by weight. After an attempt, an unsolved
statement is requeued for the next pass (a larger budget, each pass once) only when an open state of its search is
close to a proof by the value model; otherwise, or after the last pass, it is retired. Requeued statements are
retried most promising first, up to a share of the attempts while fresh statements remain. The state is rebuilt from
the attempt log, so the service resumes after a crash: searches that were in flight simply start again.
"""

import heapq
import math
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.loop_config import PassBudget, SchedulerConfig
from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.shards import AttemptRecord, Decision


class StatementStatus(StrEnum):
    FRESH = "fresh"
    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    SOLVED = "solved"
    RETIRED = "retired"


@dataclass(frozen=True)
class Job:
    statement: StatementRecord
    pass_index: int
    budget: PassBudget

    @property
    def name(self) -> str:
        return problem_name(self.statement)


@dataclass(frozen=True)
class AttemptOutcome:
    proved: bool
    start_failed: bool
    # The smallest value estimate h on the open frontier when the search stopped; None without one.
    best_frontier_value: float | None
    root_dead: bool
    max_depth: int


@dataclass(frozen=True)
class SchedulerCounts:
    known: int
    fresh: int
    queued: int
    in_flight: int
    solved: int
    retired: int
    fresh_started: int
    retries_started: int


@dataclass
class _Entry:
    statement: StatementRecord | None
    status: StatementStatus
    next_pass: int = 0
    priority: float = math.inf


def decide(outcome: AttemptOutcome, pass_index: int, config: SchedulerConfig) -> Decision:
    if outcome.proved:
        return Decision.SOLVED
    if outcome.start_failed:
        return Decision.RETIRED_LOAD_FAILURE
    if pass_index + 1 >= len(config.budgets):
        return Decision.RETIRED_LAST_PASS
    if outcome.root_dead:
        return Decision.RETIRED_DEAD
    close = outcome.best_frontier_value is not None and outcome.best_frontier_value <= config.promising_value
    deep = config.promising_depth > 0 and outcome.max_depth >= config.promising_depth
    return Decision.REQUEUED if close or deep else Decision.RETIRED_UNPROMISING


def retry_priority(attempt: AttemptRecord) -> float:
    """Lower first: the closest open state to a proof by h; without a value model, the deepest search."""
    if attempt.best_frontier_value is not None:
        return attempt.best_frontier_value
    return -float(attempt.max_depth)


class Scheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self.config = config
        self.weights = {source.name: source.weight for source in config.source_weights}
        self.entries: dict[str, _Entry] = {}
        self.fresh_by_source: dict[str, deque[str]] = {}
        self.fresh_started_by_source: Counter[str] = Counter()
        self.retries: list[tuple[float, str]] = []
        self.fresh_started = 0
        self.retries_started = 0

    def add_statements(self, statements: Iterable[StatementRecord]) -> int:
        """New statements become fresh; ones seen before (also in the attempt log) are skipped."""
        added = 0
        for statement in statements:
            name = problem_name(statement)
            entry = self.entries.get(name)
            if entry is not None:
                if entry.statement is None and entry.status == StatementStatus.QUEUED:
                    heapq.heappush(self.retries, (entry.priority, name))
                entry.statement = entry.statement or statement
                continue
            self.entries[name] = _Entry(statement, StatementStatus.FRESH)
            self.fresh_by_source.setdefault(statement.source, deque()).append(name)
            added += 1
        return added

    def replay(self, attempts: Iterable[AttemptRecord]) -> int:
        count = 0
        for attempt in attempts:
            entry = self.entries.setdefault(attempt.problem_name, _Entry(None, StatementStatus.FRESH))
            self._count_start(attempt.source, attempt.pass_index)
            self._apply(attempt.problem_name, entry, attempt)
            count += 1
        return count

    def next_job(self) -> Job | None:
        fresh_source = self._fresh_source()
        take_retry = self._has_retry() and (
            fresh_source is None
            or self.retries_started < self.config.retry_share * (self.fresh_started + self.retries_started + 1)
        )
        if take_retry:
            _, name = heapq.heappop(self.retries)
        elif fresh_source is not None:
            name = self.fresh_by_source[fresh_source].popleft()
        else:
            return None
        entry = self.entries[name]
        assert entry.statement is not None, name
        entry.status = StatementStatus.IN_FLIGHT
        self._count_start(entry.statement.source, entry.next_pass)
        return Job(entry.statement, entry.next_pass, self.config.budgets[entry.next_pass])

    def record(self, attempt: AttemptRecord) -> None:
        self._apply(attempt.problem_name, self.entries[attempt.problem_name], attempt)

    def release(self, job: Job) -> None:
        """A search that failed for infrastructure reasons: the statement waits for the same pass again."""
        entry = self.entries[job.name]
        if job.pass_index == 0:
            self.fresh_started -= 1
            self.fresh_started_by_source[job.statement.source] -= 1
            entry.status = StatementStatus.FRESH
            self.fresh_by_source[job.statement.source].appendleft(job.name)
        else:
            self.retries_started -= 1
            entry.status = StatementStatus.QUEUED
            heapq.heappush(self.retries, (entry.priority, job.name))

    def counts(self) -> SchedulerCounts:
        statuses = Counter(entry.status for entry in self.entries.values())
        return SchedulerCounts(
            known=len(self.entries),
            fresh=statuses[StatementStatus.FRESH],
            queued=statuses[StatementStatus.QUEUED],
            in_flight=statuses[StatementStatus.IN_FLIGHT],
            solved=statuses[StatementStatus.SOLVED],
            retired=statuses[StatementStatus.RETIRED],
            fresh_started=self.fresh_started,
            retries_started=self.retries_started,
        )

    def _apply(self, name: str, entry: _Entry, attempt: AttemptRecord) -> None:
        match attempt.decision:
            case Decision.SOLVED:
                entry.status = StatementStatus.SOLVED
            case Decision.REQUEUED:
                entry.status = StatementStatus.QUEUED
                entry.next_pass = attempt.pass_index + 1
                entry.priority = retry_priority(attempt)
                heapq.heappush(self.retries, (entry.priority, name))
            case _:
                entry.status = StatementStatus.RETIRED

    def _count_start(self, source: str, pass_index: int) -> None:
        if pass_index == 0:
            self.fresh_started += 1
            self.fresh_started_by_source[source] += 1
        else:
            self.retries_started += 1

    def _has_retry(self) -> bool:
        while self.retries:
            _, name = self.retries[0]
            entry = self.entries[name]
            if entry.status == StatementStatus.QUEUED and entry.statement is not None:
                return True
            heapq.heappop(self.retries)
        return False

    def _fresh_source(self) -> str | None:
        """The source furthest below its weighted share of the fresh attempts started so far."""
        active = [source for source in sorted(self.fresh_by_source) if self._has_fresh(source)]
        weights = {source: self.weights.get(source, 1.0) for source in active}
        active = [source for source in active if weights[source] > 0]
        if not active:
            return None
        total_weight = sum(weights[source] for source in active)
        started = sum(self.fresh_started_by_source[source] for source in active)

        def deficit(source: str) -> float:
            return weights[source] / total_weight * (started + 1) - self.fresh_started_by_source[source]

        return max(active, key=deficit)

    def _has_fresh(self, source: str) -> bool:
        queue = self.fresh_by_source[source]
        while queue and self.entries[queue[0]].status != StatementStatus.FRESH:
            queue.popleft()
        return bool(queue)
