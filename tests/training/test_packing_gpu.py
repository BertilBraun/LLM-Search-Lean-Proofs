import dataclasses

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="varlen kernels need a GPU")

from lean_search.training.packing import enable_packed_sequences  # noqa: E402
from lean_search.training.sft import CompletionLoss, collate, pack  # noqa: E402
from lean_search.training.sft_data import SftExample, TokenizedExample  # noqa: E402
from lean_search.value.labels import LabelKind, ValueExample  # noqa: E402
from lean_search.value.training import (  # noqa: E402
    LastPositionLogits,
    TokenizedValueExample,
    collate_prompts,
    pack_prompts,
)

LENGTHS = (37, 90, 5, 64, 130, 21)


def tiny_qwen3_5() -> transformers.PreTrainedModel:
    torch.manual_seed(0)
    config = transformers.Qwen3_5TextConfig(
        vocab_size=128,
        hidden_size=128,
        intermediate_size=256,
        num_hidden_layers=4,
        layer_types=["linear_attention", "linear_attention", "linear_attention", "full_attention"],
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=64,
        linear_num_key_heads=2,
        linear_num_value_heads=2,
        linear_key_head_dim=64,
        linear_value_head_dim=64,
        rope_parameters={
            "rope_type": "default",
            "rope_theta": 10000.0,
            "partial_rotary_factor": 0.25,
            "mrope_section": [3, 3, 2],
            "mrope_interleaved": True,
        },
    )
    model = transformers.Qwen3_5ForCausalLM(config).to(device="cuda", dtype=torch.bfloat16).eval()
    enable_packed_sequences(model)
    return model


def examples(seed: int) -> list[TokenizedExample]:
    generator = torch.Generator().manual_seed(seed)
    return [
        TokenizedExample(
            SftExample("source", f"proof/{index}", 0, ("⊢ True",), "trivial"),
            tuple(torch.randint(1, 128, (length,), generator=generator).tolist()),
            length // 2,
        )
        for index, length in enumerate(LENGTHS)
    ]


@torch.no_grad()
def completion_losses(model: transformers.PreTrainedModel, batch_examples: list[TokenizedExample]) -> torch.Tensor:
    batch = pack(batch_examples, torch.device("cuda"))
    token_losses, _, _ = CompletionLoss(model)(
        batch.input_ids, batch.attention_mask, batch.labels, batch.position_ids, batch.sequence_starts
    )
    return token_losses.float()


@torch.no_grad()
def unpacked_losses(model: transformers.PreTrainedModel, batch_examples: list[TokenizedExample]) -> torch.Tensor:
    losses = []
    for example in batch_examples:
        batch = collate([example], pad_token_id=0, device=torch.device("cuda"))
        token_losses, _, _ = CompletionLoss(model)(batch.input_ids, batch.attention_mask, batch.labels)
        losses.append(token_losses.float())
    return torch.cat(losses)


def test_packed_losses_match_each_example_alone() -> None:
    model = tiny_qwen3_5()
    torch.testing.assert_close(
        completion_losses(model, examples(0)), unpacked_losses(model, examples(0)), atol=0.05, rtol=0.0
    )


def test_changing_the_other_examples_leaves_an_example_losses_unchanged() -> None:
    model = tiny_qwen3_5()
    original = examples(0)
    neighbours_changed = [
        example if index == 2 else dataclasses.replace(example, input_ids=examples(1)[index].input_ids)
        for index, example in enumerate(original)
    ]
    start = sum(example.completion_token_count for example in original[:2])
    kept = slice(start, start + original[2].completion_token_count)
    assert torch.equal(completion_losses(model, neighbours_changed)[kept], completion_losses(model, original)[kept])


def test_packed_value_prompts_give_each_prompt_its_own_last_logits() -> None:
    model = tiny_qwen3_5()
    prompts = [
        TokenizedValueExample(
            ValueExample(("⊢ True",), LabelKind.EXACT, 1, 1.0, "source", str(index), 0), example.input_ids
        )
        for index, example in enumerate(examples(0))
    ]
    with torch.no_grad():
        packed = LastPositionLogits(model)(pack_prompts(prompts, torch.device("cuda"))).float()
        alone = torch.cat(
            [
                LastPositionLogits(model)(collate_prompts([prompt], 0, torch.device("cuda"))).float()
                for prompt in prompts
            ]
        )
    torch.testing.assert_close(packed, alone, atol=0.05, rtol=0.0)
