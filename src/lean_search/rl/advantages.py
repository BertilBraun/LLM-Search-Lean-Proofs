"""Advantages: a block's anchor and the sample's score against the group's baselines, later tactics within the block."""

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
    # Every sampled token gets r minus the group's mean r, r = 1 when the sample reaches the proof graph.
    PROOF_SUCCESS = "proof_success"
    # Every sampled token gets r minus the group's mean r over the samples with an r (`GroupSample.verified_progress`);
    # a sample without one (a clean block ending in an unknown state) is left out.
    VERIFIED_PROGRESS = "verified_progress"
    # As verified progress, r weighted by the share of the node's remaining proof the block covers
    # (`GroupSample.verified_fraction`): a longer correct block earns more than a one-step one.
    VERIFIED_FRACTION = "verified_fraction"


@dataclass(frozen=True)
class SampleAdvantages:
    # Score minus baseline; None without a known score.
    sequence: float | None
    # Per executed tactic: its gain within the block, else (the anchor) its reward minus the first-tactic baseline; None
    # for unknown and masked tactics. They add up to score minus the first-tactic baseline.
    tactics: tuple[float | None, ...]
    # The closing fence and end of turn: 0 after a complete block (stopping keeps the state reached), else None.
    closing: float | None
    # r minus the group's proof-success baseline (`GroupSample.reaches_proof_graph`).
    proof_success: float
    # r minus the group's verified-progress baseline; None without an r.
    verified_progress: float | None
    # The same for the progress-fraction r.
    verified_fraction: float | None

    def whole(self, mode: CreditMode) -> float | None:
        """The advantage a mode gives every sampled token (per-tactic credit: the explanation's)."""
        match mode:
            case CreditMode.PER_TACTIC | CreditMode.SEQUENCE:
                return self.sequence
            case CreditMode.PROOF_SUCCESS:
                return self.proof_success
            case CreditMode.VERIFIED_PROGRESS:
                return self.verified_progress
            case CreditMode.VERIFIED_FRACTION:
                return self.verified_fraction


@dataclass(frozen=True)
class GroupAdvantages:
    # The multiplicity-weighted mean score of the samples with a known score.
    baseline: float | None
    # The same mean of their anchors' rewards: a later tactic's progress is not charged to the first.
    first_tactic_baseline: float | None
    # The multiplicity-weighted share of samples reaching the proof graph.
    proof_success_baseline: float
    samples: tuple[SampleAdvantages, ...]
    # Multiplicity-weighted sums of |global part| and |local part| over the tactic advantages.
    global_magnitude: float
    local_magnitude: float

    def has_signal(self, mode: CreditMode) -> bool:
        values: list[float | None]
        match mode:
            case CreditMode.PER_TACTIC:
                values = [sample.sequence for sample in self.samples]
                values += [value for sample in self.samples for value in sample.tactics]
            case CreditMode.SEQUENCE:
                values = [sample.sequence for sample in self.samples]
            case CreditMode.PROOF_SUCCESS:
                values = [sample.proof_success for sample in self.samples]
            case CreditMode.VERIFIED_PROGRESS:
                values = [sample.verified_progress for sample in self.samples]
            case CreditMode.VERIFIED_FRACTION:
                values = [sample.verified_fraction for sample in self.samples]
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


def sample_advantages(
    sample: GroupSample,
    baseline: RewardParts | None,
    first_tactic_baseline: RewardParts | None,
    proof_success_baseline: float,
    progress_baseline: float | None,
    fraction_baseline: float | None,
) -> SampleAdvantages:
    score = sample.score
    tactics = [tactic_advantage(tactic, first_tactic_baseline) for tactic in sample.tactics]
    return SampleAdvantages(
        None if score is None or baseline is None else score - baseline.total,
        tuple(None if parts is None else parts.total for parts in tactics),
        0.0 if sample.complete else None,
        float(sample.reaches_proof_graph) - proof_success_baseline,
        minus_baseline(sample.verified_progress, progress_baseline),
        minus_baseline(sample.verified_fraction, fraction_baseline),
    )


def minus_baseline(value: float | None, baseline: float | None) -> float | None:
    return None if value is None or baseline is None else value - baseline


def scored_baseline(values: Sequence[tuple[float | None, int]]) -> float | None:
    """The multiplicity-weighted mean of the values that are not None; None without one."""
    known = [(value, weight) for value, weight in values if value is not None]
    total = sum(weight for _, weight in known)
    return sum(value * weight for value, weight in known) / total if total else None


def group_advantages(group: PolicyGroup) -> GroupAdvantages:
    scored = [sample for sample in group.samples if sample.anchor_parts is not None]
    weights = [sample.multiplicity for sample in scored]
    baseline = first_tactic_baseline = None
    if scored:
        baseline = weighted_mean([sample.score_parts for sample in scored], weights)
        first_tactic_baseline = weighted_mean([sample.anchor_parts for sample in scored], weights)
    proof_success_baseline = (
        sum(float(sample.reaches_proof_graph) * sample.multiplicity for sample in group.samples) / group.sample_count
    )
    progress_baseline = scored_baseline([(sample.verified_progress, sample.multiplicity) for sample in group.samples])
    fraction_baseline = scored_baseline([(sample.verified_fraction, sample.multiplicity) for sample in group.samples])
    advantages = [
        (parts, sample.multiplicity)
        for sample in group.samples
        for tactic in sample.tactics
        if (parts := tactic_advantage(tactic, first_tactic_baseline)) is not None
    ]
    return GroupAdvantages(
        baseline=None if baseline is None else baseline.total,
        first_tactic_baseline=None if first_tactic_baseline is None else first_tactic_baseline.total,
        proof_success_baseline=proof_success_baseline,
        samples=tuple(
            sample_advantages(
                sample, baseline, first_tactic_baseline, proof_success_baseline, progress_baseline, fraction_baseline
            )
            for sample in group.samples
        ),
        global_magnitude=sum(abs(parts.global_part) * weight for parts, weight in advantages),
        local_magnitude=sum(abs(parts.local_part) * weight for parts, weight in advantages),
    )


def local_share_of_advantages(groups: Sequence[GroupAdvantages]) -> float:
    """The fraction of the summed |tactic advantage| that comes from the local term."""
    local = sum(group.local_magnitude for group in groups)
    total = local + sum(group.global_magnitude for group in groups)
    return local / total if total else 0.0
