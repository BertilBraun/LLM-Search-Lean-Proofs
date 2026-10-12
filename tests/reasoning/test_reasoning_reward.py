import pytest

from lean_search.lean import LeanError, LeanTimeout, ReplFailure, ReplFailureKind
from lean_search.reasoning.reward import (
    Classification,
    RewardConfig,
    StepOutcome,
    classify_block,
    is_success,
)

BEFORE = ("a b : ℕ\n⊢ a + b = 5",)
NEXT = ("b : ℕ\n⊢ 2 + b = 5",)
LATER = ("⊢ 2 + 3 = 5",)
REFERENCES = (NEXT, LATER, ())
ERROR = LeanError("unknown identifier 'foo'")
TIMEOUT = LeanTimeout("deterministic timeout", wall_clock=False)
CRASH = ReplFailure(ReplFailureKind.REPLAY_FAILED, "replay failed")


@pytest.mark.parametrize(
    ("failure", "applied", "total", "after", "expected"),
    [
        (None, 1, 1, NEXT, Classification(StepOutcome.REFERENCE, 1)),
        (None, 2, 2, LATER, Classification(StepOutcome.REFERENCE, 2)),
        (None, 1, 1, (), Classification(StepOutcome.CLOSED, 0)),
        (None, 1, 1, ("b : ℕ\n⊢ b = 3",), Classification(StepOutcome.PROGRESS, 0)),
        (None, 1, 1, BEFORE, Classification(StepOutcome.NO_PROGRESS, 0)),
        (None, 1, 2, (), Classification(StepOutcome.CLOSED_EARLY, 0)),
        (ERROR, 0, 1, BEFORE, Classification(StepOutcome.ERROR, 0)),
        (TIMEOUT, 0, 1, BEFORE, Classification(StepOutcome.TIMEOUT, 0)),
        (ERROR, 1, 2, NEXT, Classification(StepOutcome.PARTIAL, 0)),
        (CRASH, 0, 1, BEFORE, Classification(StepOutcome.INFRASTRUCTURE, 0)),
    ],
)
def test_block_classification(
    failure: LeanError | LeanTimeout | ReplFailure | None,
    applied: int,
    total: int,
    after: tuple[str, ...],
    expected: Classification,
) -> None:
    assert classify_block(failure, applied, total, BEFORE, after, REFERENCES) == expected


def test_unchanged_goals_are_no_progress_even_when_the_reference_step_changed_nothing() -> None:
    assert classify_block(None, 1, 1, BEFORE, BEFORE, (BEFORE,)).outcome == StepOutcome.NO_PROGRESS


@pytest.mark.parametrize(
    ("outcome", "advanced", "value_drop", "config", "success"),
    [
        (StepOutcome.CLOSED, 0, None, RewardConfig(), True),
        (StepOutcome.REFERENCE, 1, None, RewardConfig(), True),
        (StepOutcome.REFERENCE, 2, None, RewardConfig(), True),
        (StepOutcome.REFERENCE, 2, None, RewardConfig(accept_later_reference_states=False), False),
        (StepOutcome.PROGRESS, 0, 3.0, RewardConfig(), False),
        (StepOutcome.PROGRESS, 0, 3.0, RewardConfig(value_progress=True, value_progress_margin=1.0), True),
        (StepOutcome.PROGRESS, 0, 0.5, RewardConfig(value_progress=True, value_progress_margin=1.0), False),
        (StepOutcome.PROGRESS, 0, None, RewardConfig(value_progress=True), False),
        (StepOutcome.CLOSED_EARLY, 0, None, RewardConfig(), False),
        (StepOutcome.PARTIAL, 0, None, RewardConfig(), False),
        (StepOutcome.TRUNCATED, 0, None, RewardConfig(), False),
    ],
)
def test_success(
    outcome: StepOutcome, advanced: int, value_drop: float | None, config: RewardConfig, success: bool
) -> None:
    assert is_success(outcome, advanced, value_drop, config) == success


def test_value_progress_rescues_a_later_reference_state_when_those_do_not_count() -> None:
    config = RewardConfig(accept_later_reference_states=False, value_progress=True, value_progress_margin=1.0)
    assert is_success(StepOutcome.REFERENCE, 2, 1.5, config)
