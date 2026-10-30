"""The search options A/B in the loop (`sampling.options_arm`; rl/README.md, "Search options A/B in the loop").

Per phase, each arm's trees finished in it (`arm_outcomes`): solves, tokens, trainable groups and tree-hours, the
options arm's differences to the control arm with 95% bootstrap intervals over trees, and a balance check of what the
hash split leaves alike. The decision pools the trees by the phase in which their search started, so a long tree cut
off by a pause still counts in its own phase: at the check after the A/B's phases 2, 4 and 6 (`options_look`) a
bootstrap stratified by start phase and arm gives R, the options arm's solves per generated token over the control
arm's, and G, the same for trainable groups (feedback groups weighted by their samples); `options_verdict` applies the
rule. Trees an excluded (rejected) version sampled are left out. After `max_phases` A/B phases the arm switches off.
"""

import dataclasses
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

import numpy

from lean_search.monitoring.families import (
    ArmBalance,
    ArmDifference,
    ArmOutcome,
    OptionsLook,
    OptionsVerdict,
    RatioInterval,
)
from lean_search.rl.search_options import CONTROL_ARM, OptionsArmConfig
from lean_search.rl.tree_store import TreeEntry

# The per-phase intervals: each arm's trees drawn with replacement.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0
CONFIDENCE = 0.95
BALANCE_CONFIDENCE = 0.99
# The planned looks, by the number of A/B phases pooled, and their confidence (owner decision 2026-10-30).
LOOK_CONFIDENCES = {2: 0.99, 4: 0.99, 6: 0.95}
FUTILITY_LOOK = 4
LAST_LOOK = 6
LOOK_RESAMPLES = 10_000
RESAMPLE_CHUNK = 1000
ADOPT_MIN_RATIO = 1.05
GUARD_MIN_RATIO = 0.95
GUARD_CONFIDENCE = 0.95


@dataclass(frozen=True)
class RatioSample:
    """Per tree, the parts of a ratio of sums over trees."""

    numerators: numpy.ndarray
    denominators: numpy.ndarray

    @property
    def ratio(self) -> float | None:
        total = self.denominators.sum()
        return float(self.numerators.sum() / total) if total else None


def ratio_sample(
    entries: Sequence[TreeEntry], numerator: Callable[[TreeEntry], float], denominator: Callable[[TreeEntry], float]
) -> RatioSample:
    return RatioSample(
        numpy.array([numerator(entry) for entry in entries], dtype=float),
        numpy.array([denominator(entry) for entry in entries], dtype=float),
    )


def resampled_ratios(sample: RatioSample, generator: numpy.random.Generator) -> numpy.ndarray:
    drawn = generator.integers(0, len(sample.numerators), size=(BOOTSTRAP_RESAMPLES, len(sample.numerators)))
    with numpy.errstate(divide="ignore", invalid="ignore"):
        return sample.numerators[drawn].sum(axis=1) / sample.denominators[drawn].sum(axis=1)


def percentile_interval(draws: numpy.ndarray, confidence: float) -> tuple[float, float]:
    """A draw of zero cost gives no rate: left out (NaN when every draw does, as in a tiny smoke run)."""
    finite = draws[numpy.isfinite(draws)]
    if not len(finite):
        return float("nan"), float("nan")
    low, high = numpy.quantile(finite, [(1 - confidence) / 2, (1 + confidence) / 2])
    return float(low), float(high)


def ratio_difference(
    arm: RatioSample, control: RatioSample, scale: float, confidence: float = CONFIDENCE
) -> ArmDifference | None:
    """The arm's ratio minus the control's, with a percentile interval from drawing each arm's trees with
    replacement; None while either has nothing to divide by."""
    arm_ratio, control_ratio = arm.ratio, control.ratio
    if arm_ratio is None or control_ratio is None:
        return None
    generator = numpy.random.default_rng(BOOTSTRAP_SEED)
    draws = scale * (resampled_ratios(arm, generator) - resampled_ratios(control, generator))
    low, high = percentile_interval(draws, confidence)
    return ArmDifference(scale * (arm_ratio - control_ratio), low, high)


