"""Group-relative advantages: each known tactic's reward and each sample's score minus the group's baseline."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardParts

# Advantages below this count as zero when deciding whether a group carries a signal.
ZERO_ADVANTAGE = 1e-12


class CreditMode(StrEnum):
    # Tactic tokens get their tactic's reward minus the baseline, the explanation the sample's score minus it.
    PER_TACTIC = "per_tactic"
    # Every sampled token gets the sample's score minus the baseline (the single-step comparison).
    SEQUENCE = "sequence"


@dataclass(frozen=True)
class SampleAdvantages:
    # Score minus baseline; None without a known score.
    sequence: float | None
    # Per executed tactic: reward minus baseline; None for unknown and masked tactics.
    tactics: tuple[float | None, ...]
    # The closing fence and end of turn: the last tactic's advantage after a complete block, else None.
    closing: float | None


@dataclass(frozen=True)
class GroupAdvantages:
    # The multiplicity-weighted mean score of the samples with a known score.
    baseline: float | None
    samples: tuple[SampleAdvantages, ...]
    # Multiplicity-weighted sums over known tactics of |(1 − λ)(G − b_G)| and |λ(L − b_L)|, which add up to R − b.
    global_magnitude: float
    local_magnitude: float

    def has_signal(self, mode: CreditMode) -> bool:
        values = [sample.sequence for sample in self.samples]
        if mode == CreditMode.PER_TACTIC:
            values += [value for sample in self.samples for value in sample.tactics]
        return any(value is not None and abs(value) > ZERO_ADVANTAGE for value in values)


def weighted_mean(values: Sequence[float], weights: Sequence[int]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def mean_parts(known: Sequence[RewardParts]) -> RewardParts:
    return RewardParts(
        sum(parts.global_part for parts in known) / len(known), sum(parts.local_part for parts in known) / len(known)
    )


def sample_advantages(sample: GroupSample, baseline: float | None) -> SampleAdvantages:
    score = sample.score
    if baseline is None:
        return SampleAdvantages(None, tuple(None for _ in sample.tactics), None)
    tactics = tuple(None if tactic.parts is None else tactic.parts.total - baseline for tactic in sample.tactics)
    return SampleAdvantages(
        None if score is None else score - baseline,
        tactics,
        tactics[-1] if sample.complete and tactics else None,
    )


def group_advantages(group: PolicyGroup) -> GroupAdvantages:
    scored = [(sample, mean_parts(sample.known)) for sample in group.samples if sample.known]
    if not scored:
        return GroupAdvantages(None, tuple(sample_advantages(sample, None) for sample in group.samples), 0.0, 0.0)
    weights = [sample.multiplicity for sample, _ in scored]
    global_baseline = weighted_mean([parts.global_part for _, parts in scored], weights)
    local_baseline = weighted_mean([parts.local_part for _, parts in scored], weights)
    baseline = global_baseline + local_baseline
    known = [(parts, sample.multiplicity) for sample, _ in scored for parts in sample.known]
    return GroupAdvantages(
        baseline=baseline,
        samples=tuple(sample_advantages(sample, baseline) for sample in group.samples),
        global_magnitude=sum(abs(parts.global_part - global_baseline) * weight for parts, weight in known),
        local_magnitude=sum(abs(parts.local_part - local_baseline) * weight for parts, weight in known),
    )


def local_share_of_advantages(groups: Sequence[GroupAdvantages]) -> float:
    """The fraction of the summed |tactic advantage| that comes from the local term."""
    local = sum(group.local_magnitude for group in groups)
    total = local + sum(group.global_magnitude for group in groups)
    return local / total if total else 0.0
