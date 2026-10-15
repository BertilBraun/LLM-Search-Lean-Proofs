import math

import pytest

torch = pytest.importorskip("torch")

from lean_search.training.dpo import (  # noqa: E402
    SequenceLogProbabilities,
    dpo_losses,
    dpo_metrics,
    pair_batch,
    plan_item_steps,
    plan_pair_steps,
    sequence_log_probabilities,
)
from lean_search.training.dpo_data import (  # noqa: E402
    PreferencePair,
    TokenizedPair,
    deduplicate_pairs,
    fits,
    read_pairs,
    tokenize_pair,
    write_pairs,
)
from lean_search.training.sft import OptimizationConfig  # noqa: E402
from lean_search.training.sft_data import IGNORE_INDEX, SftExample, TokenizedExample  # noqa: E402

GOALS = ("x : ℕ\n⊢ x + 0 = x",)


class CharacterTokenizer:
    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + "<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def scores(chosen: list[float], rejected: list[float]) -> SequenceLogProbabilities:
    return SequenceLogProbabilities(torch.tensor(chosen), torch.tensor(rejected))


def pair(chosen: str = "simp", rejected: str = "exact foo") -> PreferencePair:
    return PreferencePair("expert_iteration", "round_0/p", 0, GOALS, chosen, rejected, "error")


def tokenized(prompt_tokens: int, chosen_tokens: int, rejected_tokens: int, number: int = 0) -> TokenizedPair:
    example = SftExample("s", f"p{number}", 0, GOALS, "simp")
    return TokenizedPair(
        pair(),
        TokenizedExample(example, (1,) * (prompt_tokens + chosen_tokens), prompt_tokens),
        TokenizedExample(example, (2,) * (prompt_tokens + rejected_tokens), prompt_tokens),
    )


def test_the_loss_is_log_two_while_the_policy_equals_the_reference() -> None:
    same = scores([-3.0, -1.0], [-2.0, -5.0])
    assert torch.allclose(dpo_losses(same, same, beta=0.1).losses, torch.full((2,), math.log(2)))


def test_raising_the_chosen_log_probability_lowers_the_loss() -> None:
    reference = scores([-3.0], [-2.0])
    assert dpo_losses(scores([-1.0], [-2.0]), reference, beta=0.1).losses.item() < math.log(2)


def test_rewards_are_beta_times_the_log_ratio_to_the_reference() -> None:
    losses = dpo_losses(scores([-1.0], [-4.0]), scores([-3.0], [-2.0]), beta=0.5)
    assert (losses.chosen_rewards.item(), losses.rejected_rewards.item()) == (1.0, -1.0)


def test_the_loss_is_the_logistic_loss_of_the_reward_margin() -> None:
    losses = dpo_losses(scores([-1.0], [-4.0]), scores([-3.0], [-2.0]), beta=0.5)
    assert losses.losses.item() == pytest.approx(math.log1p(math.exp(-2.0)))


def test_reward_accuracy_counts_pairs_with_a_positive_margin() -> None:
    metrics = dpo_metrics(scores([-1.0, -5.0], [-2.0, -2.0]), scores([-2.0, -2.0], [-2.0, -2.0]), beta=0.1)
    assert metrics.reward_accuracy == 0.5


def test_chosen_preferred_compares_the_policy_log_probabilities_alone() -> None:
    metrics = dpo_metrics(scores([-1.0, -5.0], [-2.0, -2.0]), scores([0.0, 0.0], [0.0, 0.0]), beta=0.1)
    assert metrics.chosen_preferred == 0.5


def test_sequence_log_probabilities_sum_the_tokens_of_each_row() -> None:
    token_losses = torch.tensor([0.5, 1.0, 2.0, 0.25])
    rows = torch.tensor([0, 0, 2, 2])
    assert sequence_log_probabilities(token_losses, rows, 3).tolist() == [-1.5, 0.0, -2.25]


def test_pair_batches_hold_the_chosen_rows_before_the_rejected_rows() -> None:
    first, second = tokenized(3, 2, 4, 0), tokenized(3, 1, 1, 1)
    batch = pair_batch([first, second], pad_token_id=0, device=torch.device("cpu"))
    assert batch.input_ids[:, 0].tolist() == [1, 1, 2, 2]


def test_pair_batches_train_only_on_completions() -> None:
    batch = pair_batch([tokenized(3, 2, 2)], pad_token_id=0, device=torch.device("cpu"))
    assert batch.labels[0].tolist() == [IGNORE_INDEX] * 3 + [1, 1]


def test_each_epoch_visits_every_pair_once() -> None:
    pairs = [tokenized(10, number % 5 + 1, 3, number) for number in range(40)]
    config = OptimizationConfig(epochs=2, micro_batch_tokens=64, micro_batches_per_step=1, length_group_examples=8)
    steps = plan_pair_steps(pairs, config)
    assert sorted(index for step in steps for batch in step.micro_batches for index in batch) == sorted(
        list(range(40)) * 2
    )


def test_micro_batches_respect_the_padded_token_budget() -> None:
    pairs = [tokenized(10, number % 7 + 1, 4, number) for number in range(40)]
    config = OptimizationConfig(micro_batch_tokens=100, micro_batches_per_step=1, length_group_examples=40)
    steps = plan_pair_steps(pairs, config)
    widest = max(
        len(batch) * max(pairs[index].padded_length for index in batch)
        for step in steps
        for batch in step.micro_batches
    )
    assert widest <= 100


