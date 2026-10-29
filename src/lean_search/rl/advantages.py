"""Advantages: the first tactic and the sample's score against the group's baseline, later tactics within the block."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardParts, TacticReward

# Advantages below this count as zero when deciding whether a group carries a signal.
ZERO_ADVANTAGE = 1e-12


class CreditMode(StrEnum):
    # Tactic tokens get their tactic's advantage, the explanation the sample's score minus the baseline.
    PER_TACTIC = "per_tactic"
    # Every sampled token gets the sample's score minus the baseline (the single-step comparison).
    SEQUENCE = "sequence"


@dataclass(frozen=True)
class SampleAdvantages:
    # Score minus baseline; None without a known score.
    sequence: float | None
    # Per executed tactic: its gain within the block, else its reward minus the baseline; None for unknown and masked.
    tactics: tuple[float | None, ...]
    # The closing fence and end of turn: 0 after a complete block (stopping keeps the state reached), else None.
    closing: float | None


@dataclass(frozen=True)
class GroupAdvantages:
    # The multiplicity-weighted mean score of the samples with a known score.
    baseline: float | None
    samples: tuple[SampleAdvantages, ...]
    # Multiplicity-weighted sums of |global part| and |local part| over the tactic advantages.
    global_magnitude: float
    local_magnitude: float

    def has_signal(self, mode: CreditMode) -> bool:
        values = [sample.sequence for sample in self.samples]
        if mode == CreditMode.PER_TACTIC:
            values += [value for sample in self.samples for value in sample.tactics]
        return any(value is not None and abs(value) > ZERO_ADVANTAGE for value in values)


def weighted_mean(values: Sequence[RewardParts], weights: Sequence[int]) -> RewardParts:
    total = sum(weights)
    return RewardParts(
        sum(value.global_part * weight for value, weight in zip(values, weights, strict=True)) / total,
        sum(value.local_part * weight for value, weight in zip(values, weights, strict=True)) / total,
    )


def tactic_advantage(tactic: TacticReward, baseline: RewardParts | None) -> RewardParts | None:
    if tactic.gain is not None:
        return tactic.gain
    if tactic.parts is None or baseline is None:
        return None
    return tactic.parts - baseline


def sample_advantages(sample: GroupSample, baseline: RewardParts | None) -> SampleAdvantages:
    score = sample.score
    tactics = [tactic_advantage(tactic, baseline) for tactic in sample.tactics]
    return SampleAdvantages(
        None if score is None or baseline is None else score - baseline.total,
        tuple(None if parts is None else parts.total for parts in tactics),
        0.0 if sample.complete else None,
    )


def group_advantages(group: PolicyGroup) -> GroupAdvantages:
    scored = [(parts, sample.multiplicity) for sample in group.samples if (parts := sample.score_parts) is not None]
    baseline = weighted_mean([parts for parts, _ in scored], [weight for _, weight in scored]) if scored else None
    advantages = [
        (parts, sample.multiplicity)
        for sample in group.samples
        for tactic in sample.tactics
        if (parts := tactic_advantage(tactic, baseline)) is not None
    ]
    return GroupAdvantages(
        baseline=None if baseline is None else baseline.total,
        samples=tuple(sample_advantages(sample, baseline) for sample in group.samples),
        global_magnitude=sum(abs(parts.global_part) * weight for parts, weight in advantages),
        local_magnitude=sum(abs(parts.local_part) * weight for parts, weight in advantages),
    )


def local_share_of_advantages(groups: Sequence[GroupAdvantages]) -> float:
    """The fraction of the summed |tactic advantage| that comes from the local term."""
    local = sum(group.local_magnitude for group in groups)
    total = local + sum(group.global_magnitude for group in groups)
    return local / total if total else 0.0
