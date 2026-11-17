"""One search's memory of the tactics it ran: deterministic outcomes of identical Lean input are not run again, and
tactic texts that kept hanging are not run at all."""

import collections
from typing import NamedTuple

from lean_search.lean.repl import LeanError, LeanTimeout, Outcome, ProofState, Remembered, ReplFailure


class TacticInput(NamedTuple):
    """Everything Lean's result depends on: the state's whole tactic path from the statement (so its environment,
    metavariables and fresh-name counters, which equal goals do not pin down) and the step with its limit. The
    wall-clock limit is left out: only outcomes that do not depend on it are stored."""

    header: str
    statement: str
    tactics: tuple[str, ...]
    tactic_heartbeats: tuple[int, ...]
    tactic: str
    heartbeats: int


def tactic_input(state: ProofState, tactic: str, heartbeats: int) -> TacticInput:
    return TacticInput(state.header, state.statement, state.tactics, state.tactic_heartbeats, tactic, heartbeats)


def is_deterministic(outcome: Outcome) -> bool:
    """Whether running the same input again gives the same outcome. A wall-clock stop depends on the machine's load
    (re-run alone, most such steps end in an error or at the heartbeat limit), and a REPL failure on the process."""
    match outcome:
        case ProofState() | LeanError() | LeanTimeout(wall_clock=False):
            return True
        case LeanTimeout() | ReplFailure():
            return False


def skipped_timeout(wall_clock_timeouts: int) -> LeanTimeout:
    message = f"Not run: the tactic reached the wall-clock limit {wall_clock_timeouts} times earlier in this search."
    return LeanTimeout(message, wall_clock=True, skipped=True)


class SearchMemory:
    """Owned by one search and never shared: its keys are tactic paths of that search's statement.
    `max_wall_clock_timeouts`: a tactic text stopped by the wall clock that often in the search, at any states, is not
    run again (None: always run)."""

    def __init__(self, cache_results: bool, max_wall_clock_timeouts: int | None = None) -> None:
        assert max_wall_clock_timeouts is None or max_wall_clock_timeouts >= 1
        self.cache_results = cache_results
        self.max_wall_clock_timeouts = max_wall_clock_timeouts
        self._outcomes: dict[TacticInput, Remembered] = {}
        # By tactic text and heartbeat limit: the sweep's stops at its own limit do not skip the policy's text.
        self._wall_clock_timeouts: collections.Counter[tuple[str, int]] = collections.Counter()

    def recall(self, state: ProofState, tactic: str, heartbeats: int) -> Remembered | None:
        if not self.cache_results:
            return None
        return self._outcomes.get(tactic_input(state, tactic, heartbeats))

    def record(self, state: ProofState, tactic: str, heartbeats: int, outcome: Outcome, seconds: float) -> None:
        if self.cache_results and is_deterministic(outcome):
            self._outcomes[tactic_input(state, tactic, heartbeats)] = Remembered(outcome, seconds)
        match outcome:
            case LeanTimeout(wall_clock=True, skipped=False):
                self._wall_clock_timeouts[tactic, heartbeats] += 1

    def skipped(self, tactic: str, heartbeats: int) -> LeanTimeout | None:
        timeouts = self._wall_clock_timeouts[tactic, heartbeats]
        if self.max_wall_clock_timeouts is None or timeouts < self.max_wall_clock_timeouts:
            return None
        return skipped_timeout(timeouts)
