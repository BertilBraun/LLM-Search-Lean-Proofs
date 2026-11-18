"""What Lean's load did to a probe run's searches, from its results: the per-tactic wall-clock timeouts (the 60 s
backstop restarts the REPL, and after one an automation tactic is dropped for the rest of that search, so load changes
outcomes, not only time), the REPL failures and the Lean seconds per policy attempt, in total and per stratum. Two runs
compared with unlike figures ran under unlike load (reviews AO and AP of 2026-11-15)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lean_search.record_fields import written_when_set
from lean_search.rl.fixed_sets import stratum_order
from lean_search.search import SearchResult
from lean_search.search.search import POLICY_STEP_KEY

TOTAL = "all"


@dataclass(frozen=True)
class LeanLoad:
    stratum: str
    statements: int
    # Per-tactic wall-clock timeouts over every step (`step_statistics`), and the statements with at least one.
    wall_clock_timeouts: int
    statements_with_wall_clock_timeouts: int
    repl_failures: int
    policy_attempts: int
    policy_lean_seconds: float
    # None without a policy attempt.
    lean_seconds_per_policy_attempt: float | None
    # Tactics not run after their text's wall-clock stops (search.timeout_skip): not stops, so not in the counts above.
    skipped_timeouts: int = written_when_set(0)


def wall_clock_timeouts(result: SearchResult) -> int:
    return sum(statistics.wall_clock_timeouts for statistics in result.step_statistics)


def lean_load(stratum: str, results: Sequence[SearchResult]) -> LeanLoad:
    policy = [
        statistics for result in results for statistics in result.step_statistics if statistics.step == POLICY_STEP_KEY
    ]
    attempts = sum(statistics.attempts for statistics in policy)
    seconds = sum(statistics.lean_seconds for statistics in policy)
    return LeanLoad(
        stratum=stratum,
        statements=len(results),
        wall_clock_timeouts=sum(wall_clock_timeouts(result) for result in results),
        statements_with_wall_clock_timeouts=sum(wall_clock_timeouts(result) > 0 for result in results),
        repl_failures=sum(result.accounting.repl_failures for result in results),
        policy_attempts=attempts,
        policy_lean_seconds=seconds,
        lean_seconds_per_policy_attempt=seconds / attempts if attempts else None,
        skipped_timeouts=sum(result.accounting.skipped_timeouts for result in results),
    )


def lean_loads(results: Sequence[SearchResult], strata: Mapping[str, str]) -> tuple[LeanLoad, ...]:
    """The run's total (stratum "all") first, then each stratum of `strata` (a statement's stratum by name)."""
    by_stratum: dict[str, list[SearchResult]] = {}
    for result in results:
        by_stratum.setdefault(strata[result.problem_name], []).append(result)
    ordered = sorted(by_stratum, key=stratum_order)
    return (lean_load(TOTAL, results), *(lean_load(stratum, by_stratum[stratum]) for stratum in ordered))


def load_cell(load: LeanLoad) -> str:
    """Timeouts (statements with one) / REPL failures / Lean s per policy attempt; tactics the timeout skip did not run
    follow the timeouts as "+ N skipped" when there are any."""
    seconds = load.lean_seconds_per_policy_attempt
    timeouts = f"{load.wall_clock_timeouts} ({load.statements_with_wall_clock_timeouts})"
    if load.skipped_timeouts:
        timeouts += f" + {load.skipped_timeouts} skipped"
    return f"{timeouts} / {load.repl_failures} / {'-' if seconds is None else f'{seconds:.2f}'}"


LOAD_HEADER = "tactic wall-clock timeouts (statements) / REPL failures / Lean s per policy attempt"
