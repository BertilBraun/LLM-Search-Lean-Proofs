"""Which statement the searches take next, and how far each statement's search escalates.

Fresh statements come from the curriculum (a difficulty band over verified known-proof statements, curriculum.py) and,
for `open_share` of the fresh starts or once the curriculum has none, from the open pool in its order, drawn across
sources by weight. The curriculum learns the outcome of every statement it fed. A search runs stage by stage on
the same tree: after each stage, an unsolved statement continues into the next stage (a larger total budget) when the
best open state of its tree is close enough to a proof by the value model; otherwise, or after the last stage, it is
retired. The state is rebuilt from the attempt log, so the service resumes after a crash: a search cut off before it
ended starts again from scratch at the stage it had reached, waiting in a queue ahead of fresh statements, most
promising first.
"""

import heapq
import math
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import Curriculum
from lean_search.expert_iteration.loop_config import SchedulerConfig, SearchStage
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
    # The stage the search starts at: 0, or a later stage when a cut-off search starts again.
    stage: int

    @property
    def name(self) -> str:
        return problem_name(self.statement)


@dataclass(frozen=True)
class StageOutcome:
    proved: bool
    start_failed: bool
    frontier_exhausted: bool
    # The smallest value estimate h on the open frontier when the stage ended; None without one.
    best_frontier_value: float | None
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
    open_started: int
    restarts_started: int


@dataclass
class _Entry:
    statement: StatementRecord | None
    status: StatementStatus
    stage: int = 0
    priority: float = math.inf


def decide(outcome: StageOutcome, stage: int, config: SchedulerConfig) -> Decision:
    if outcome.proved:
        return Decision.SOLVED
    if outcome.start_failed:
        return Decision.RETIRED_LOAD_FAILURE
    if outcome.frontier_exhausted:
        return Decision.RETIRED_DEAD
    if stage + 1 >= len(config.stages):
        return Decision.RETIRED_LAST_STAGE
    if outcome.best_frontier_value is None:
        deep = config.promising_depth > 0 and outcome.max_depth >= config.promising_depth
        return Decision.ESCALATED if deep else Decision.RETIRED_UNPROMISING
    gate = config.stages[stage + 1].max_frontier_value
    close = gate is None or outcome.best_frontier_value <= gate
    return Decision.ESCALATED if close else Decision.RETIRED_UNPROMISING


def restart_priority(attempt: AttemptRecord) -> float:
    """Lower first: the closest open state to a proof by h; without a value model, the deepest search."""
    if attempt.best_frontier_value is not None:
        return attempt.best_frontier_value
    return -float(attempt.max_depth)


