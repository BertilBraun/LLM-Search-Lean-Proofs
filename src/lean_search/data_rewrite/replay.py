"""Step-by-step replay of a tactic plan that records every state and checks that flattened `have` proofs stay put."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.lean import LeanError, LeanRepl, LeanTimeout, ProofState, ReplFailure
from lean_search.lean.identifiers import tokenize
from lean_search.lean.plans import Proceed, TacticPlan, segment_verdict
from lean_search.lean.text import LexicalKind, TacticPiece, is_incomplete_input, join_tactics, lex


@dataclass(frozen=True)
class ReplayLimits:
    heartbeats: int
    timeout_seconds: float


class ReplayOutcome(StrEnum):
    # Every tactic applied (and, for a proof, no goals left).
    COMPLETE = "complete"
    LEAN_ERROR = "lean_error"
    TIMEOUT = "timeout"
    REPL_FAILURE = "repl_failure"
    GOALS_REMAINING = "goals_remaining"
    # The goals were closed and a later tactic failed on the closed state.
    CLOSED_EARLY = "closed_early"
    # A flattened nested proof closed its goal early, left it open past its end, or touched goals outside it.
    SEGMENT_BROKEN = "segment_broken"


@dataclass(frozen=True)
class Replay:
    # The start state and the state after each applied tactic; for a complete proof up to the first proved state.
    states: tuple[ProofState, ...]
    outcome: ReplayOutcome
    message: str = ""

    @property
    def tactics(self) -> tuple[str, ...]:
        """The applied tactics (pieces merged where one did not parse alone)."""
        return self.states[-1].tactics[len(self.states[0].tactics) :]

    @property
    def goals(self) -> tuple[tuple[str, ...], ...]:
        return tuple(state.goals for state in self.states)


def tactic_plan(tactics: Sequence[str]) -> TacticPlan:
    """Already split tactics as a plan without nested proofs."""
    return TacticPlan(join_tactics(tactics), tuple(TacticPiece(tactic, 0, 0) for tactic in tactics))


def has_nested_have_proof(tactics: Sequence[str]) -> bool:
    """A `have`/`obtain` whose own `:=` is followed by `by`: flattening refused it (binders, goal-list tactics…)."""
    for tactic in tactics:
        tokens = tokenize(lex(tactic).masked(frozenset({LexicalKind.CODE})))
        for position, token in enumerate(tokens):
            if token.text not in ("have", "obtain"):
                continue
            definition = next(
                (
                    later
                    for later in range(position + 1, len(tokens))
                    if tokens[later].depth == token.depth and tokens[later].text == ":="
                ),
                None,
            )
            if definition is not None and definition + 1 < len(tokens) and tokens[definition + 1].text == "by":
                return True
    return False


async def replay_plan(
    repl: LeanRepl, start: ProofState, plan: TacticPlan, limits: ReplayLimits, *, proof: bool
) -> Replay:
    """Applies the plan's tactics one by one; tactics after the goals are closed must succeed and are cut."""
    states = [start]
    goals_before: dict[int, int] = {}
    index = 0
    while index < len(plan.tactics):
        current = states[-1]
        goals_before[index] = len(current.goals)
        result = await repl.apply_tactic(current, plan.tactics[index].text, limits.heartbeats, limits.timeout_seconds)
        match result.outcome:
            case ProofState() as after:
                verdict = segment_verdict(plan, goals_before, index, len(after.goals))
                if verdict != Proceed(index + 1):
                    return Replay(tuple(states), ReplayOutcome.SEGMENT_BROKEN, str(verdict))
                states.append(after)
                index += 1
            case LeanError(message=message) if is_incomplete_input(message) and (merged := plan.merged(index)):
                plan = merged
            case LeanError(message=message) if current.is_proved:
                return Replay(tuple(states), ReplayOutcome.CLOSED_EARLY, message)
            case LeanError(message=message):
                return Replay(tuple(states), ReplayOutcome.LEAN_ERROR, message)
            case LeanTimeout(message=message):
                return Replay(tuple(states), ReplayOutcome.TIMEOUT, message)
            case ReplFailure(message=message):
                return Replay(tuple(states), ReplayOutcome.REPL_FAILURE, message)
    if not proof:
        return Replay(tuple(states), ReplayOutcome.COMPLETE)
    proved = next((position for position, state in enumerate(states) if state.is_proved), None)
    if proved is None:
        return Replay(tuple(states), ReplayOutcome.GOALS_REMAINING)
    return Replay(tuple(states[: proved + 1]), ReplayOutcome.COMPLETE)
