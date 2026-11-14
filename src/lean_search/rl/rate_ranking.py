"""Step 2's choice of a signal's learning rate (DESIGN.md, "Follow-up study: controlled arms", "Step 2", "Ranking the
rates"): the 512 held-out states decide, paired per state; among rates tied there (the 95% interval of their paired
success difference includes 0) the better point estimate on the old gate set wins, the lower rate only if that ties
too; when the gate set shows the opposite sign to the held-out states with its interval excluding 0, both rates are
flagged for a probe run. Every variant is reported against v0 on both sets.

Held-out success is the ranking measure (a sample's block ran and closed the goals or reached a state of the reference
proof, `single_step.sample_success`); valid Lean is reported beside it. The gate set is optional: it needs searches
(probe_evaluate.py runs of followup/gate_evaluation.toml), without it the lowest tied rate is chosen.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from lean_search.rl.arm_comparison import Arm, Difference, check_comparable, common_problems, compare_arms, pooled
from lean_search.rl.probe_rating import DifferenceInterval, difference_interval
from lean_search.rl.single_step import SampleSuccess


@dataclass(frozen=True)
class HeldOutStates:
    """One checkpoint's held-out run: per state, its samples' outcomes."""

    label: str
    states: Mapping[str, SampleSuccess]


def success_rate(outcome: SampleSuccess) -> float:
    return outcome.successes / outcome.samples


def valid_rate(outcome: SampleSuccess) -> float:
    return outcome.valid / outcome.samples


def paired_states(
    candidate: HeldOutStates, reference: HeldOutStates, rate: Callable[[SampleSuccess], float], seed: int = 0
) -> DifferenceInterval:
    """The candidate's rate minus the reference's on each state both sampled, bootstrapped over states."""
    names = sorted(
        name
        for name, outcome in candidate.states.items()
        if outcome.samples and name in reference.states and reference.states[name].samples
    )
    return difference_interval([rate(candidate.states[name]) - rate(reference.states[name]) for name in names], seed)


def includes_zero(interval: DifferenceInterval | Difference) -> bool:
    return interval.lower <= 0 <= interval.upper


@dataclass(frozen=True)
class Variant:
    label: str
    learning_rate: float
    held_out: HeldOutStates
    # Its gate-set probe runs; None without them.
    gate: Arm | None = None


@dataclass(frozen=True)
class VariantReport:
    label: str
    learning_rate: float
    valid: DifferenceInterval
    success: DifferenceInterval
    gate: Difference | None


def against_v0(
    variants: Sequence[Variant], v0_held_out: HeldOutStates, v0_gate: Arm | None, seed: int = 0
) -> tuple[VariantReport, ...]:
    return tuple(
        VariantReport(
            variant.label,
            variant.learning_rate,
            paired_states(variant.held_out, v0_held_out, valid_rate, seed),
            paired_states(variant.held_out, v0_held_out, success_rate, seed),
            None if variant.gate is None or v0_gate is None else compare_arms(variant.gate, v0_gate, seed).overall,
        )
        for variant in variants
    )


@dataclass(frozen=True)
class RateChoice:
    chosen: str
    # The variants tied with the best on the held-out states, the best among them.
    tied: tuple[str, ...]
    reason: str
    # Pairs (chosen, other) whose gate-set difference has the opposite sign with its interval excluding 0.
    probe_runs: tuple[tuple[str, str], ...]


def choose_rate(variants: Sequence[Variant], seed: int = 0) -> RateChoice:
    """`variants`: one signal's (or C's window's) learning rates."""
    reference = variants[0].held_out

    def held_out_success(variant: Variant) -> float:
        return paired_states(variant.held_out, reference, success_rate, seed).difference

    best = max(variants, key=held_out_success)
    tied = [
        variant
        for variant in variants
        if variant is best or includes_zero(paired_states(variant.held_out, best.held_out, success_rate, seed))
    ]
    if len(tied) == 1:
        chosen, reason = best, "the held-out states decide"
    elif all(variant.gate is not None for variant in tied):
        gate_arms = [variant.gate for variant in tied if variant.gate is not None]
        check_comparable(gate_arms, across_search_modes=False)
        problems = common_problems(gate_arms)
        shares = {variant.label: float(pooled(variant.gate, problems).mean()) for variant in tied}
        top = max(shares.values())
        leaders = [variant for variant in tied if shares[variant.label] == top]
        chosen = min(leaders, key=lambda variant: variant.learning_rate)
        reason = (
            "tied on the held-out states; the gate set's better estimate"
            if len(leaders) == 1
            else "tied on the held-out states and the gate set; the lower rate"
        )
    else:
        chosen = min(tied, key=lambda variant: variant.learning_rate)
        reason = "tied on the held-out states, no gate runs; the lower rate"
    probe_runs = []
    for other in variants:
        if other is chosen or other.gate is None or chosen.gate is None:
            continue
        held_out = paired_states(chosen.held_out, other.held_out, success_rate, seed).difference
        gate = compare_arms(chosen.gate, other.gate, seed).overall
        if not includes_zero(gate) and gate.difference * held_out < 0:
            probe_runs.append((chosen.label, other.label))
    return RateChoice(chosen.label, tuple(variant.label for variant in tied), reason, tuple(probe_runs))
