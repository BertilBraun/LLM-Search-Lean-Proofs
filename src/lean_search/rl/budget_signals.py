"""Whether the loop's expansion budget is large enough, per phase, from the tree index (`TreeSummary`).

A budget that stops the searches short of the harder proofs shows in three ways: solves crowd into the budget's last
quarter (a search that needed 25-32 of 32 expansions would often have needed more), the proofs found get no longer,
and the curriculum's difficulty of the solved statements stops rising.
"""

import statistics
from collections.abc import Callable, Sequence

import numpy

from lean_search.monitoring.families import ArmDifference, ArmOutcome, BudgetPhase
from lean_search.rl.search_options import CONTROL_ARM
from lean_search.rl.tree_store import TreeEntry

# Inclusive ranges; None: no upper end.
EXPANSION_BUCKETS = ((1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 24), (25, 32), (33, 48), (49, 64), (65, None))
PROOF_STEP_BUCKETS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 8), (9, None))
# The search options A/B's intervals for the difference between its arms.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0
CONFIDENCE = 0.95


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


def solves_per(entries: Sequence[TreeEntry], cost: Callable[[TreeEntry], float], scale: float) -> float:
    total = sum(map(cost, entries))
    return scale * sum(entry.proved for entry in entries) / total if total else 0.0


def generated_tokens(entry: TreeEntry) -> float:
    return entry.summary.generated_tokens


def wall_seconds(entry: TreeEntry) -> float:
    return entry.wall_seconds


def resampled_rates(
    entries: Sequence[TreeEntry], cost: Callable[[TreeEntry], float], scale: float, generator: numpy.random.Generator
) -> numpy.ndarray:
    solved = numpy.array([entry.proved for entry in entries], dtype=float)
    costs = numpy.array([cost(entry) for entry in entries], dtype=float)
    drawn = generator.integers(0, len(entries), size=(BOOTSTRAP_RESAMPLES, len(entries)))
    with numpy.errstate(divide="ignore", invalid="ignore"):
        return scale * solved[drawn].sum(axis=1) / costs[drawn].sum(axis=1)


def rate_difference(
    arm: Sequence[TreeEntry], control: Sequence[TreeEntry], cost: Callable[[TreeEntry], float], scale: float
) -> ArmDifference | None:
    """The arm's solves per unit of cost minus the control's, with a percentile interval from drawing each arm's trees
    with replacement; None while either arm has no cost."""
    if not sum(map(cost, arm)) or not sum(map(cost, control)):
        return None
    generator = numpy.random.default_rng(BOOTSTRAP_SEED)
    differences = resampled_rates(arm, cost, scale, generator) - resampled_rates(control, cost, scale, generator)
    low, high = numpy.nanquantile(differences, [(1 - CONFIDENCE) / 2, (1 + CONFIDENCE) / 2])
    difference = solves_per(arm, cost, scale) - solves_per(control, cost, scale)
    return ArmDifference(difference, float(low), float(high))


def arm_outcome(entries: Sequence[TreeEntry], control: Sequence[TreeEntry] | None) -> ArmOutcome:
    """`control`: the control arm's trees, for an options arm's differences."""
    groups = sum(entry.summary.trainable_groups for entry in entries)
    return ArmOutcome(
        trees=len(entries),
        solved=sum(entry.proved for entry in entries),
        trainable_groups=groups,
        generated_tokens=sum(entry.summary.generated_tokens for entry in entries),
        solved_per_thousand_tokens=solves_per(entries, generated_tokens, 1e3),
        trainable_groups_per_tree=groups / len(entries),
        feedback_trainable_groups=sum(entry.summary.feedback_trainable_groups for entry in entries),
        generated_tokens_to_first_proof=sum(entry.summary.generated_tokens_to_first_proof for entry in entries),
        wall_seconds=sum(entry.wall_seconds for entry in entries),
        lean_seconds=sum(entry.summary.lean_seconds for entry in entries),
        solved_per_tree_hour=solves_per(entries, wall_seconds, 3600.0),
        solved_per_thousand_tokens_difference=None
        if control is None
        else rate_difference(entries, control, generated_tokens, 1e3),
        solved_per_tree_hour_difference=None
        if control is None
        else rate_difference(entries, control, wall_seconds, 3600.0),
    )


def arm_outcomes(entries: Sequence[TreeEntry]) -> dict[str, ArmOutcome]:
    """Per search options A/B arm; empty with the A/B off. An options arm also carries its differences to the control
    arm, once the control arm has trees."""
    by_arm: dict[str, list[TreeEntry]] = {}
    for entry in entries:
        if entry.summary.arm:
            by_arm.setdefault(entry.summary.arm, []).append(entry)
    control = by_arm.get(CONTROL_ARM)
    return {
        arm: arm_outcome(arm_entries, None if arm == CONTROL_ARM else control)
        for arm, arm_entries in sorted(by_arm.items())
    }


def difference_text(difference: ArmDifference | None, unit: str) -> str:
    if difference is None:
        return f"no difference per {unit} yet"
    return f"{difference.difference:+.3g} per {unit} [{difference.low:+.3g}, {difference.high:+.3g}]"


def arm_outcome_text(arm: str, outcome: ArmOutcome) -> str:
    text = (
        f"{arm}: {outcome.trees} trees, {outcome.solved} solved, {outcome.trainable_groups} trainable groups "
        f"({outcome.feedback_trainable_groups} of feedback rounds), {outcome.generated_tokens / 1e6:.1f}M generated "
        f"tokens ({outcome.generated_tokens_to_first_proof / 1e6:.1f}M to the first proof), "
        f"{outcome.wall_seconds / 3600:.1f} tree-hours, {outcome.lean_seconds / 3600:.1f} Lean hours; "
        f"{outcome.solved_per_thousand_tokens:.3g} solves per 1k tokens, {outcome.solved_per_tree_hour:.3g} per "
        "tree-hour"
    )
    if arm == CONTROL_ARM:
        return text
    tokens = difference_text(outcome.solved_per_thousand_tokens_difference, "1k tokens")
    hours = difference_text(outcome.solved_per_tree_hour_difference, "tree-hour")
    return f"{text}; minus control (95% bootstrap over trees): {tokens}, {hours}"


def arm_outcomes_text(outcomes: dict[str, ArmOutcome]) -> str:
    return "; ".join(arm_outcome_text(arm, outcome) for arm, outcome in outcomes.items())


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
