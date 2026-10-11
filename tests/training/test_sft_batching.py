import random

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from lean_search.training.sft import (  # noqa: E402
    CompletionLoss,
    OptimizationConfig,
    collate,
    learning_rate_factor,
    length_grouped_micro_batches,
    plan_steps,
)
from lean_search.training.sft_data import IGNORE_INDEX, SftExample, TokenizedExample  # noqa: E402

LENGTHS = [random.Random(1).randint(5, 300) for _ in range(500)]
BUDGET = 1024
CPU = torch.device("cpu")


def micro_batches(group_size: int = 64) -> list[tuple[int, ...]]:
    return length_grouped_micro_batches(LENGTHS, BUDGET, group_size, random.Random(0))


def tokenized(token_ids: tuple[int, ...], prompt_token_count: int, number: int = 0) -> TokenizedExample:
    return TokenizedExample(
        SftExample("source", f"source/0/{number}", 0, ("⊢ True",), "trivial"), token_ids, prompt_token_count
    )


def uniform_examples(count: int, length: int) -> list[TokenizedExample]:
    return [tokenized((1,) * length, length - 3, number) for number in range(count)]


def test_micro_batches_cover_every_example_once() -> None:
    assert sorted(index for batch in micro_batches() for index in batch) == list(range(len(LENGTHS)))


def test_micro_batches_stay_within_the_padded_token_budget() -> None:
    assert all(max(LENGTHS[index] for index in batch) * len(batch) <= BUDGET for batch in micro_batches())


def test_an_example_longer_than_the_budget_gets_its_own_micro_batch() -> None:
    assert (1,) in length_grouped_micro_batches([10, 5000, 10], BUDGET, 64, random.Random(0))


def test_grouping_by_length_keeps_padding_small() -> None:
    batches = micro_batches(group_size=len(LENGTHS))
    padded = sum(max(LENGTHS[index] for index in batch) * len(batch) for batch in batches)
    assert padded < 1.05 * sum(LENGTHS)


def test_a_step_counts_the_completion_tokens_of_all_its_micro_batches() -> None:
    steps = plan_steps(uniform_examples(40, 20), OptimizationConfig(micro_batch_tokens=64, micro_batches_per_step=2), 1)
    assert all(step.completion_tokens == 3 * sum(len(batch) for batch in step.micro_batches) for step in steps)


def test_each_gpu_gets_its_own_micro_batches_in_a_step() -> None:
    steps = plan_steps(uniform_examples(40, 20), OptimizationConfig(micro_batch_tokens=64, micro_batches_per_step=2), 2)
    assert {len(step.micro_batches) for step in steps} == {4}


def test_max_steps_truncates_the_plan() -> None:
    config = OptimizationConfig(micro_batch_tokens=64, micro_batches_per_step=1, max_steps=3)
    assert len(plan_steps(uniform_examples(40, 20), config, 1)) == 3


def test_epochs_repeat_the_examples() -> None:
    config = OptimizationConfig(micro_batch_tokens=60, micro_batches_per_step=1, epochs=2)
    steps = plan_steps(uniform_examples(30, 20), config, 1)
    assert sorted(index for step in steps for batch in step.micro_batches for index in batch) == sorted(
        [*range(30), *range(30)]
    )


@pytest.mark.parametrize(
    ("step", "expected"),
    [(0, 0.1), (9, 1.0), (10, 1.0), (60, 0.55), (110, 0.1)],
)
def test_learning_rate_warms_up_linearly_then_follows_a_cosine_to_the_minimum(step: int, expected: float) -> None:
    assert learning_rate_factor(step, warmup_steps=10, total_steps=110, minimum_ratio=0.1) == pytest.approx(expected)


BATCH = collate([tokenized((5, 6, 7), 2), tokenized((5, 6, 7, 8, 9), 3)], pad_token_id=0, device=CPU)


def test_collate_pads_on_the_right() -> None:
    assert BATCH.attention_mask.tolist() == [[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]]


def test_collate_labels_only_completion_tokens() -> None:
    assert BATCH.labels.tolist() == [
        [IGNORE_INDEX, IGNORE_INDEX, 7, IGNORE_INDEX, IGNORE_INDEX],
        [IGNORE_INDEX, IGNORE_INDEX, IGNORE_INDEX, 8, 9],
    ]


def test_completion_loss_matches_the_model_loss_on_the_same_labels() -> None:
    torch.manual_seed(0)
    config = transformers.Qwen3Config(
        vocab_size=32,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
    )
    model = transformers.Qwen3ForCausalLM(config).eval()
    with torch.no_grad():
        token_losses, _, _ = CompletionLoss(model)(BATCH.input_ids, BATCH.attention_mask, BATCH.labels)
        reference = model(input_ids=BATCH.input_ids, attention_mask=BATCH.attention_mask, labels=BATCH.labels).loss
    assert token_losses.mean().item() == pytest.approx(reference.item(), rel=1e-5)
