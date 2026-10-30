from test_prompt_groups import add_sample, feedback_tree, record_of, root_tree

from lean_search.rl.search_option_analysis import (
    ErrorMix,
    error_mix,
    feedback_triggers,
    shares,
    trigger_rows,
)
from lean_search.rl.search_variants import ErrorCounts, SampleOutcomes


def test_error_mix_counts_every_policy_sample() -> None:
    assert error_mix(feedback_tree()).outcomes == SampleOutcomes(new_state=1, existing_state=1, lean_error=3)


def test_error_mix_sorts_the_errors() -> None:
    assert error_mix(feedback_tree()).errors == ErrorCounts(unknown_identifier=1, linarith=2)


def test_shares_are_of_the_samples() -> None:
    mix = ErrorMix(1, SampleOutcomes(new_state=1, lean_error=3), ErrorCounts(linarith=3))
    assert shares(mix)["linarith"] == 0.75


def test_expansion_without_new_states_fires_at_every_threshold() -> None:
    tree = root_tree()
    add_sample(tree, "linarith", False)
    assert feedback_triggers(record_of(tree)).fires == (1, 1, 1)


def test_one_new_state_fires_only_above_one() -> None:
    tree = root_tree()
    add_sample(tree, "simp", True)
    add_sample(tree, "linarith", False)
    assert feedback_triggers(record_of(tree)).fires == (0, 1, 1)


def test_the_feedback_round_s_own_samples_are_left_out() -> None:
    assert feedback_triggers(feedback_tree()).expansions == 1


def test_extra_tokens_are_the_round_s_samples_at_the_expansion_s_rate() -> None:
    tree = root_tree()
    add_sample(tree, "linarith", False)
    add_sample(tree, "omega", False)
    tree.root.expansion_generated_tokens = 200
    rows = trigger_rows(feedback_triggers(record_of(tree)), 4)
    assert rows[0].extra_token_share == 2.0
