"""Whether the loop's expansion budget is large enough, per phase, from the tree index (`TreeSummary`).

A budget that stops the searches short of the harder proofs shows in three ways: solves crowd into the budget's last
quarter (a search that needed 25-32 of 32 expansions would often have needed more), the proofs found get no longer,
and the curriculum's difficulty of the solved statements stops rising.
"""

import statistics
from collections.abc import Sequence

from lean_search.monitoring.families import BudgetPhase
from lean_search.rl.options_ab import arm_outcomes
from lean_search.rl.tree_store import TreeEntry

# Inclusive ranges; None: no upper end.
EXPANSION_BUCKETS = ((1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 24), (25, 32), (33, 48), (49, 64), (65, None))
PROOF_STEP_BUCKETS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, None))


def bucket_name(low: int, high: int | None) -> str:
    if high is None:
        return f"{low}+"
    return str(low) if low == high else f"{low}-{high}"


def bucket_counts(values: Sequence[int], buckets: Sequence[tuple[int, int | None]]) -> dict[str, int]:
    return {
        bucket_name(low, high): sum(low <= value and (high is None or value <= high) for value in values)
        for low, high in buckets
    }


def is_late_solve(entry: TreeEntry) -> bool:
    """The first proof came in the last quarter of the search's budget (expansions 25-32 of 32)."""
    summary = entry.summary
    assert summary.solved_at_expansion is not None
    return summary.solved_at_expansion > summary.expansion_budget - summary.expansion_budget // 4


def timed_solves(entries: Sequence[TreeEntry]) -> list[TreeEntry]:
    """Solved trees whose first proof's expansion is known."""
    return [entry for entry in entries if entry.proved and entry.summary.solved_at_expansion is not None]


def late_solve_share(entries: Sequence[TreeEntry]) -> float | None:
    solves = timed_solves(entries)
    return sum(map(is_late_solve, solves)) / len(solves) if solves else None


def mean_or_none(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def quantile(values: Sequence[float], share: float) -> float | None:
    """The nearest-rank quantile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def recent_phases(entries: Sequence[TreeEntry], phase: int, count: int) -> list[TreeEntry]:
    return [entry for entry in entries if phase - count < entry.phase <= phase]


def budget_phase_record(
    entries: Sequence[TreeEntry], phase: int, late_solve_phases: int, max_late_solve_share: float
) -> BudgetPhase:
    """`entries`: the whole index; the late-solve share is pooled over the last `late_solve_phases` phases."""
    current = [entry for entry in entries if entry.phase == phase]
    solved = [entry for entry in current if entry.proved]
    solves = timed_solves(current)
    expansions = [expansion for entry in solves if (expansion := entry.summary.solved_at_expansion) is not None]
    steps = [entry.summary.proof_steps for entry in solved if entry.summary.proof_steps is not None]
    solved_difficulty = [entry.difficulty for entry in solved if entry.difficulty is not None]
    searched_difficulty = [entry.difficulty for entry in current if entry.difficulty is not None]
    return BudgetPhase(
        trees=len(current),
        solved_trees=len(solved),
        trainable_groups=sum(entry.summary.trainable_groups for entry in current),
        expansion_budget=max((entry.summary.expansion_budget for entry in current), default=0),
        late_solves=sum(map(is_late_solve, solves)),
        late_solve_share=late_solve_share(current),
        recent_late_solve_share=late_solve_share(recent_phases(entries, phase, late_solve_phases)),
        recent_phases=min(phase, late_solve_phases),
        max_late_solve_share=max_late_solve_share,
        expansions_to_solve=bucket_counts(expansions, EXPANSION_BUCKETS),
        mean_expansions_to_solve=mean_or_none(expansions),
        proof_steps=bucket_counts(steps, PROOF_STEP_BUCKETS),
        mean_proof_steps=mean_or_none(steps),
        mean_difficulty_solved=mean_or_none(solved_difficulty),
        median_difficulty_solved=median_or_none(solved_difficulty),
        p90_difficulty_solved=quantile(solved_difficulty, 0.9),
        mean_difficulty_searched=mean_or_none(searched_difficulty),
        by_search_arm=arm_outcomes(current),
    )
