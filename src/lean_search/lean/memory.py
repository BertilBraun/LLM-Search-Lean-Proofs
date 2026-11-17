"""One search's memory of the tactics it ran: deterministic outcomes of identical Lean input are not run again."""

from typing import NamedTuple

from lean_search.lean.repl import LeanError, LeanTimeout, Outcome, ProofState, Remembered, ReplFailure


class TacticInput(NamedTuple):
    """Everything Lean's result depends on: the state's whole tactic path from the statement (so its environment,
    metavariables and fresh-name counters, which equal goals do not pin down) and the step with its limit."""

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


class SearchMemory:
    """Owned by one search and never shared: its keys are tactic paths of that search's statement."""

    def __init__(self, cache_results: bool) -> None:
        self.cache_results = cache_results
        self._outcomes: dict[TacticInput, Remembered] = {}

    def recall(self, state: ProofState, tactic: str, heartbeats: int) -> Remembered | None:
        if not self.cache_results:
            return None
        return self._outcomes.get(tactic_input(state, tactic, heartbeats))

    def record(self, state: ProofState, tactic: str, heartbeats: int, outcome: Outcome, seconds: float) -> None:
        if self.cache_results and is_deterministic(outcome):
            self._outcomes[tactic_input(state, tactic, heartbeats)] = Remembered(outcome, seconds)
