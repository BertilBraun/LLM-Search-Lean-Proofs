"""Single-step reward: what a sampled block did on its state in Lean, and whether that counts as a success."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.lean import LeanError, LeanTimeout, ReplFailure
from lean_search.policy.prompts import ParseFailure
from lean_search.reasoning.states import GoalKey


class StepOutcome(StrEnum):
    TRUNCATED = "truncated"
    NO_BLOCK = "no_block"
    EMPTY = "empty"
    FORBIDDEN = "forbidden"
    ERROR = "error"
    TIMEOUT = "timeout"
    # Some top-level tactics applied, then one failed.
    PARTIAL = "partial"
    # The goals closed before the block's last tactic, which never ran.
    CLOSED_EARLY = "closed_early"
    NO_PROGRESS = "no_progress"
    PROGRESS = "progress"
    # The goals equal the reference proof's next state or a later one.
    REFERENCE = "reference"
    CLOSED = "closed"
    # Rebuilding the state or running the REPL failed: never the sample's fault.
    INFRASTRUCTURE = "infrastructure"

    @property
    def applied_any(self) -> bool:
        return self in APPLIED_ANY

    @property
    def fully_applied(self) -> bool:
        return self in FULLY_APPLIED

    @property
    def changed_goals(self) -> bool:
        return self in CHANGED_GOALS


FULLY_APPLIED = frozenset({StepOutcome.NO_PROGRESS, StepOutcome.PROGRESS, StepOutcome.REFERENCE, StepOutcome.CLOSED})
APPLIED_ANY = FULLY_APPLIED | {StepOutcome.PARTIAL, StepOutcome.CLOSED_EARLY}
CHANGED_GOALS = frozenset({StepOutcome.PROGRESS, StepOutcome.REFERENCE, StepOutcome.CLOSED, StepOutcome.CLOSED_EARLY})


@dataclass(frozen=True)
class RewardConfig:
    # Reaching a state further along the reference proof than its next state also counts.
    accept_later_reference_states: bool = True
    # The weaker success level: a fully applied block whose goals changed and whose value estimate h dropped by at
    # least the margin (needs a served value adapter while executing).
    value_progress: bool = False
    value_progress_margin: float = 1.0


@dataclass(frozen=True)
class Classification:
    outcome: StepOutcome
    # 1 for the reference next state, 2 for the state after it, ...; 0 when no reference state was reached.
    reference_steps_advanced: int


def parse_failure_outcome(failure: ParseFailure) -> StepOutcome:
    return StepOutcome(failure.value)


def classify_block(
    failure: LeanError | LeanTimeout | ReplFailure | None,
    applied_tactics: int,
    total_tactics: int,
    goals_before: GoalKey,
    goals_after: GoalKey,
    reference_goal_keys: Sequence[GoalKey],
) -> Classification:
    match failure:
        case ReplFailure():
            outcome = StepOutcome.INFRASTRUCTURE
        case LeanError() | LeanTimeout() if applied_tactics:
            outcome = StepOutcome.PARTIAL
        case LeanTimeout():
            outcome = StepOutcome.TIMEOUT
        case LeanError():
            outcome = StepOutcome.ERROR
        case None if applied_tactics < total_tactics:
            outcome = StepOutcome.CLOSED_EARLY
        case None if not goals_after:
            outcome = StepOutcome.CLOSED
        case None if goals_after == goals_before:
            outcome = StepOutcome.NO_PROGRESS
        case None if goals_after in reference_goal_keys:
            return Classification(StepOutcome.REFERENCE, reference_goal_keys.index(goals_after) + 1)
        case None:
            outcome = StepOutcome.PROGRESS
    return Classification(outcome, 0)


def is_success(
    outcome: StepOutcome, reference_steps_advanced: int, value_drop: float | None, config: RewardConfig
) -> bool:
    match outcome:
        case StepOutcome.CLOSED:
            return True
        case StepOutcome.REFERENCE if config.accept_later_reference_states or reference_steps_advanced == 1:
            return True
        case StepOutcome.REFERENCE | StepOutcome.PROGRESS:
            # A run executed without the value option has no estimates.
            return config.value_progress and value_drop is not None and value_drop >= config.value_progress_margin
        case _:
            return False
