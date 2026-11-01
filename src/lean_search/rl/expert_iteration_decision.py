"""Whether to keep a published expert-iteration round (rl/README.md, "Expert iteration", "Decision"): its held-out
states against version 0's and its reference's, its whole probe set paired per problem with the reference runs, and
its probe trees' diversity and explanations against the reference runs' trees."""

import math
from dataclasses import dataclass

from lean_search.rl.health_checks import HeldOutRates
from lean_search.rl.loop_config import HealthConfig
from lean_search.rl.probe_rating import PairedComparison
from lean_search.rl.tree_summary import SearchHabits, binned_median

# The whole set's paired difference has a 95% half-width of about 3 points, so the rule keeps a round only when it
# observed about +1 point or more: a demand for evidence, not a non-inferiority test.
MIN_PAIRED_DIFFERENCE_LOWER = -0.02
# The held-out valid-Lean rate may fall this many per-sample standard errors below the reference's.
HELD_OUT_STANDARD_ERRORS = 2.0


@dataclass(frozen=True)
class HeldOutRun:
    rates: HeldOutRates
    samples: int

    @property
    def valid_standard_error(self) -> float:
        return math.sqrt(self.rates.valid_rate * (1 - self.rates.valid_rate) / self.samples)


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


def round_checks(evidence: RoundEvidence, health: HealthConfig) -> tuple[Check, ...]:
    """Every check must pass to keep the round; the health checks' fractions, applied before the loop restarts."""
    zero = evidence.version_zero.rates
    reference = evidence.reference_held_out
    candidate = evidence.candidate_held_out.rates
    overall = evidence.paired.overall
    valid_floor = reference.rates.valid_rate - HELD_OUT_STANDARD_ERRORS * reference.valid_standard_error
    distinct_floor = health.min_distinct_samples_fraction * evidence.reference_habits.distinct_blocks_per_expansion
    explanation_floor = health.min_explanation_characters_fraction * median_explanation(evidence.reference_habits)
    return (
        Check(
            "held-out valid Lean against version 0",
            candidate.valid_rate >= health.min_held_out_valid_fraction * zero.valid_rate,
            f"{candidate.valid_rate:.1%} >= {health.min_held_out_valid_fraction} x {zero.valid_rate:.1%}",
        ),
        Check(
            "held-out success against version 0",
            candidate.success >= health.min_held_out_success_fraction * zero.success,
            f"{candidate.success:.1%} >= {health.min_held_out_success_fraction} x {zero.success:.1%}",
        ),
        Check(
            "held-out valid Lean against the reference",
            candidate.valid_rate >= valid_floor,
            f"{candidate.valid_rate:.1%} >= {reference.rates.valid_rate:.1%} - {HELD_OUT_STANDARD_ERRORS:g} SE",
        ),
        Check(
            "probe paired solve difference",
            overall.difference >= 0 and overall.lower > MIN_PAIRED_DIFFERENCE_LOWER,
            f"{100 * overall.difference:+.1f} points >= 0, lower bound {100 * overall.lower:+.1f} > "
            f"{100 * MIN_PAIRED_DIFFERENCE_LOWER:+.0f}",
        ),
        Check(
            "distinct blocks per expansion",
            evidence.candidate_habits.distinct_blocks_per_expansion >= distinct_floor,
            f"{evidence.candidate_habits.distinct_blocks_per_expansion:.2f} >= {distinct_floor:.2f}",
        ),
        Check(
            "median explanation characters",
            median_explanation(evidence.candidate_habits) >= explanation_floor,
            f"{median_explanation(evidence.candidate_habits):.0f} >= {explanation_floor:.0f}",
        ),
    )
