"""Two arms' probe runs compared by the follow-up's pre-set rule (DESIGN.md, "Follow-up study: controlled arms",
"Evaluation"; the numbers from results/followup_step0/noise_floor.md).

An arm is one checkpoint searched alike (one `probe_evaluate.py` identity) in one or two accepted runs; its runs are
pooled per statement as the mean outcome. Two arms are compared on the statements every run searched: solved shares
and the paired per-statement difference with a 95% interval from a bootstrap over statements stratified like the probe,
in total and per stratum; exact McNemar on every pair of single runs; solved within 1-16 expansions as a secondary
curve. The rule: two arms differ when the interval excludes 0 and the difference is at least 3 points, provisional with
one seed. With second seeds, a difference is confirmed only when all four cross-seed comparisons favour the same arm
(exact McNemar p < 0.05 each) and each arm's seed gap is at most a third of the claimed difference.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from lean_search.rl.evaluation import EvaluationPaths
from lean_search.rl.fixed_sets import stratum_order
from lean_search.rl.probe_evaluation import ProbeRunStart
from lean_search.search import SearchResult, StopReason, load_run_config, read_results
from lean_search.search.records import from_json_object

MIN_DIFFERENCE = 0.03
# Two seeds per arm confirm about 5 points at best (noise_floor.md, section 5).
CONFIRMABLE_DIFFERENCE = 0.05
SIGNIFICANCE = 0.05
MAX_SEED_GAP_SHARE = 1 / 3
BOOTSTRAP_SAMPLES = 2000
WITHIN_BUDGETS = (1, 2, 4, 8, 16)
CONFIRMATION_NOTE = (
    "Differences under about 5 points cannot be confirmed with two seeds (results/followup_step0/noise_floor.md, "
    "section 5): they are reported as such."
)


class SearchEnd(StrEnum):
    """Which limit ended a search."""

    PROVED = "proved"
    EXPANSIONS = "expansions"
    TOKENS = "tokens"
    WALL_CLOCK = "wall clock"
    # The frontier ran out with nodes left unexpanded at the depth cap.
    DEPTH = "depth"
    FRONTIER = "frontier exhausted"
    START_FAILED = "start failed"


@dataclass(frozen=True)
class StatementOutcome:
    problem: str
    stratum: str
    proved: bool
    # The expansions its first proof took; None when unproved.
    expansions_to_proof: int | None
    end: SearchEnd
    generated_tokens: int


@dataclass(frozen=True)
class RunSettings:
    """What must match between compared runs; the search config's digest only within one search mode."""

    probe_set_sha256: str
    max_expansions: int
    max_wall_seconds: float
    run_config_sha256: str


@dataclass(frozen=True)
class ArmRun:
    name: str
    identity: str
    settings: RunSettings
    outcomes: tuple[StatementOutcome, ...]


@dataclass(frozen=True)
class Arm:
    label: str
    runs: tuple[ArmRun, ...]


def search_end(result: SearchResult, max_depth: int) -> SearchEnd:
    match result.stop_reason:
        case StopReason.PROVED:
            return SearchEnd.PROVED
        case StopReason.EXPANSION_BUDGET:
            return SearchEnd.EXPANSIONS
        case StopReason.TOKEN_BUDGET:
            return SearchEnd.TOKENS
        case StopReason.WALL_CLOCK_BUDGET:
            return SearchEnd.WALL_CLOCK
        case StopReason.FRONTIER_EXHAUSTED if result.max_depth_reached >= max_depth:
            return SearchEnd.DEPTH
        case StopReason.FRONTIER_EXHAUSTED:
            return SearchEnd.FRONTIER
        case StopReason.START_FAILED:
            return SearchEnd.START_FAILED