def proved(entry: TreeEntry) -> float:
    return float(entry.proved)


def one(entry: TreeEntry) -> float:
    return 1.0


def generated_tokens(entry: TreeEntry) -> float:
    return entry.summary.generated_tokens


def tokens_to_first_proof(entry: TreeEntry) -> float:
    return entry.summary.generated_tokens_to_first_proof


def active_seconds(entry: TreeEntry) -> float:
    return entry.active_seconds


def difficulty(entry: TreeEntry) -> float:
    return entry.difficulty or 0.0


def has_difficulty(entry: TreeEntry) -> float:
    return float(entry.difficulty is not None)


def verified(entry: TreeEntry) -> float:
    return float(bool(entry.verified))


def has_verified(entry: TreeEntry) -> float:
    return float(entry.verified is not None)


def root_valid_blocks(entry: TreeEntry) -> float:
    return entry.summary.root_valid_blocks


def root_judged_blocks(entry: TreeEntry) -> float:
    return entry.summary.root_judged_blocks


def root_blocks(entry: TreeEntry) -> float:
    return entry.summary.root_blocks


def feedback_group_weight(entries: Sequence[TreeEntry]) -> float:
    """A feedback round's samples against a first-round expansion's (4 of 8 in the loop's A/B)."""
    summaries = [entry.summary for entry in entries]
    rounds = sum(summary.feedback_expansions for summary in summaries)
    if not rounds:
        return 1.0
    per_round = sum(summary.feedback_samples for summary in summaries) / rounds
    per_expansion = sum(summary.policy_samples for summary in summaries) / sum(
        summary.policy_expansions for summary in summaries
    )
    return per_round / per_expansion


def weighted_groups(weight: float) -> Callable[[TreeEntry], float]:
    def groups(entry: TreeEntry) -> float:
        feedback = entry.summary.feedback_trainable_groups
        return entry.summary.trainable_groups - feedback + weight * feedback

    return groups


def ratio_or_none(
    entries: Sequence[TreeEntry], numerator: Callable[[TreeEntry], float], denominator: Callable[[TreeEntry], float]
) -> float | None:
    return ratio_sample(entries, numerator, denominator).ratio


def arm_balance(arm: Sequence[TreeEntry], control: Sequence[TreeEntry]) -> ArmBalance:
    differences = [
        ratio_difference(
            ratio_sample(arm, numerator, denominator),
            ratio_sample(control, numerator, denominator),
            1.0,
            BALANCE_CONFIDENCE,
        )
        for numerator, denominator in (
            (difficulty, has_difficulty),
            (verified, has_verified),
            (root_valid_blocks, root_judged_blocks),
            (root_blocks, one),
        )
    ]
    balanced = all(difference is None or difference.low <= 0 <= difference.high for difference in differences)
    return ArmBalance(*differences, balanced=balanced)


