"""The GRPO loop's host memory budget (rl/README.md, "Host memory"), checked whenever the loop logs the host memory.

Every condition must stay within 0.85 of the memory limit. The persistent trainer's terms are one shared copy of the
parked bases (whatever the number of ranks) and the merges handed off in host memory, which stay until written to disk
while the searches already run again.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

BUDGET_SHARE = 0.85


class BudgetStage(StrEnum):
    SAMPLING = "sampling"
    TRAINING = "training"
    PUBLISHING = "publishing"
    EVALUATING = "evaluating"


@dataclass(frozen=True)
class HostMemoryTerms:
    """In GiB; what the loop measures, and the terms it cannot (0 until taken from the system family)."""

    total: float
    repl_p90: float
    vllm: float
    parked: float = 0.0
    handoff: float = 0.0
    # A training rank's rise while training, and the CPU merge's while publishing.
    rank: float = 0.0
    merge: float = 0.0


@dataclass(frozen=True)
class BudgetCondition:
    stage: BudgetStage
    used: float
    limit: float

    @property
    def fits(self) -> bool:
        return self.used <= self.limit


def budget_conditions(
    terms: HostMemoryTerms, loop_concurrency: int, evaluation_concurrency: int, training_ranks: int
) -> tuple[BudgetCondition, ...]:
    """With the paused searches' REPLs stopped before training and evaluating (the defaults)."""
    limit = BUDGET_SHARE * terms.total
    trainer = terms.parked + terms.handoff
    searches = loop_concurrency * terms.repl_p90
    used = {
        BudgetStage.SAMPLING: searches + terms.vllm + trainer,
        BudgetStage.TRAINING: terms.vllm + training_ranks * terms.rank + trainer,
        BudgetStage.PUBLISHING: searches + terms.vllm + terms.merge + trainer,
        BudgetStage.EVALUATING: evaluation_concurrency * terms.repl_p90 + terms.vllm + terms.parked,
    }
    return tuple(BudgetCondition(stage, used[stage], limit) for stage in BudgetStage)


def budget_text(conditions: Sequence[BudgetCondition]) -> str:
    parts = [
        f"{condition.stage} {condition.used:.0f}/{condition.limit:.0f}" + ("" if condition.fits else " OVER")
        for condition in conditions
    ]
    return "budget (GiB) " + ", ".join(parts)
