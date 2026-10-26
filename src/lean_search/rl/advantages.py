"""GRPO rewards mixed AlphaZero-style from the group samples' components, and their group-relative advantages."""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from lean_search.rl.grpo_groups import (
    GroupSample,
    PolicyGroup,
    RewardComponents,
    RewardConfig,
    RewardMode,
    total_reward,
)


class AdvantageScale(StrEnum):
    # Mean-centering only (Dr. GRPO): local-only groups keep advantages proportional to the local share.
    NONE = "none"
    # GRPO's division by the group's reward standard deviation.
    STANDARD_DEVIATION = "standard_deviation"


@dataclass(frozen=True)
class AdvantageConfig:
    # lambda in reward = (1 - lambda) * G + lambda * clip(L, -1, 1).
    local_share: float = 0.15
    scale: AdvantageScale = AdvantageScale.NONE
    # With STANDARD_DEVIATION: the smallest divisor, against near-identical rewards turning into large advantages.
    standard_deviation_floor: float = 0.1


@dataclass(frozen=True)
class MixedReward:
    # G in [0, 1] (slightly more for short proofs with RewardConfig.shorter_proof_bonus).
    global_value: float
    # L clipped to [-1, 1]; 0 in the outcome-only control.
    local: float
    total: float


@dataclass(frozen=True)
class SampleAdvantages:
    # (reward - group mean) / scale.
    overall: float
    # (prefix reward - group mean) / scale; None when no tactic of the block reached a state.
    prefix: float | None
    # (reward - prefix reward) / scale, the overall advantage without a prefix; None when the block ran completely.
    error: float | None


@dataclass(frozen=True)
class GroupAdvantages:
    rewards: tuple[MixedReward, ...]
    advantages: tuple[SampleAdvantages, ...]
    scale: float
    # Sample-weighted sums of |global part| and |local part| of the overall advantages.
    global_magnitude: float
    local_magnitude: float

    @property
    def has_mixed_rewards(self) -> bool:
        return len({reward.total for reward in self.rewards}) > 1

    @property
    def has_global_signal(self) -> bool:
        return len({reward.global_value for reward in self.rewards}) > 1


def mixed_reward(components: RewardComponents, local_share: float) -> MixedReward:
    local = min(1.0, max(-1.0, components.local))
    global_value = components.global_value
    return MixedReward(global_value, local, (1 - local_share) * global_value + local_share * local)


def prefix_components(sample: GroupSample, config: RewardConfig) -> RewardComponents | None:
    """The valid prefix's components: the sample's without the failure (outcome-only: G of the state reached)."""
    prefix_reward = sample.credit.prefix_reward
    if prefix_reward is None:
        return None
    if sample.credit.prefix_components is not None:
        return sample.credit.prefix_components
    match config.mode:
        case RewardMode.DENSE:
            prefix = replace(sample.components, failure=0.0)
        case RewardMode.OUTCOME_ONLY:
            prefix = RewardComponents(0.0, 0.0, 0.0, 0.0, 0.0, prefix_reward)
    assert math.isclose(total_reward(prefix, config), prefix_reward, abs_tol=1e-9), (sample.text, prefix_reward)
    return prefix


def weighted_mean(values: Sequence[float], weights: Sequence[int]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def group_advantages(group: PolicyGroup, reward_config: RewardConfig, config: AdvantageConfig) -> GroupAdvantages:
    rewards = tuple(mixed_reward(sample.components, config.local_share) for sample in group.samples)
    multiplicities = [sample.multiplicity for sample in group.samples]
    mean = weighted_mean([reward.total for reward in rewards], multiplicities)
    match config.scale:
        case AdvantageScale.NONE:
            scale = 1.0
        case AdvantageScale.STANDARD_DEVIATION:
            variance = weighted_mean([(reward.total - mean) ** 2 for reward in rewards], multiplicities)
            scale = max(math.sqrt(variance), config.standard_deviation_floor)
    global_mean = weighted_mean([reward.global_value for reward in rewards], multiplicities)
    local_mean = weighted_mean([reward.local for reward in rewards], multiplicities)
    global_parts = [abs((1 - config.local_share) * (reward.global_value - global_mean)) / scale for reward in rewards]
    local_parts = [abs(config.local_share * (reward.local - local_mean)) / scale for reward in rewards]
    return GroupAdvantages(
        rewards=rewards,
        advantages=tuple(
            sample_advantages(sample, reward, mean, scale, reward_config, config)
            for sample, reward in zip(group.samples, rewards, strict=True)
        ),
        scale=scale,
        global_magnitude=sum(part * weight for part, weight in zip(global_parts, multiplicities, strict=True)),
        local_magnitude=sum(part * weight for part, weight in zip(local_parts, multiplicities, strict=True)),
    )


def sample_advantages(
    sample: GroupSample,
    reward: MixedReward,
    mean: float,
    scale: float,
    reward_config: RewardConfig,
    config: AdvantageConfig,
) -> SampleAdvantages:
    overall = (reward.total - mean) / scale
    components = prefix_components(sample, reward_config)
    if components is None:
        prefix_total = None
        prefix = None
    else:
        prefix_total = mixed_reward(components, config.local_share).total
        prefix = (prefix_total - mean) / scale
    if sample.credit.first_failing_tactic is None:
        return SampleAdvantages(overall, prefix, None)
    error = overall if prefix_total is None else (reward.total - prefix_total) / scale
    return SampleAdvantages(overall, prefix, error)


def local_share_of_advantages(groups: Sequence[GroupAdvantages]) -> float:
    """The fraction of the summed |advantage| that comes from the local term."""
    local = sum(group.local_magnitude for group in groups)
    total = local + sum(group.global_magnitude for group in groups)
    return local / total if total else 0.0
