"""Whether to keep a published expert-iteration round (rl/README.md, "Expert iteration", "Decision"): its held-out
states against version 0's and, paired per state, its reference's; its whole probe set paired per problem with the
reference runs; and its probe trees' diversity and explanations against the reference runs' trees."""

import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.rl.health_checks import HeldOutRates
from lean_search.rl.loop_config import HealthConfig
from lean_search.rl.probe_rating import DifferenceInterval, PairedComparison, difference_interval
from lean_search.rl.single_step import root_samples
from lean_search.rl.tree_summary import SearchHabits, binned_median
from lean_search.search.records import read_tree

# The whole set's paired difference has a 95% half-width of about 3 points, so the rule keeps a round only when it
# observed about +1 point or more: a demand for evidence, not a non-inferiority test.
MIN_PAIRED_DIFFERENCE_LOWER = -0.02
# The lower 95% bound of the per-state paired difference of held-out valid-Lean rates.
MIN_HELD_OUT_PAIRED_LOWER = -0.02


@dataclass(frozen=True)
class StateValidity:
    """One held-out state's policy samples and those of them whose block ran completely in Lean."""

    name: str
    samples: int
    valid: int


@dataclass(frozen=True)
class HeldOutRun:
    rates: HeldOutRates
    states: tuple[StateValidity, ...]


def state_validities(trees: Sequence[Path]) -> tuple[StateValidity, ...]:
    """Per held-out run tree (one per state, named after it) its root's samples, as `sample_success` counts them;
    unreadable trees skipped."""
    validities = []
    for path in trees:
        try:
            record = read_tree(path)
        except (OSError, EOFError, ValueError, zlib.error):
            continue
        samples = root_samples(record, frozenset())
        validities.append(
            StateValidity(
                path.name.removesuffix(".json.gz"),
                sum(sample.sample_count for sample in samples),
                sum(sample.sample_count for sample in samples if sample.valid),
            )
        )
    return tuple(validities)


def paired_valid_difference(reference: HeldOutRun, candidate: HeldOutRun, seed: int = 0) -> DifferenceInterval:
    """The candidate's valid-Lean rate minus the reference's per state both runs sampled, bootstrapped over states: a
    state's samples are correlated through its difficulty, which the pairing removes."""
    reference_rates = {state.name: state.valid / state.samples for state in reference.states if state.samples}
    return difference_interval(
        [
            state.valid / state.samples - reference_rates[state.name]
            for state in candidate.states
            if state.samples and state.name in reference_rates
        ],
        seed,
    )


@dataclass(frozen=True)
class RoundEvidence:
    version_zero: HeldOutRun
    reference_held_out: HeldOutRun
    candidate_held_out: HeldOutRun
    paired: PairedComparison
    reference_habits: SearchHabits
    candidate_habits: SearchHabits


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def median_explanation(habits: SearchHabits) -> float:
    return binned_median(habits.habits.explanation_character_bins) or 0.0


def held_out_checks(
    version_zero: HeldOutRun, reference: HeldOutRun, candidate: HeldOutRun, health: HealthConfig
) -> tuple[Check, ...]:
    zero = version_zero.rates
    rates = candidate.rates
    paired = paired_valid_difference(reference, candidate)
    return (
        Check(
            "held-out valid Lean against version 0",
            rates.valid_rate >= health.min_held_out_valid_fraction * zero.valid_rate,
            f"{rates.valid_rate:.1%} >= {health.min_held_out_valid_fraction} x {zero.valid_rate:.1%}",
        ),
        Check(
            "held-out success against version 0",
            rates.success >= health.min_held_out_success_fraction * zero.success,
            f"{rates.success:.1%} >= {health.min_held_out_success_fraction} x {zero.success:.1%}",
        ),
        Check(
            "held-out valid Lean against the reference, paired per state",
            paired.lower > MIN_HELD_OUT_PAIRED_LOWER,
            f"{100 * paired.difference:+.1f} [{100 * paired.lower:+.1f}, {100 * paired.upper:+.1f}] points on "
            f"{paired.problems} states, lower bound > {100 * MIN_HELD_OUT_PAIRED_LOWER:+.0f}",
        ),
    )


def probe_checks(
    paired: PairedComparison, reference_habits: SearchHabits, candidate_habits: SearchHabits, health: HealthConfig
) -> tuple[Check, ...]:
    """The diversity checks fail without readable reference trees: nothing would bound the candidate."""
    overall = paired.overall
    measured = reference_habits.policy_expansions > 0
    distinct_floor = health.min_distinct_samples_fraction * reference_habits.distinct_blocks_per_expansion
    explanation_floor = health.min_explanation_characters_fraction * median_explanation(reference_habits)
    unmeasured = "no readable reference trees"
    return (
        Check(
            "probe paired solve difference",
            overall.difference >= 0 and overall.lower > MIN_PAIRED_DIFFERENCE_LOWER,
            f"{100 * overall.difference:+.1f} points >= 0, lower bound {100 * overall.lower:+.1f} > "
            f"{100 * MIN_PAIRED_DIFFERENCE_LOWER:+.0f}",
        ),
        Check(
            "distinct blocks per expansion",
            measured and candidate_habits.distinct_blocks_per_expansion >= distinct_floor,
            f"{candidate_habits.distinct_blocks_per_expansion:.2f} >= {distinct_floor:.2f}" if measured else unmeasured,
        ),
        Check(
            "median explanation characters",
            measured and median_explanation(candidate_habits) >= explanation_floor,
            f"{median_explanation(candidate_habits):.0f} >= {explanation_floor:.0f}" if measured else unmeasured,
        ),
    )


def round_checks(evidence: RoundEvidence, health: HealthConfig) -> tuple[Check, ...]:
    """Every check must pass to keep the round; the health checks' fractions, applied before the loop restarts."""
    return held_out_checks(
        evidence.version_zero, evidence.reference_held_out, evidence.candidate_held_out, health
    ) + probe_checks(evidence.paired, evidence.reference_habits, evidence.candidate_habits, health)


def against_verdict(second: int, first: int, second_beats_first: bool, continued: int) -> str:
    """The head-to-head part of the winner rule: keep the second if it passes its own compare and (the first fails
    its own or the second beats the first); else the first if it passes its own; else neither."""
    rest = f"else version {first} if it passes its own; else neither (grpo_loop.py rollback --version {continued})"
    if second_beats_first:
        return f"Version {second} beats version {first}: keep {second} if it passes its own compare; {rest}."
    return (
        f"Version {second} does not beat version {first}: keep {second} only if it passes its own compare and "
        f"{first} fails its own; {rest}."
    )