class Scheduler:
    def __init__(self, config: SchedulerConfig, curriculum: Curriculum | None = None, open_share: float = 0.0) -> None:
        self.config = config
        self.curriculum = curriculum
        self.open_share = open_share
        self.open_started = 0
        self.open_names: set[str] = set()
        self.weights = {source.name: source.weight for source in config.source_weights}
        self.entries: dict[str, _Entry] = {}
        self.fresh_by_source: dict[str, deque[str]] = {}
        self.fresh_started_by_source: Counter[str] = Counter()
        self.restarts: list[tuple[float, str]] = []
        self.fresh_started = 0
        self.restarts_started = 0

    def stage(self, index: int) -> SearchStage:
        return self.config.stages[index]

    def add_statements(self, statements: Iterable[StatementRecord], open_pool: bool = True) -> int:
        """New statements become fresh, in order for the open pool; ones seen before (or logged) are kept."""
        added = 0
        for statement in statements:
            name = problem_name(statement)
            entry = self.entries.get(name)
            if entry is not None:
                if entry.statement is None and entry.status == StatementStatus.QUEUED:
                    heapq.heappush(self.restarts, (entry.priority, name))
                entry.statement = entry.statement or statement
                continue
            self.entries[name] = _Entry(statement, StatementStatus.FRESH)
            if open_pool:
                self.open_names.add(name)
                self.fresh_by_source.setdefault(statement.source, deque()).append(name)
            added += 1
        return added

    def replay(self, attempts: Iterable[AttemptRecord]) -> int:
        """The attempt log of earlier sessions: a search whose last record escalated was cut off and starts again."""
        count = 0
        for attempt in attempts:
            entry = self.entries.setdefault(attempt.problem_name, _Entry(None, StatementStatus.FRESH))
            if attempt.stage == 0 and entry.status == StatementStatus.FRESH:
                self.fresh_started += 1
                if attempt.problem_name in self.open_names:
                    self.open_started += 1
                    self.fresh_started_by_source[attempt.source] += 1
            if self.curriculum is not None:
                self.curriculum.mark_started([attempt.problem_name])
            if attempt.decision == Decision.ESCALATED:
                entry.status = StatementStatus.QUEUED
                entry.stage = attempt.stage + 1
                entry.priority = restart_priority(attempt)
                if entry.statement is not None:
                    heapq.heappush(self.restarts, (entry.priority, attempt.problem_name))
            else:
                self._finish(entry, attempt.decision)
            count += 1
        return count

    def next_job(self) -> Job | None:
        if self._has_restart():
            _, name = heapq.heappop(self.restarts)
            self.restarts_started += 1
        else:
            fresh = self._next_fresh()
            if fresh is None:
                return None
            name = fresh
            self.fresh_started += 1
        entry = self.entries[name]
        assert entry.statement is not None, name
        entry.status = StatementStatus.IN_FLIGHT
        return Job(entry.statement, entry.stage)

    def record(self, attempt: AttemptRecord) -> None:
        """A stage of a live search ended; an escalated search goes on in place."""
        entry = self.entries[attempt.problem_name]
        if attempt.decision == Decision.ESCALATED:
            entry.stage = attempt.stage + 1
            entry.priority = restart_priority(attempt)
            return
        self._finish(entry, attempt.decision)
        if self.curriculum is not None and attempt.decision != Decision.RETIRED_LOAD_FAILURE:
            self.curriculum.record_outcome(attempt.problem_name, attempt.decision == Decision.SOLVED)

    def release(self, job: Job) -> None:
        """A search that failed for infrastructure reasons starts again at the stage it had reached."""
        entry = self.entries[job.name]
        if entry.stage == 0 and job.name in self.open_names:
            self.fresh_started -= 1
            self.open_started -= 1
            self.fresh_started_by_source[job.statement.source] -= 1
            entry.status = StatementStatus.FRESH
            self.fresh_by_source[job.statement.source].appendleft(job.name)
        else:
            entry.status = StatementStatus.QUEUED
            heapq.heappush(self.restarts, (entry.priority, job.name))

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
            open_started=self.open_started,
            restarts_started=self.restarts_started,
        )

    def _next_fresh(self) -> str | None:
        """The curriculum's next statement, or the open pool's while it is below its share or the curriculum is out."""
        open_source = self._fresh_source()
        open_turn = self.open_started < self.open_share * (self.fresh_started + 1)
        if open_source is not None and (self.curriculum is None or open_turn):
            return self._take_open(open_source)
        statement = None if self.curriculum is None else self.curriculum.next_statement()
        if statement is not None:
            name = problem_name(statement)
            self.entries.setdefault(name, _Entry(statement, StatementStatus.FRESH))
            return name
        return None if open_source is None else self._take_open(open_source)

    def _take_open(self, source: str) -> str:
        self.open_started += 1
        self.fresh_started_by_source[source] += 1
        return self.fresh_by_source[source].popleft()

    def _finish(self, entry: _Entry, decision: Decision) -> None:
        entry.status = StatementStatus.SOLVED if decision == Decision.SOLVED else StatementStatus.RETIRED

    def _has_restart(self) -> bool:
        while self.restarts:
            _, name = self.restarts[0]
            entry = self.entries[name]
            if entry.status == StatementStatus.QUEUED and entry.statement is not None:
                return True
            heapq.heappop(self.restarts)
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
