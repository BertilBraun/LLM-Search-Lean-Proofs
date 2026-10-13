from collections import Counter

import pytest
from reasoning_records import GOALS, proof_steps

from lean_search.corpora.records import DataSplit
from lean_search.reasoning.states import (
    StateSelectionConfig,
    goal_key,
    goals_digest,
    proof_states,
    round_robin,
    select_states,
    without_seen_states,
)


def test_states_carry_the_goals_after_every_later_step() -> None:
    states = proof_states(proof_steps())
    assert [state.later_goals for state in states] == [(GOALS[2], GOALS[3]), (GOALS[3],), ()]


def test_reference_goal_keys_start_with_the_next_state() -> None:
    assert proof_states(proof_steps())[0].reference_goal_keys == (goal_key(GOALS[1]), goal_key(GOALS[2]), ())


def test_goal_keys_ignore_whitespace_differences() -> None:
    assert goal_key(("a  b : ℕ\n\n⊢  a = b ",)) == goal_key(("a b : ℕ\n⊢ a = b",))


def test_states_out_of_step_order_get_the_same_later_goals() -> None:
    assert proof_states(list(reversed(proof_steps())))[0].later_goals == (GOALS[2], GOALS[3])


def test_round_robin_interleaves_while_every_sequence_lasts() -> None:
    assert round_robin([[1, 2, 3], [10], [20, 21]]) == [1, 10, 20, 2, 21, 3]


def many_proofs(source: str, count: int, split: DataSplit = DataSplit.TRAIN) -> list:
    return [step for number in range(count) for step in proof_steps(source, f"{source}/{number}", split)]


def test_only_train_split_states_are_selected() -> None:
    steps = many_proofs("a", 3) + many_proofs("b", 3, DataSplit.VALIDATION)
    assert {state.source for state in select_states(steps, StateSelectionConfig(count=100))} == {"a"}


def test_at_most_states_per_proof_are_selected() -> None:
    states = select_states(many_proofs("a", 4), StateSelectionConfig(count=100, states_per_proof=2))
    assert max(Counter(state.step.proof_identifier for state in states).values()) == 2


def test_sources_get_equal_shares_while_they_last() -> None:
    steps = many_proofs("large", 20) + many_proofs("small", 20)
    states = select_states(steps, StateSelectionConfig(count=10, states_per_proof=1))
    assert Counter(state.source for state in states) == {"large": 5, "small": 5}


def test_seen_states_are_marked() -> None:
    seen = frozenset({goals_digest(GOALS[index]) for index in range(3)})
    states = select_states(many_proofs("a", 2), StateSelectionConfig(count=10), seen)
    assert all(state.seen_in_sft for state in states)


def test_excluded_identifiers_are_skipped() -> None:
    excluded = frozenset({"a/0#0", "a/0#1", "a/0#2"})
    states = select_states(many_proofs("a", 2), StateSelectionConfig(count=10), excluded_identifiers=excluded)
    assert {state.step.proof_identifier for state in states} == {"a/1"}


@pytest.mark.parametrize("seed", ["one", "two"])
def test_selection_is_deterministic(seed: str) -> None:
    config = StateSelectionConfig(count=6, seed=seed)
    steps = many_proofs("a", 10)
    assert select_states(steps, config) == select_states(list(reversed(steps)), config)


def test_the_validation_split_can_be_selected() -> None:
    steps = many_proofs("a", 3) + many_proofs("b", 3, DataSplit.VALIDATION)
    config = StateSelectionConfig(count=100, split=DataSplit.VALIDATION)
    assert {state.source for state in select_states(steps, config)} == {"b"}


def test_sources_can_be_restricted() -> None:
    steps = many_proofs("a", 3) + many_proofs("b", 3) + many_proofs("c", 3)
    config = StateSelectionConfig(count=100, sources=("a", "c"))
    assert {state.source for state in select_states(steps, config)} == {"a", "c"}


def test_unseen_only_skips_states_seen_in_sft() -> None:
    seen = frozenset({goals_digest(GOALS[0])})
    states = select_states(many_proofs("a", 4), StateSelectionConfig(count=100, unseen_only=True), seen)
    assert {state.step.step_index for state in states} <= {1, 2}


def test_states_seen_by_a_later_sft_data_set_can_be_dropped() -> None:
    states = select_states(many_proofs("a", 4), StateSelectionConfig(count=100))
    remaining = without_seen_states(states, frozenset({goals_digest(GOALS[0])}))
    assert {state.step.step_index for state in remaining} == {state.step.step_index for state in states} - {0}
