from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from rl_samples import FAILING, MASKED, PROOF_GRAPH, UNKNOWN, group, sample

from lean_search.policy.prompts import END_OF_TURN
from lean_search.rl.advantages import CreditMode
from lean_search.rl.policy_data import (
    ExpansionTexts,
    PolicyData,
    PolicyDataConfig,
    SampledCompletion,
    build_policy_data,
    read_expansion_texts,
    write_expansion_texts,
)
from lean_search.rl.token_credit import CharacterSpan
from lean_search.search.texts import InsertedSpan, SampledTokens, TokenSpan


class CharacterTokenizer:
    pad_token_id = 0

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        return "".join(f"<{turn['role']}>{turn['content']}" for turn in conversation) + "<assistant>"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(chr(token) for token in token_ids)

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]:
        return {
            "input_ids": [ord(character) for character in text],
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


def completion(edge_id: int, block: str, *, recorded: bool = True, explanation: str = "Idea.") -> SampledCompletion:
    """With `recorded` the sample's token ids and log-probabilities, one token per character, as the search keeps."""
    text = f"{explanation}\n\n```lean\n{block}\n```"
    tactics = []
    position = text.index(block)
    for line in block.split("\n"):
        tactics.append(CharacterSpan(position, position + len(line)))
        position += len(line) + 1
    if not recorded:
        return SampledCompletion(edge_id, text, tuple(tactics))
    sampled = text + END_OF_TURN
    tokens = SampledTokens(tuple(ord(character) for character in sampled), tuple(-0.5 for _ in sampled))
    return SampledCompletion(edge_id, text, tuple(tactics), tokens=tokens)


def forced_completion(edge_id: int, block: str) -> SampledCompletion:
    """The opening inserted after the cut-off explanation, as budget forcing records it."""
    base = completion(edge_id, block)
    opening = base.text.index("\n\n```lean\n")
    span = InsertedSpan(CharacterSpan(opening, opening + 10), TokenSpan(opening, opening + 10))
    log_probabilities = tuple(
        None if opening <= index < opening + 10 else value for index, value in enumerate(base.tokens.log_probabilities)
    )
    return SampledCompletion(
        edge_id, base.text, base.tactic_spans, tokens=SampledTokens(base.tokens.token_ids, log_probabilities, (span,))
    )


def policy_data(
    *, recorded: bool = True, credit: CreditMode = CreditMode.PER_TACTIC, explanation: str = "Idea."
) -> PolicyData:
    trained = group(sample("good", PROOF_GRAPH, edge_id=0), sample("bad\nworse", FAILING, MASKED, edge_id=1), node_id=0)
    identical = group(sample("a", PROOF_GRAPH, edge_id=2), sample("b", PROOF_GRAPH, edge_id=3), node_id=1)
    texts = [
        ExpansionTexts(
            "p",
            0,
            "prompt",
            (
                completion(0, "good", recorded=recorded, explanation=explanation),
                completion(0, "good", recorded=recorded),
                completion(1, "bad\nworse", recorded=recorded),
            ),
            temperature=0.7,
        ),
        ExpansionTexts("p", 1, "prompt", (completion(2, "a"), completion(3, "b"))),
    ]
    return build_policy_data([trained, identical], texts, CharacterTokenizer(), PolicyDataConfig(credit))


def test_every_recorded_completion_of_a_trained_group_is_a_sequence() -> None:
    assert [sequence.edge_id for sequence in policy_data().sequences] == [0, 0, 1]


def test_groups_without_a_non_zero_advantage_are_dropped() -> None:
    assert {sequence.node_id for sequence in policy_data().sequences} == {0}


def test_sequences_train_on_the_recorded_token_ids() -> None:
    sequence = policy_data().sequences[2]
    completion_ids = sequence.tokenized.input_ids[sequence.tokenized.prompt_token_count :]
    assert completion_ids == completion(1, "bad\nworse").tokens.token_ids


def test_prompt_is_the_recorded_prompt() -> None:
    sequence = policy_data().sequences[0]
    assert sequence.tokenized.input_ids[: sequence.tokenized.prompt_token_count] == tuple(map(ord, "prompt"))


def test_temperature_comes_from_the_expansion() -> None:
    assert policy_data().sequences[0].temperature == 0.7


def test_sampler_log_probabilities_are_kept() -> None:
    assert set(policy_data().sequences[0].sampler_log_probabilities) == {-0.5}


def test_one_advantage_and_mask_entry_per_completion_token() -> None:
    sequence = policy_data().sequences[2]
    assert {len(sequence.advantages), len(sequence.trained)} == {sequence.tokenized.completion_token_count}


def test_tokens_after_the_failing_tactic_are_not_trained() -> None:
    sequence = policy_data().sequences[2]
    assert sum(not trained for trained in sequence.trained) == len("\nworse\n```" + END_OF_TURN)


def test_long_completions_are_kept() -> None:
    assert len(policy_data(explanation="Thinking. " * 400).sequences) == 3


def test_records_without_tokens_are_tokenized_again() -> None:
    assert policy_data(recorded=False).metrics.retokenized_sequences == 3


def test_sequence_credit_trains_every_token_of_a_failed_sample() -> None:
    assert all(policy_data(credit=CreditMode.SEQUENCE).sequences[2].trained)


def test_tactic_counts_of_the_trained_groups() -> None:
    tactics = policy_data().metrics.tactics
    assert (tactics.proof_graph, tactics.failing, tactics.masked) == (1, 1, 1)


def test_forced_answers_are_kept_with_the_inserted_opening_untrained() -> None:
    group_with_forced = group(sample("good", PROOF_GRAPH, edge_id=0), sample("other", FAILING, edge_id=1))
    texts = [ExpansionTexts("p", 0, "prompt", (forced_completion(0, "good"), completion(1, "other")))]
    data = build_policy_data([group_with_forced], texts, CharacterTokenizer(), PolicyDataConfig())
    forced = data.sequences[0]
    assert (data.metrics.forced_sequences, sum(not trained for trained in forced.trained)) == (1, 10)


def test_tokens_that_do_not_decode_to_the_text_fall_back_to_sequence_credit() -> None:
    broken = completion(0, "good")
    broken = SampledCompletion(0, broken.text, broken.tactic_spans, tokens=SampledTokens((ord("x"),), (-0.5,)))
    texts = [ExpansionTexts("p", 0, "prompt", (broken, completion(1, "bad")))]
    data = build_policy_data(
        [group(sample("good", PROOF_GRAPH, edge_id=0), sample("bad", FAILING, edge_id=1))],
        texts,
        CharacterTokenizer(),
        PolicyDataConfig(),
    )
    assert data.metrics.token_mismatch_sequences == 1


def test_unknown_only_sample_is_not_trained() -> None:
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "a"), completion(1, "b"), completion(2, "c")))]
    groups = [
        group(sample("a", PROOF_GRAPH, edge_id=0), sample("b", FAILING, edge_id=1), sample("c", UNKNOWN, edge_id=2))
    ]
    data = build_policy_data(groups, texts, CharacterTokenizer(), PolicyDataConfig())
    assert not any(data.sequences[2].trained)


def test_expansion_texts_round_trip(tmp_path: Path) -> None:
    texts = [ExpansionTexts("p", 3, "prompt", (completion(5, "simp"),), temperature=0.8, top_p=1.0)]
    write_expansion_texts(tmp_path / "texts.jsonl", texts)
    assert list(read_expansion_texts(tmp_path / "texts.jsonl")) == texts


@pytest.mark.parametrize("credit", list(CreditMode))
def test_inserted_tokens_are_untrained_in_every_credit_mode(credit: CreditMode) -> None:
    group_with_forced = group(sample("good", PROOF_GRAPH, edge_id=0), sample("other", FAILING, edge_id=1))
    texts = [ExpansionTexts("p", 0, "prompt", (forced_completion(0, "good"), completion(1, "other")))]
    data = build_policy_data([group_with_forced], texts, CharacterTokenizer(), PolicyDataConfig(credit))
    opening = data.sequences[0].sampler_log_probabilities.index(None)
    assert not any(data.sequences[0].trained[opening : opening + 10])