def test_chosen_and_rejected_share_the_prompt() -> None:
    tokenized_pair = tokenize_pair(CharacterTokenizer(), pair())
    prompt = tokenized_pair.chosen.prompt_token_count
    assert tokenized_pair.chosen.input_ids[:prompt] == tokenized_pair.rejected.input_ids[:prompt]


def test_pairs_over_the_completion_cap_do_not_fit() -> None:
    tokenized_pair = tokenize_pair(CharacterTokenizer(), pair(rejected="nlinarith [" + "sq_nonneg x, " * 20 + "]"))
    assert not fits(tokenized_pair, max_prompt_tokens=2048, max_completion_tokens=64)


def test_identical_pairs_are_kept_once() -> None:
    assert deduplicate_pairs([pair(), pair(), pair(rejected="other")]) == [pair(), pair(rejected="other")]


def test_pairs_round_trip_through_json_lines(tmp_path) -> None:
    path = tmp_path / "pairs.jsonl"
    write_pairs(path, [pair(), pair(rejected="other")])
    assert list(read_pairs(path)) == [pair(), pair(rejected="other")]


def chosen_only(prompt_tokens: int, chosen_tokens: int, number: int = 0) -> TokenizedPair:
    example = SftExample("s", f"p{number}", 0, GOALS, "simp")
    return TokenizedPair(
        pair(rejected=None), TokenizedExample(example, (3,) * (prompt_tokens + chosen_tokens), prompt_tokens), None
    )


def test_chosen_only_items_add_no_rejected_row() -> None:
    batch = pair_batch([tokenized(3, 2, 2), chosen_only(3, 1)], pad_token_id=0, device=torch.device("cpu"))
    assert batch.input_ids[:, 0].tolist() == [1, 3, 2]


def test_steps_count_the_pairs_among_their_items() -> None:
    items = [tokenized(5, 2, 2, 0), chosen_only(5, 2, 1), chosen_only(5, 2, 2)]
    config = OptimizationConfig(micro_batch_tokens=1000, micro_batches_per_step=1, length_group_examples=10)
    (step,) = plan_pair_steps(items, config)
    assert (step.items, step.pairs) == (3, 1)


def test_metrics_without_pairs_are_empty() -> None:
    assert dpo_metrics(scores([], []), scores([], []), beta=0.1).pairs == 0


def test_a_chosen_only_item_tokenizes_without_a_rejected_completion() -> None:
    assert tokenize_pair(CharacterTokenizer(), pair(rejected=None)).rejected is None


def visible_pair() -> PreferencePair:
    return PreferencePair(
        "expert_iteration", "round_0/p", 0, GOALS, "simp", "exact foo", "error", "Both sides agree.", "Try foo."
    )


def test_a_visible_pair_renders_its_explanation_before_the_block() -> None:
    tokenized = tokenize_pair(CharacterTokenizer(), visible_pair(), visible=True)
    completion = "".join(chr(token) for token in tokenized.chosen.input_ids[tokenized.chosen.prompt_token_count :])
    assert completion.startswith("Both sides agree.\n\n```lean\nsimp")


def test_a_visible_pair_renders_without_thinking() -> None:
    tokenized = tokenize_pair(CharacterTokenizer(), visible_pair(), visible=True)
    prompt = "".join(chr(token) for token in tokenized.chosen.input_ids[: tokenized.chosen.prompt_token_count])
    assert "briefly explain" in prompt


def test_a_chosen_only_item_differs_from_a_pair_in_deduplication() -> None:
    assert len(deduplicate_pairs([pair(), pair(rejected=None)])) == 2


def test_item_steps_hold_the_requested_number_of_items() -> None:
    items = [tokenized(5, number % 3 + 1, 2, number) for number in range(10)]
    config = OptimizationConfig(micro_batch_tokens=30, epochs=1)
    steps = plan_item_steps(items, config, batch_items=4)
    assert [step.items for step in steps] == [4, 4]


def test_packed_pair_batches_hold_every_sequence_in_one_row() -> None:
    batch = pair_batch([tokenized(3, 2, 2), chosen_only(3, 1)], 0, torch.device("cpu"), packing=True)
    assert batch.sequence_starts == (0, 5, 9, 14)


def test_packed_pair_batches_list_the_chosen_sequences_before_the_rejected_ones() -> None:
    batch = pair_batch([tokenized(3, 2, 2), chosen_only(3, 1)], 0, torch.device("cpu"), packing=True)
    assert [batch.input_ids[0, start].item() for start in batch.sequence_starts[:-1]] == [1, 3, 2]


def test_packed_item_steps_fill_micro_batches_up_to_the_real_token_budget() -> None:
    items = [tokenized(5, 2, 2, number) for number in range(8)]
    config = OptimizationConfig(micro_batch_tokens=30, epochs=1, packing=True)
    (step,) = plan_item_steps(items, config, batch_items=8)
    assert [len(batch) for batch in step.micro_batches] == [2, 2, 2, 2]


def test_item_steps_split_into_micro_batches_within_the_token_budget() -> None:
    items = [tokenized(5, 2, 2, number) for number in range(8)]
    (step,) = plan_item_steps(items, OptimizationConfig(micro_batch_tokens=30, epochs=1), batch_items=8)
    assert max(len(batch) for batch in step.micro_batches) * items[0].padded_length <= 30