def read_arm_run(directory: Path, strata: Mapping[str, str]) -> ArmRun:
    """A finished `probe_evaluate.py` run; ValueError unless its run.json says accepted. `strata`: the probe set's
    stratum of each statement."""
    record = directory / "run.json"
    if not record.exists() or not json.loads(record.read_text(encoding="utf-8"))["accepted"]:
        raise ValueError(f"{directory.name} is not an accepted probe run (run.json).")
    start = from_json_object(ProbeRunStart, json.loads((directory / "checkpoint.json").read_text(encoding="utf-8")))
    paths = EvaluationPaths(directory)
    max_depth = load_run_config(paths.config).search.max_depth
    outcomes = tuple(
        StatementOutcome(
            result.problem_name,
            strata[result.problem_name],
            result.proved,
            (result.solved_at or result.accounting).expansions if result.proved else None,
            search_end(result, max_depth),
            result.accounting.generated_tokens,
        )
        for result in read_results(paths.results)
    )
    settings = RunSettings(
        start.probe_set_sha256, start.max_expansions, start.max_wall_seconds, start.run_config_sha256
    )
    return ArmRun(directory.name, start.identity, settings, outcomes)


def check_comparable(arms: Sequence[Arm], across_search_modes: bool) -> None:
    """ValueError unless each arm is one checkpoint searched alike and every run shares the probe, budget and wall cap,
    and, unless the comparison is across search modes, the search config."""
    for arm in arms:
        identities = {run.identity for run in arm.runs}
        if len(identities) != 1:
            raise ValueError(f"Arm {arm.label} pools runs of several identities: {sorted(identities)}")
    runs = [run for arm in arms for run in arm.runs]
    fields = [
        ("probe set", lambda settings: settings.probe_set_sha256),
        ("expansion budget", lambda settings: settings.max_expansions),
        ("wall cap", lambda settings: settings.max_wall_seconds),
    ]
    if not across_search_modes:
        fields.append(("search config", lambda settings: settings.run_config_sha256))
    for what, value in fields:
        found = {run.name: value(run.settings) for run in runs}
        if len(set(found.values())) > 1:
            raise ValueError(f"The runs differ in their {what}: {found}")


def common_problems(arms: Sequence[Arm]) -> list[str]:
    """The statements every run searched, sorted."""
    searched = [{outcome.problem for outcome in run.outcomes} for arm in arms for run in arm.runs]
    return sorted(set.intersection(*searched))


def run_outcomes(run: ArmRun, problems: Sequence[str]) -> list[StatementOutcome]:
    by_problem = {outcome.problem: outcome for outcome in run.outcomes}
    return [by_problem[problem] for problem in problems]


def pooled(arm: Arm, problems: Sequence[str]) -> np.ndarray:
    """Per statement, the share of the arm's runs that proved it."""
    proved = [[outcome.proved for outcome in run_outcomes(run, problems)] for run in arm.runs]
    return np.mean(np.array(proved, dtype=float), axis=0)


def pooled_within(arm: Arm, problems: Sequence[str], budget: int) -> float:
    within = [
        [
            outcome.expansions_to_proof is not None and outcome.expansions_to_proof <= budget
            for outcome in run_outcomes(run, problems)
        ]
        for run in arm.runs
    ]
    return float(np.mean(np.array(within, dtype=float)))


def stratified_interval(differences: np.ndarray, strata: np.ndarray, seed: int) -> tuple[float, float]:
    """The 95% bootstrap interval of the mean difference, statements resampled within each stratum."""
    generator = np.random.default_rng(seed)
    totals = np.zeros(BOOTSTRAP_SAMPLES)
    for stratum in sorted(set(strata.tolist())):
        members = differences[strata == stratum]
        draws = generator.integers(0, len(members), size=(BOOTSTRAP_SAMPLES, len(members)))
        totals += members[draws].sum(axis=1)
    lower, upper = np.percentile(totals / len(differences), [2.5, 97.5])
    return float(lower), float(upper)


def mcnemar_p_value(first_only: int, second_only: int) -> float:
    """Exact two-sided McNemar: the binomial test of the discordant statements at one half."""
    discordant = first_only + second_only
    tail = sum(math.comb(discordant, count) for count in range(min(first_only, second_only) + 1))
    return min(1.0, 2 * tail / 2**discordant)


@dataclass(frozen=True)
class Difference:
    statements: int
    x_solved: float
    y_solved: float
    # x minus y, per statement, and its 95% interval.
    difference: float
    lower: float
    upper: float


