"""Step 2's choice of a signal's learning rate (DESIGN.md, "Follow-up study: controlled arms", "Step 2", "Ranking the
rates"): the 512 held-out states decide, paired per state; rates tied there (the 95% interval of their paired success
difference to the best includes 0) go to the old gate set, paired per statement, where the best estimate wins unless
another tied rate's interval to it includes 0 too, and then the lower rate; when a held-out difference whose interval
excludes 0 meets a gate-set difference of the opposite sign whose interval excludes 0, both rates are flagged for a
probe run. Every variant is reported against v0 on both sets.

Held-out success is the ranking measure (a sample's block ran and closed the goals or reached a state of the reference
proof, `single_step.sample_success`); valid Lean is reported beside it. Every held-out run must cover the same states.
The gate set is optional: it needs searches (probe_evaluate.py runs of followup/gate_evaluation.toml); without it the
lowest held-out-tied rate is chosen.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from lean_search.rl.arm_comparison import Arm, Difference, check_comparable, common_problems, compare_arms, pooled
from lean_search.rl.probe_evaluation import ProbeCheckpoint
from lean_search.rl.probe_rating import DifferenceInterval, difference_interval
from lean_search.rl.single_step import SampleSuccess


@dataclass(frozen=True)
class HeldOutRunStart:
    """experiments/held_out_evaluate.py's checkpoint.json: a resumed run must sample what it began with."""

    checkpoint: ProbeCheckpoint
    states_file: str
    states_sha256: str
    concurrency: int


@dataclass(frozen=True)
class HeldOutStates:
    """One checkpoint's held-out run: per state, its samples' outcomes."""

    label: str
    states: Mapping[str, SampleSuccess]


def success_rate(outcome: SampleSuccess) -> float:
    return outcome.successes / outcome.samples


def valid_rate(outcome: SampleSuccess) -> float:
    return outcome.valid / outcome.samples


def check_same_states(runs: Sequence[HeldOutStates]) -> None:
    """ValueError unless every run sampled the same states as the first (v0's)."""
    expected = set(runs[0].states)
    for run in runs[1:]:
        missing, extra = expected - set(run.states), set(run.states) - expected
        if missing or extra:
            raise ValueError(
                f"{run.label} covers other held-out states than {runs[0].label}: {len(missing)} missing, "
                f"{len(extra)} extra."
            )


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
    check_same_states([v0_held_out, *(variant.held_out for variant in variants)])
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
class GateTie:
    label: str
    # Its gate-set solves minus the gate leader's, paired per statement.
    difference: Difference


@dataclass(frozen=True)
class RateChoice:
    chosen: str
    # The variants tied with the best on the held-out states, the best among them.
    tied: tuple[str, ...]
    reason: str
    # The held-out-tied variants against the best of them on the gate set; empty without a gate-set decision.
    gate: tuple[GateTie, ...]
    # Pairs (chosen, other) where the gate set and the held-out states disagree, each with an interval excluding 0.
    probe_runs: tuple[tuple[str, str], ...]


def tie_break(tied: Sequence[Variant]) -> Variant:
    """DESIGN's rule for variants nothing separates (decided 2026-11-14, open to the owner): the lower rate; among
    equal rates the first listed, which is how step 2 prefers C's window 1 (learning_rate_step.STEP_VARIANTS)."""
    return min(tied, key=lambda variant: variant.learning_rate)


def choose_rate(variants: Sequence[Variant], seed: int = 0) -> RateChoice:
    """`variants`: one signal's (or C's window's) learning rates."""
    check_same_states([variant.held_out for variant in variants])
    reference = variants[0].held_out

    def held_out_success(variant: Variant) -> float:
        return paired_states(variant.held_out, reference, success_rate, seed).difference

    best = max(variants, key=held_out_success)
    tied = [
        variant
        for variant in variants
        if variant is best or includes_zero(paired_states(variant.held_out, best.held_out, success_rate, seed))
    ]
    gate: tuple[GateTie, ...] = ()
    if len(tied) == 1:
        chosen, reason = best, "the held-out states decide"
    elif all(variant.gate is not None for variant in tied):
        gate_arms = [variant.gate for variant in tied if variant.gate is not None]
        check_comparable(gate_arms, across_search_modes=False)
        problems = common_problems(gate_arms)
        leader = max(tied, key=lambda variant: float(pooled(variant.gate, problems).mean()))
        against_leader = {
            variant.label: compare_arms(variant.gate, leader.gate, seed).overall
            for variant in tied
            if variant is not leader
        }
        gate = tuple(GateTie(label, found) for label, found in against_leader.items())
        gate_tied = [variant for variant in tied if variant is leader or includes_zero(against_leader[variant.label])]
        chosen = tie_break(gate_tied)
        reason = (
            "tied on the held-out states; the gate set decides"
            if len(gate_tied) == 1
            else "tied on the held-out states and on the gate set; the lower rate"
        )
    else:
        chosen = tie_break(tied)
        reason = "tied on the held-out states, no gate runs; the lower rate"
    probe_runs = []
    for other in variants:
        if other is chosen or other.gate is None or chosen.gate is None:
            continue
        held_out = paired_states(chosen.held_out, other.held_out, success_rate, seed)
        gate_difference = compare_arms(chosen.gate, other.gate, seed).overall
        if (
            not includes_zero(held_out)
            and not includes_zero(gate_difference)
            and gate_difference.difference * held_out.difference < 0
        ):
            probe_runs.append((chosen.label, other.label))
    return RateChoice(chosen.label, tuple(variant.label for variant in tied), reason, gate, tuple(probe_runs))
