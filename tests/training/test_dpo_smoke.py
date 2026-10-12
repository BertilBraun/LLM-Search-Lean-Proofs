from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
pytest.importorskip("peft")

from lean_search.policy.adapters import create_zero_adapter  # noqa: E402
from lean_search.training.dpo import (  # noqa: E402
    DpoConfig,
    DpoEvaluationConfig,
    DpoEvaluationRecord,
    train_dpo,
)
from lean_search.training.dpo_data import PreferencePair, TokenizedPair, tokenize_pair  # noqa: E402
from lean_search.training.sft import OptimizationConfig  # noqa: E402

# Every character of the prompts and completions below has a code point under this.
VOCABULARY_SIZE = 9000


class CharacterTokenizer:
    pad_token_id = 0

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + "<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A two-layer random Qwen2 with a fresh LoRA adapter, small enough to train on the CPU in seconds."""
    pytest.importorskip("accelerate")
    directory = tmp_path_factory.mktemp("tiny")
    config = transformers.Qwen2Config(
        vocab_size=VOCABULARY_SIZE,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=1024,
    )
    torch.manual_seed(0)
    transformers.Qwen2ForCausalLM(config).save_pretrained(directory / "model")
    create_zero_adapter(str(directory / "model"), directory / "adapter", rank=8)
    return directory / "model", directory / "adapter"


def preference_pairs() -> list[TokenizedPair]:
    tokenizer = CharacterTokenizer()
    return [
        tokenize_pair(
            tokenizer, PreferencePair("s", f"p{number}", 0, (f"⊢ {number} = {number}",), "rfl", "simp", "error")
        )
        for number in range(8)
    ]


def test_dpo_opens_a_reward_margin_on_its_training_pairs(tiny_model: tuple[Path, Path], tmp_path: Path) -> None:
    model, adapter = tiny_model
    pairs = preference_pairs()
    config = DpoConfig(
        model=str(model),
        initial_adapter=str(adapter),
        data="unused",
        beta=0.5,
        optimization=OptimizationConfig(
            learning_rate=1e-2,
            warmup_fraction=0.0,
            epochs=10,
            micro_batch_tokens=8192,
            micro_batches_per_step=1,
            length_group_examples=8,
            gradient_checkpointing=False,
        ),
        evaluation=DpoEvaluationConfig(interval_steps=1000, validation_pairs=8, micro_batch_tokens=8192),
    )
    evaluations: list[DpoEvaluationRecord] = []
    train_dpo(
        config, CharacterTokenizer(), pairs, pairs, torch.device("cpu"), tmp_path / "adapter", print, evaluations.append
    )
    assert evaluations[-1].metrics.reward_margin > 0.1