@dataclass(frozen=True)
class StratumDifference:
    stratum: str
    difference: Difference


@dataclass(frozen=True)
class McNemar:
    x_run: str
    y_run: str
    # Statements only the x run proved, only the y run proved.
    x_only: int
    y_only: int
    p_value: float


@dataclass(frozen=True)
class WithinBudget:
    budget: int
    x_solved: float
    y_solved: float


@dataclass(frozen=True)
class SearchEnds:
    run: str
    counts: tuple[tuple[SearchEnd, int], ...]
    mean_generated_tokens: float


class VerdictKind(StrEnum):
    DIFFER = "differ (provisional, one seed)"
    NO_DIFFERENCE = "no difference shown"


@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    # The arm ahead when they differ.
    ahead: str | None

    @property
    def text(self) -> str:
        return f"{self.kind}: {self.ahead} ahead" if self.ahead else str(self.kind)


@dataclass(frozen=True)
class ArmComparison:
    x: str
    y: str
    overall: Difference
    strata: tuple[StratumDifference, ...]
    mcnemar: tuple[McNemar, ...]
    within: tuple[WithinBudget, ...]
    ends: tuple[SearchEnds, ...]
    verdict: Verdict


def difference(
    x_pooled: np.ndarray, y_pooled: np.ndarray, strata: np.ndarray, seed: int, selected: np.ndarray | None = None
) -> Difference:
    if selected is not None:
        x_pooled, y_pooled, strata = x_pooled[selected], y_pooled[selected], strata[selected]
    differences = x_pooled - y_pooled
    lower, upper = stratified_interval(differences, strata, seed)
    return Difference(
        len(differences), float(x_pooled.mean()), float(y_pooled.mean()), float(differences.mean()), lower, upper
    )


def rule_verdict(found: Difference, x: str, y: str) -> Verdict:
    excludes_zero = found.lower > 0 or found.upper < 0
    # Rounded, so that a pooled mean a float's width under 3 points still counts as 3.
    if excludes_zero and round(abs(found.difference), 9) >= MIN_DIFFERENCE:
        return Verdict(VerdictKind.DIFFER, x if found.difference > 0 else y)
    return Verdict(VerdictKind.NO_DIFFERENCE, None)


def search_ends(run: ArmRun, problems: Sequence[str]) -> SearchEnds:
    outcomes = run_outcomes(run, problems)
    counts = tuple((end, sum(outcome.end == end for outcome in outcomes)) for end in SearchEnd)
    tokens = float(np.mean([outcome.generated_tokens for outcome in outcomes]))
    return SearchEnds(run.name, tuple((end, count) for end, count in counts if count), tokens)


def compare_arms(x: Arm, y: Arm, seed: int = 0, across_search_modes: bool = False) -> ArmComparison:
    check_comparable([x, y], across_search_modes)
    problems = common_problems([x, y])
    if not problems:
        raise ValueError(f"Arms {x.label} and {y.label} share no searched statement.")
    strata = np.array([outcome.stratum for outcome in run_outcomes(x.runs[0], problems)])
    x_pooled, y_pooled = pooled(x, problems), pooled(y, problems)
    overall = difference(x_pooled, y_pooled, strata, seed)
    by_stratum = tuple(
        StratumDifference(stratum, difference(x_pooled, y_pooled, strata, seed, strata == stratum))
        for stratum in sorted(set(strata.tolist()), key=stratum_order)
    )
    mcnemar = []
    for x_run in x.runs:
        for y_run in y.runs:
            pairs = list(zip(run_outcomes(x_run, problems), run_outcomes(y_run, problems), strict=True))
            x_only = sum(first.proved and not second.proved for first, second in pairs)
            y_only = sum(second.proved and not first.proved for first, second in pairs)
            mcnemar.append(McNemar(x_run.name, y_run.name, x_only, y_only, mcnemar_p_value(x_only, y_only)))
    within = tuple(
        WithinBudget(budget, pooled_within(x, problems, budget), pooled_within(y, problems, budget))
        for budget in WITHIN_BUDGETS
    )
    ends = tuple(search_ends(run, problems) for arm in (x, y) for run in arm.runs)
    return ArmComparison(
        x.label, y.label, overall, by_stratum, tuple(mcnemar), within, ends, rule_verdict(overall, x.label, y.label)
    )


