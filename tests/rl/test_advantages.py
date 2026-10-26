import dataclasses

import pytest
from rl_samples import DENSE, components, group, sample

from lean_search.rl.advantages import (
    AdvantageConfig,
    AdvantageScale,
    group_advantages,
    local_share_of_advantages,
    mixed_reward,
)
from lean_search.rl.grpo_groups import RewardComponents, RewardMode

CONFIG = AdvantageConfig(local_share=0.15)
OUTCOME = dataclasses.replace(DENSE, mode=RewardMode.OUTCOME_ONLY)


def test_mixed_reward_weighs_global_and_local_terms() -> None:
    assert mixed_reward(components(shaping=0.2, global_value=1.0), 0.15).total == pytest.approx(0.85 + 0.15 * 0.2)


def test_local_term_is_clipped_to_minus_one() -> None:
    assert mixed_reward(components(failure=-1.0, shaping=-0.3), 0.15).local == -1.0


def test_advantages_are_centred_on_the_sample_weighted_mean() -> None:
    advantages = group_advantages(
        group(
            sample("a", components(global_value=1.0), multiplicity=3),
            sample("b", components(failure=-1.0), reached=False, first_failing_tactic=0),
        ),
        DENSE,
        CONFIG,
    )
    assert 3 * advantages.advantages[0].overall + advantages.advantages[1].overall == pytest.approx(0.0)


def test_local_only_group_keeps_advantages_proportional_to_the_local_share() -> None:
    advantages = group_advantages(
        group(sample("a", components()), sample("b", components(failure=-1.0), reached=False, first_failing_tactic=0)),
        DENSE,
        CONFIG,
    )
    assert advantages.advantages[0].overall == pytest.approx(0.075)


def test_standard_deviation_scale_normalizes_a_local_only_group() -> None:
    config = dataclasses.replace(CONFIG, scale=AdvantageScale.STANDARD_DEVIATION, standard_deviation_floor=0.0)
    advantages = group_advantages(
        group(sample("a", components()), sample("b", components(failure=-1.0), reached=False, first_failing_tactic=0)),
        DENSE,
        config,
    )
    assert advantages.advantages[0].overall == pytest.approx(1.0)


def test_overall_advantage_is_prefix_plus_error_for_a_partial_block() -> None:
    partial = sample("p", components(failure=-1.0, shaping=0.3, global_value=1.0), first_failing_tactic=1)
    advantages = group_advantages(group(partial, sample("q", components())), DENSE, CONFIG).advantages[0]
    assert advantages.overall == pytest.approx(advantages.prefix + advantages.error)


def test_error_advantage_is_the_failure_penalty_after_a_valid_prefix() -> None:
    partial = sample("p", components(failure=-1.0, shaping=0.3, global_value=1.0), first_failing_tactic=1)
    advantages = group_advantages(group(partial, sample("q", components())), DENSE, CONFIG).advantages[0]
    assert advantages.error == pytest.approx(0.15 * (-0.7 - 0.3))


def test_error_advantage_without_a_prefix_is_the_overall_advantage() -> None:
    failed = sample("f", components(failure=-1.0), reached=False, first_failing_tactic=0)
    advantages = group_advantages(group(failed, sample("q", components())), DENSE, CONFIG).advantages[0]
    assert advantages.error == advantages.overall


def test_outcome_only_prefix_gets_the_global_value_of_the_state_reached() -> None:
    partial = sample("p", components(), first_failing_tactic=1, config=OUTCOME)
    partial = dataclasses.replace(partial, credit=dataclasses.replace(partial.credit, prefix_reward=1.0))
    advantages = group_advantages(group(partial, sample("q", components(), config=OUTCOME)), OUTCOME, CONFIG)
    assert advantages.advantages[0].prefix == pytest.approx(0.85 * 1.0)


@pytest.mark.parametrize(
    ("second", "share"),
    [(components(failure=-1.0), 1.0), (components(global_value=1.0), 0.0)],
    ids=["local only", "global only"],
)
def test_local_share_of_advantages(second: RewardComponents, share: float) -> None:
    advantages = group_advantages(group(sample("a", components()), sample("b", second)), DENSE, CONFIG)
    assert local_share_of_advantages([advantages]) == pytest.approx(share)


def test_group_without_reward_spread_has_no_mixed_rewards() -> None:
    advantages = group_advantages(group(sample("a", components()), sample("b", components())), DENSE, CONFIG)
    assert not advantages.has_mixed_rewards
