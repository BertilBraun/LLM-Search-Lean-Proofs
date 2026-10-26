from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from rl_samples import DENSE, components, group, sample

from lean_search.policy.prompts import END_OF_TURN
from lean_search.rl.advantages import AdvantageConfig, group_advantages
from lean_search.rl.grpo_groups import RewardComponents
from lean_search.rl.policy_data import (
    ExpansionTexts,
    GroupWeightConfig,
    PolicyData,
    SampledCompletion,
    build_policy_data,
    group_weight,
    read_expansion_texts,
    write_expansion_texts,
)
from lean_search.rl.token_credit import CharacterSpan, CreditMode

WEIGHTS = GroupWeightConfig(global_signal_weight=1.0, local_only_weight=0.25)


class CharacterTokenizer:
    pad_token_id = 0

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        return "".join(f"<{turn['role']}>{turn['content']}" for turn in conversation) + "<assistant>"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]:
        return {
            "input_ids": [ord(character) for character in text],
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


def completion(edge_id: int, block: str, ended_turn: bool = True) -> SampledCompletion:
    text = f"Idea.\n\n```lean\n{block}\n```"
    tactics = []
    position = text.index(block)
    for line in block.split("\n"):
        tactics.append(CharacterSpan(position, position + len(line)))
        position += len(line) + 1
    return SampledCompletion(edge_id, text, tuple(tactics), ended_turn)


def policy_data(max_completion_tokens: int = 1000) -> PolicyData:
    mixed = group(
        sample("good", components(global_value=1.0), edge_id=0),
        sample("bad\nworse", components(failure=-1.0), first_failing_tactic=0, reached=False, edge_id=1),
        node_id=0,
    )
    identical = group(sample("a", components(), edge_id=2), sample("b", components(), edge_id=3), node_id=1)
    texts = [
        ExpansionTexts("p", 0, "prompt", (completion(0, "good"), completion(0, "good"), completion(1, "bad\nworse"))),
        ExpansionTexts("p", 1, "prompt", (completion(2, "a"), completion(3, "b"))),
    ]
    return build_policy_data(
        [mixed, identical],
        texts,
        CharacterTokenizer(),
        DENSE,
        AdvantageConfig(),
        CreditMode.PER_TOKEN,
        WEIGHTS,
        max_prompt_tokens=100,
        max_completion_tokens=max_completion_tokens,
    )


def test_every_recorded_completion_of_a_trained_group_is_a_sequence() -> None:
    assert [sequence.edge_id for sequence in policy_data().sequences] == [0, 0, 1]


def test_groups_with_identical_rewards_are_dropped() -> None:
    assert {sequence.node_id for sequence in policy_data().sequences} == {0}


def test_completion_ends_with_the_end_of_turn() -> None:
    sequence = policy_data().sequences[0]
    tail = sequence.tokenized.input_ids[-len(END_OF_TURN) :]
    assert "".join(chr(token) for token in tail) == END_OF_TURN


def test_one_advantage_and_mask_entry_per_completion_token() -> None:
    sequence = policy_data().sequences[2]
    counts = {len(sequence.advantages), len(sequence.trained)}
    assert counts == {sequence.tokenized.completion_token_count}


def test_tokens_after_the_failing_tactic_are_counted_as_masked() -> None:
    sequence = policy_data().sequences[2]
    assert sequence.masked_tokens == len("\nworse\n```" + END_OF_TURN)


def test_sequences_over_the_length_cap_are_counted_and_dropped() -> None:
    assert policy_data(max_completion_tokens=10).metrics.sequences_over_length == 3


def test_mixed_reward_share() -> None:
    assert policy_data().metrics.mixed_reward_share == 0.5


@pytest.mark.parametrize(
    ("second", "weight"),
    [(components(global_value=1.0), 1.0), (components(failure=-1.0), 0.25), (components(), 0.0)],
    ids=["global signal", "local only", "identical"],
)
def test_group_weight(second: RewardComponents, weight: float) -> None:
    advantages = group_advantages(group(sample("a", components()), sample("b", second)), DENSE, AdvantageConfig())
    assert group_weight(advantages, WEIGHTS) == weight


def test_expansion_texts_round_trip(tmp_path: Path) -> None:
    texts = [ExpansionTexts("p", 3, "prompt", (completion(5, "simp"),))]
    write_expansion_texts(tmp_path / "texts.jsonl", texts)
    assert list(read_expansion_texts(tmp_path / "texts.jsonl")) == texts