@dataclass(frozen=True)
class SeedPair:
    x_seed: int
    y_seed: int
    # x minus y over the statements both searched, and the statements each pooled outcome favours.
    difference: float
    x_ahead: int
    y_ahead: int
    p_value: float


@dataclass(frozen=True)
class SeedConfirmation:
    pairs: tuple[SeedPair, ...]
    # The mean of the four cross-seed differences.
    claimed_difference: float
    x_seed_gap: float
    y_seed_gap: float
    confirmed: bool
    ahead: str | None
    reasons: tuple[str, ...]


def confirm_with_seeds(
    x_seeds: tuple[Arm, Arm], y_seeds: tuple[Arm, Arm], across_search_modes: bool = False
) -> SeedConfirmation:
    """Each seed's checkpoint pooled per statement over its runs; a pair's McNemar is the exact sign test over the
    statements whose pooled outcomes differ (McNemar itself with one run per checkpoint)."""
    arms = [*x_seeds, *y_seeds]
    check_comparable(arms, across_search_modes)
    problems = common_problems(arms)
    x_pooled = [pooled(arm, problems) for arm in x_seeds]
    y_pooled = [pooled(arm, problems) for arm in y_seeds]
    pairs = []
    for x_index, x_values in enumerate(x_pooled):
        for y_index, y_values in enumerate(y_pooled):
            x_ahead, y_ahead = int(np.sum(x_values > y_values)), int(np.sum(y_values > x_values))
            pairs.append(
                SeedPair(
                    x_index + 1,
                    y_index + 1,
                    float(np.mean(x_values - y_values)),
                    x_ahead,
                    y_ahead,
                    mcnemar_p_value(x_ahead, y_ahead),
                )
            )
    claimed = float(np.mean([pair.difference for pair in pairs]))
    x_gap = abs(float(x_pooled[0].mean() - x_pooled[1].mean()))
    y_gap = abs(float(y_pooled[0].mean() - y_pooled[1].mean()))
    reasons = []
    if len({pair.difference > 0 for pair in pairs}) > 1 or any(pair.difference == 0 for pair in pairs):
        reasons.append("the four cross-seed comparisons do not all favour the same arm")
    if any(pair.p_value >= SIGNIFICANCE for pair in pairs):
        reasons.append(f"not every cross-seed McNemar p is below {SIGNIFICANCE}")
    for label, gap in ((x_seeds[0].label, x_gap), (y_seeds[0].label, y_gap)):
        if gap > MAX_SEED_GAP_SHARE * abs(claimed):
            reasons.append(f"{label}'s seed gap {100 * gap:.1f} points exceeds a third of the claimed difference")
    confirmed = not reasons
    ahead = (x_seeds[0].label if claimed > 0 else y_seeds[0].label) if confirmed else None
    return SeedConfirmation(tuple(pairs), claimed, x_gap, y_gap, confirmed, ahead, tuple(reasons))


@dataclass(frozen=True)
class VariantRow:
    label: str
    runs: int
    comparison: ArmComparison

    @property
    def verdict(self) -> str:
        """Against v0 a difference under 3 points is a step too small, never "equal" (DESIGN.md, step 2)."""
        if round(abs(self.comparison.overall.difference), 9) < MIN_DIFFERENCE:
            return "step too small (under 3 points from the reference)"
        return self.comparison.verdict.text


def against_reference(
    reference: Arm, variants: Sequence[Arm], seed: int = 0, across_search_modes: bool = False
) -> tuple[VariantRow, ...]:
    """Every variant against one reference (v0), each on the statements it and the reference searched."""
    return tuple(
        VariantRow(variant.label, len(variant.runs), compare_arms(variant, reference, seed, across_search_modes))
        for variant in variants
    )