def arm_outcome(entries: Sequence[TreeEntry], control: Sequence[TreeEntry] | None) -> ArmOutcome:
    """`control`: the control arm's trees, for an options arm's differences and balance."""
    groups = sum(entry.summary.trainable_groups for entry in entries)
    weighted = weighted_groups(feedback_group_weight(entries))
    weighted_total = sum(map(weighted, entries))
    tokens = sum(entry.summary.generated_tokens for entry in entries)
    outcome = ArmOutcome(
        trees=len(entries),
        solved=sum(entry.proved for entry in entries),
        trainable_groups=groups,
        generated_tokens=tokens,
        solved_per_thousand_tokens=1e3 * (ratio_or_none(entries, proved, generated_tokens) or 0.0),
        trainable_groups_per_tree=groups / len(entries),
        feedback_trainable_groups=sum(entry.summary.feedback_trainable_groups for entry in entries),
        generated_tokens_to_first_proof=sum(entry.summary.generated_tokens_to_first_proof for entry in entries),
        wall_seconds=sum(entry.wall_seconds for entry in entries),
        lean_seconds=sum(entry.summary.lean_seconds for entry in entries),
        solved_per_tree_hour=3600.0 * (ratio_or_none(entries, proved, active_seconds) or 0.0),
        active_seconds=sum(entry.active_seconds for entry in entries),
        weighted_trainable_groups=weighted_total,
        trainable_groups_per_thousand_tokens=1e3 * weighted_total / tokens if tokens else 0.0,
        mean_difficulty=ratio_or_none(entries, difficulty, has_difficulty),
        verified_share=ratio_or_none(entries, verified, has_verified),
        root_valid_rate=ratio_or_none(entries, root_valid_blocks, root_judged_blocks),
        root_blocks_per_tree=sum(entry.summary.root_blocks for entry in entries) / len(entries),
    )
    if control is None:
        return outcome
    control_groups = weighted_groups(feedback_group_weight(control))
    return dataclasses.replace(
        outcome,
        solved_per_thousand_tokens_difference=ratio_difference(
            ratio_sample(entries, proved, generated_tokens), ratio_sample(control, proved, generated_tokens), 1e3
        ),
        solved_per_tree_hour_difference=ratio_difference(
            ratio_sample(entries, proved, active_seconds), ratio_sample(control, proved, active_seconds), 3600.0
        ),
        trainable_groups_per_thousand_tokens_difference=ratio_difference(
            ratio_sample(entries, weighted, generated_tokens),
            ratio_sample(control, control_groups, generated_tokens),
            1e3,
        ),
        balance=arm_balance(entries, control),
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
        return f"no difference {unit} yet"
    return f"{difference.difference:+.3g} {unit} [{difference.low:+.3g}, {difference.high:+.3g}]"


def balance_text(balance: ArmBalance) -> str:
    parts = [
        difference_text(balance.mean_difficulty, "in mean difficulty"),
        difference_text(balance.verified_share, "in verified share"),
        difference_text(balance.root_valid_rate, "in the root's first-round valid share"),
        difference_text(balance.root_blocks_per_tree, "in the root's first-round distinct blocks"),
    ]
    return f"balance (99%): {', '.join(parts)}: {'balanced' if balance.balanced else 'NOT balanced'}"


def optional_rate(value: float | None, digits: str = ".3g") -> str:
    return "-" if value is None else format(value, digits)


def arm_outcome_text(arm: str, outcome: ArmOutcome) -> str:
    text = (
        f"{arm}: {outcome.trees} trees, {outcome.solved} solved, {outcome.trainable_groups} trainable groups "
        f"({outcome.feedback_trainable_groups} of feedback rounds; {outcome.weighted_trainable_groups:.1f} weighted), "
        f"{outcome.generated_tokens / 1e6:.1f}M generated tokens ({outcome.generated_tokens_to_first_proof / 1e6:.1f}M "
        f"to the first proof), {outcome.active_seconds / 3600:.1f} active tree-hours "
        f"({outcome.wall_seconds / 3600:.1f} with pauses), {outcome.lean_seconds / 3600:.1f} Lean hours; "
        f"{outcome.solved_per_thousand_tokens:.3g} solves and {outcome.trainable_groups_per_thousand_tokens:.3g} "
        f"weighted groups per 1k tokens, {outcome.solved_per_tree_hour:.3g} solves per active tree-hour; mean "
        f"difficulty {optional_rate(outcome.mean_difficulty)}, "
        f"verified {optional_rate(outcome.verified_share, '.1%')}, "
        f"root first round {optional_rate(outcome.root_valid_rate, '.1%')} valid, "
        f"{outcome.root_blocks_per_tree:.2f} distinct blocks"
    )
    if arm == CONTROL_ARM:
        return text
    tokens = difference_text(outcome.solved_per_thousand_tokens_difference, "solves per 1k tokens")
    hours = difference_text(outcome.solved_per_tree_hour_difference, "per active tree-hour")
    groups = difference_text(outcome.trainable_groups_per_thousand_tokens_difference, "groups per 1k tokens")
    differences = f"minus control (95% bootstrap over trees): {tokens}, {hours}, {groups}"
    return f"{text}; {differences}" + ("" if outcome.balance is None else f"; {balance_text(outcome.balance)}")


def arm_outcomes_text(outcomes: dict[str, ArmOutcome]) -> str:
    return "; ".join(arm_outcome_text(arm, outcome) for arm, outcome in outcomes.items())


def options_ab_phases(entries: Sequence[TreeEntry], name: str) -> list[int]:
    """The phases in which searches started in the options arm `name`."""
    return sorted({entry.start_phase for entry in entries if entry.summary.arm == name})


def options_arm_finished(entries: Sequence[TreeEntry], config: OptionsArmConfig, collecting: int) -> bool:
    """The A/B ran its `max_phases` phases before `collecting`."""
    started = [phase for phase in options_ab_phases(entries, config.name) if phase < collecting]
    return bool(config.max_phases) and len(started) >= config.max_phases


# Per tree in the pooled look: solved, generated tokens, those to the first proof, weighted trainable groups.
LOOK_COLUMNS = 4


def look_columns(entries: Sequence[TreeEntry], groups: Callable[[TreeEntry], float]) -> numpy.ndarray:
    return numpy.array(
        [[entry.proved, generated_tokens(entry), tokens_to_first_proof(entry), groups(entry)] for entry in entries],
        dtype=float,
    ).reshape(-1, LOOK_COLUMNS)


def stratified_totals(
    strata: Sequence[numpy.ndarray], generator: numpy.random.Generator, resamples: int
) -> numpy.ndarray:
    """Per draw, the columns summed over every stratum's trees drawn with replacement within the stratum."""
    totals = numpy.zeros((resamples, LOOK_COLUMNS))
    for columns in strata:
        for start in range(0, resamples, RESAMPLE_CHUNK):
            count = min(RESAMPLE_CHUNK, resamples - start)
            drawn = generator.integers(0, len(columns), size=(count, len(columns)))
            totals[start : start + count] += columns[drawn].sum(axis=1)
    return totals


def ratio_of_rates(arm: numpy.ndarray, control: numpy.ndarray, numerator: int, cost: int) -> numpy.ndarray:
    with numpy.errstate(divide="ignore", invalid="ignore"):
        return (arm[..., numerator] / arm[..., cost]) / (control[..., numerator] / control[..., cost])


def ratio_interval(point: float, draws: numpy.ndarray, confidence: float) -> RatioInterval:
    low, high = percentile_interval(draws, confidence)
    return RatioInterval(point, low, high, confidence)


def options_verdict(look: int, solves: RatioInterval, solves_95: RatioInterval, guard_holds: bool) -> OptionsVerdict:
    """Adopt at any look if R's lower bound is above 1, R at least 1.05 and the groups guard holds; drop as harmful
    at any look if R's upper bound is below 1; drop for futility at look 4 if R's upper 95% bound is below 1.05; drop
    at look 6 if not adopted."""
    if solves.low > 1.0 and solves.ratio >= ADOPT_MIN_RATIO and guard_holds:
        return OptionsVerdict.ADOPT
    if solves.high < 1.0:
        return OptionsVerdict.DROP_HARMFUL
    if look == FUTILITY_LOOK and solves_95.high < ADOPT_MIN_RATIO:
        return OptionsVerdict.DROP_FUTILE
    if look >= LAST_LOOK:
        return OptionsVerdict.DROP_NOT_ADOPTED
    return OptionsVerdict.CONTINUE


def options_look(
    entries: Sequence[TreeEntry], name: str, phase: int, rejected_versions: Collection[int]
) -> OptionsLook | None:
    """The look due at phase `phase`'s check: the one after the A/B phase before it, when that is its 2nd, 4th or 6th;
    its population is the trees started in the A/B's phases so far (finished by now), without those a rejected
    version sampled."""
    phases = options_ab_phases(entries, name)
    if phase - 1 not in phases:
        return None
    look = phases.index(phase - 1) + 1
    if look not in LOOK_CONFIDENCES:
        return None
    pooled = phases[:look]
    rejected = set(rejected_versions)
    population = [
        entry
        for entry in entries
        if entry.summary.arm in (name, CONTROL_ARM)
        and entry.start_phase in pooled
        and not rejected.intersection(entry.summary.sampling_versions)
    ]
    arm = [entry for entry in population if entry.summary.arm == name]
    control = [entry for entry in population if entry.summary.arm == CONTROL_ARM]
    arm_groups = weighted_groups(feedback_group_weight(arm))
    control_groups = weighted_groups(feedback_group_weight(control))
    arm_strata = [
        look_columns([entry for entry in arm if entry.start_phase == number], arm_groups) for number in pooled
    ]
    control_strata = [
        look_columns([entry for entry in control if entry.start_phase == number], control_groups) for number in pooled
    ]
    generator = numpy.random.default_rng(BOOTSTRAP_SEED)
    arm_draws = stratified_totals([stratum for stratum in arm_strata if len(stratum)], generator, LOOK_RESAMPLES)
    control_draws = stratified_totals(
        [stratum for stratum in control_strata if len(stratum)], generator, LOOK_RESAMPLES
    )
    arm_totals = look_columns(arm, arm_groups).sum(axis=0)
    control_totals = look_columns(control, control_groups).sum(axis=0)

    def interval(numerator: int, cost: int, confidence: float) -> RatioInterval:
        point = float(ratio_of_rates(arm_totals, control_totals, numerator, cost))
        return ratio_interval(point, ratio_of_rates(arm_draws, control_draws, numerator, cost), confidence)

    confidence = LOOK_CONFIDENCES[look]
    solves = interval(0, 1, confidence)
    solves_95 = interval(0, 1, 0.95)
    groups = interval(3, 1, GUARD_CONFIDENCE)
    guard_holds = groups.low >= GUARD_MIN_RATIO
    return OptionsLook(
        arm=name,
        look=look,
        phases=tuple(pooled),
        arm_trees=len(arm),
        control_trees=len(control),
        solves_per_token=solves,
        solves_per_token_95=solves_95,
        solves_per_token_to_first_proof=interval(0, 2, confidence),
        groups_per_token=groups,
        guard_holds=guard_holds,
        verdict=options_verdict(look, solves, solves_95, guard_holds),
    )


def interval_text(interval: RatioInterval) -> str:
    return f"{interval.ratio:.3f} [{interval.low:.3f}, {interval.high:.3f}] ({interval.confidence:.0%})"


def options_look_text(look: OptionsLook) -> str:
    phases = f"{look.phases[0]}-{look.phases[-1]}" if len(look.phases) > 1 else str(look.phases[0])
    guard = "holds" if look.guard_holds else "fails"
    return (
        f"Search options A/B ({look.arm}) look {look.look}, the trees started in phases {phases} ({look.arm_trees} "
        f"{look.arm}, {look.control_trees} control; bootstrap within phase and arm): R, solves per generated token "
        f"over control's, {interval_text(look.solves_per_token)}, 95% [{look.solves_per_token_95.low:.3f}, "
        f"{look.solves_per_token_95.high:.3f}]; to the first proof "
        f"{interval_text(look.solves_per_token_to_first_proof)}; G, weighted trainable groups per token, "
        f"{interval_text(look.groups_per_token)}, guard >= {GUARD_MIN_RATIO} {guard}: verdict {look.verdict}"
    )
