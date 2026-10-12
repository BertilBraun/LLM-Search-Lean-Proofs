"""Applicability of retrieved lemmas on the first goal, their order and prompt lines; non-matching lemmas stay."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.lean import LeanError, LeanRepl, LeanTimeout, Outcome, ProofState, ReplFailure
from lean_search.retrieval.config import ApplicabilityConfig
from lean_search.retrieval.premises import RetrievedPremise, compact_signature


class Applicability(StrEnum):
    CLOSES = "closes"
    LEAVES_GOALS = "leaves_goals"
    NO_MATCH = "no_match"


APPLICABILITY_ORDER = {Applicability.CLOSES: 0, Applicability.LEAVES_GOALS: 1, Applicability.NO_MATCH: 2}


@dataclass(frozen=True)
class LemmaCheck:
    applicability: Applicability
    # The keyword of the tactic that applied ("exact", "apply", "rw"); empty for no match.
    tactic: str = ""
    # Goals that replace the first goal (0 when it closes).
    new_goals: int = 0


NO_MATCH = LemmaCheck(Applicability.NO_MATCH)


class TryOutcome(StrEnum):
    APPLIED = "applied"
    ERROR = "error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    REPL_FAILURE = "repl_failure"


@dataclass(frozen=True)
class TacticTry:
    tactic: str
    outcome: TryOutcome
    check: LemmaCheck
    seconds: float


@dataclass(frozen=True)
class AnnotatedLemma:
    premise: RetrievedPremise
    check: LemmaCheck
    tries: tuple[TacticTry, ...] = ()


@dataclass(frozen=True)
class Annotation:
    lemmas: tuple[AnnotatedLemma, ...]

    @property
    def lean_seconds(self) -> float:
        return sum(attempt.seconds for lemma in self.lemmas for attempt in lemma.tries)

    @property
    def tactic_calls(self) -> int:
        return sum(len(lemma.tries) for lemma in self.lemmas)


def tactic_keyword(template: str) -> str:
    return template.split(maxsplit=1)[0]


def try_outcome(outcome: Outcome) -> TryOutcome:
    match outcome:
        case ProofState():
            return TryOutcome.APPLIED
        case LeanTimeout(wall_clock=True):
            return TryOutcome.WALL_CLOCK_TIMEOUT
        case LeanTimeout():
            return TryOutcome.HEARTBEAT_TIMEOUT
        case LeanError():
            return TryOutcome.ERROR
        case ReplFailure():
            return TryOutcome.REPL_FAILURE


def tactic_check(template: str, goals_before: int, outcome: Outcome) -> LemmaCheck:
    match outcome:
        case ProofState(goals=goals):
            # Unification can also solve later goals that share metavariables with the first.
            new_goals = max(0, len(goals) - goals_before + 1)
            applicability = Applicability.CLOSES if new_goals == 0 else Applicability.LEAVES_GOALS
            return LemmaCheck(applicability, tactic_keyword(template), new_goals)
        case _:
            return NO_MATCH


def check_rank(check: LemmaCheck) -> tuple[int, int]:
    return APPLICABILITY_ORDER[check.applicability], check.new_goals


def best_check(checks: Sequence[LemmaCheck]) -> LemmaCheck:
    """Closing beats leaving goals, fewer goals beat more; ties go to the earlier tactic."""
    return min(checks, key=check_rank, default=NO_MATCH)


def order_lemmas(lemmas: Sequence[AnnotatedLemma]) -> list[AnnotatedLemma]:
    return sorted(lemmas, key=lambda lemma: (APPLICABILITY_ORDER[lemma.check.applicability], -lemma.premise.score))


def annotation_comment(check: LemmaCheck) -> str:
    match check.applicability:
        case Applicability.CLOSES:
            return f"  -- {check.tactic}: closes the goal"
        case Applicability.LEAVES_GOALS:
            plural = "" if check.new_goals == 1 else "s"
            return f"  -- {check.tactic}: leaves {check.new_goals} goal{plural}"
        case Applicability.NO_MATCH:
            return ""


def lemma_line(lemma: AnnotatedLemma, max_signature_characters: int) -> str:
    premise = lemma.premise
    signature = compact_signature(premise.signature, premise.full_name, max_signature_characters)
    return signature + annotation_comment(lemma.check)


def lemma_lines(lemmas: Sequence[AnnotatedLemma], count: int, max_signature_characters: int) -> tuple[str, ...]:
    return tuple(lemma_line(lemma, max_signature_characters) for lemma in order_lemmas(lemmas)[:count])


async def check_premise(
    repl: LeanRepl, state: ProofState, premise: RetrievedPremise, config: ApplicabilityConfig
) -> AnnotatedLemma:
    tries: list[TacticTry] = []
    for template in config.tactics:
        result = await repl.apply_tactic(
            state,
            template.format(name=premise.full_name),
            heartbeats=config.heartbeats,
            timeout_seconds=config.timeout_seconds,
        )
        check = tactic_check(template, len(state.goals), result.outcome)
        tries.append(TacticTry(tactic_keyword(template), try_outcome(result.outcome), check, result.elapsed_seconds))
        if check.applicability == Applicability.CLOSES:
            break
    return AnnotatedLemma(premise, best_check([attempt.check for attempt in tries]), tuple(tries))


async def annotate(
    repl: LeanRepl, state: ProofState, premises: Sequence[RetrievedPremise], config: ApplicabilityConfig
) -> Annotation:
    return Annotation(tuple([await check_premise(repl, state, premise, config) for premise in premises]))
