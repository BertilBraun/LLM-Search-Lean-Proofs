import pytest
from reasoning_records import execution, sample_record, state_record

from lean_search.reasoning.dataset import (
    SelectionConfig,
    reasoning_example,
    select_samples,
    with_thinking_instruction,
)
from lean_search.reasoning.reward import RewardConfig, StepOutcome

REWARD = RewardConfig()
SELECTION = SelectionConfig(max_per_state=2, min_reasoning_tokens=16)
SUCCESSFUL = {
    "subst h₀": execution("subst h₀", StepOutcome.REFERENCE, 1),
    "omega": execution("omega", StepOutcome.CLOSED),
}
FAILING = {"simp": execution("simp", StepOutcome.ERROR), "skip": execution("skip", StepOutcome.NO_PROGRESS)}


def selected_indices(samples: list, selection: SelectionConfig = SELECTION, reward: RewardConfig = REWARD) -> list[int]:
    record = state_record(samples, [*SUCCESSFUL.values(), *FAILING.values()])
    return [sample.index for sample in select_samples(record, reward, selection)]


def test_shortest_successful_reasoning_comes_first() -> None:
    samples = [sample_record(0, "omega", 300), sample_record(1, "subst h₀", 50), sample_record(2, "omega", 20)]
    assert selected_indices(samples) == [2, 1]


def test_at_most_max_per_state_samples_are_kept() -> None:
    samples = [sample_record(index, "omega", 20 + index, reasoning=f"Reason {index}.") for index in range(5)]
    assert len(selected_indices(samples, SelectionConfig(max_per_state=3))) == 3


def test_distinct_blocks_come_before_shorter_repeats() -> None:
    samples = [sample_record(0, "omega", 20), sample_record(1, "omega", 25), sample_record(2, "subst h₀", 90)]
    assert selected_indices(samples) == [0, 2]


def test_repeats_fill_the_remaining_places() -> None:
    samples = [sample_record(0, "omega", 20), sample_record(1, "omega", 25)]
    assert selected_indices(samples) == [0, 1]


def test_failed_samples_are_never_selected() -> None:
    samples = [
        sample_record(0, "simp", 20),
        sample_record(1, "skip", 20),
        sample_record(2, None, 500, parse_failure=StepOutcome.TRUNCATED),
    ]
    assert selected_indices(samples) == []


def test_reasoning_below_the_minimum_is_not_selected() -> None:
    samples = [sample_record(0, "omega", 3, reasoning="ok"), sample_record(1, "omega", 40)]
    assert selected_indices(samples) == [1]


def test_reasoning_above_the_maximum_is_not_selected() -> None:
    samples = [sample_record(0, "omega", 400), sample_record(1, "omega", 40)]
    assert selected_indices(samples, SelectionConfig(max_reasoning_tokens=256)) == [1]


def test_reasoning_with_a_think_tag_is_not_selected() -> None:
    samples = [sample_record(0, "omega", 40, reasoning="first</think>second")]
    assert selected_indices(samples) == []


def test_later_reference_states_follow_the_reward_config() -> None:
    record = state_record(
        [sample_record(0, "subst h₀\nsubst h₁", 40)], [execution("subst h₀\nsubst h₁", StepOutcome.REFERENCE, 2)]
    )
    assert select_samples(record, RewardConfig(accept_later_reference_states=False), SELECTION) == []


def test_examples_keep_the_instruction_their_reasoning_was_sampled_with() -> None:
    record = state_record([sample_record(0, "omega", 40)], [SUCCESSFUL["omega"]], thinking_instruction="Be brief.")
    (sample,) = select_samples(record, REWARD, SELECTION)
    assert reasoning_example(record.sampled, sample).thinking_instruction == "Be brief."


@pytest.mark.parametrize(("instruction", "expected"), [(None, "Be brief."), ("", ""), ("Think.", "Think.")])
def test_the_data_config_can_replace_the_sampling_instruction(instruction: str | None, expected: str) -> None:
    record = state_record([sample_record(0, "omega", 40)], [SUCCESSFUL["omega"]], thinking_instruction="Be brief.")
    (sample,) = select_samples(record, REWARD, SELECTION)
    (example,) = with_thinking_instruction([reasoning_example(record.sampled, sample)], instruction)
    assert example.thinking_instruction == expected
