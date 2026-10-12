import json
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")

from lean_search.policy.adapters import LORA_TARGET_PATTERN  # noqa: E402
from lean_search.search.records import from_json_object  # noqa: E402
from lean_search.training.sft import OptimizationConfig  # noqa: E402
from lean_search.value.labels import LabelKind, ValueExample  # noqa: E402
from lean_search.value.training import (  # noqa: E402
    TokenizedValueExample,
    ValueEvaluationConfig,
    ValueEvaluationRecord,
    ValueStepRecord,
    ValueTrainingConfig,
    ValueTrainingResult,
    collate_prompts,
    load_value_model,
    pack_prompts,
    plan_value_steps,
    tokenize_value_example,
    train_value_model,
)

CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "training"
SMOKE_MODEL = "Qwen/Qwen3.5-0.8B"
CPU = torch.device("cpu")


def tokenized(length: int, weight: float = 1.0, number: int = 0) -> TokenizedValueExample:
    example = ValueExample((f"⊢ {number}",), LabelKind.EXACT, 1, weight, "source", str(number), 0)
    return TokenizedValueExample(example, tuple(range(1, length + 1)))


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("phase3_value*.toml")), ids=lambda path: path.stem)
def test_shipped_value_configs_load(path: Path) -> None:
    config = from_json_object(ValueTrainingConfig, tomllib.loads(path.read_text(encoding="utf-8")))
    assert config.data


def test_steps_cover_every_example_once_per_epoch() -> None:
    examples = [tokenized(random.Random(number).randint(5, 60), number=number) for number in range(200)]
    steps = plan_value_steps(examples, OptimizationConfig(micro_batch_tokens=256, micro_batches_per_step=1, epochs=2))
    covered = sorted(index for step in steps for batch in step.micro_batches for index in batch)
    assert covered == sorted(list(range(200)) * 2)


def test_a_step_weighs_its_examples() -> None:
    examples = [tokenized(10, weight=0.5 if number % 2 else 1.0, number=number) for number in range(8)]
    (step,) = plan_value_steps(examples, OptimizationConfig(micro_batch_tokens=80, micro_batches_per_step=1))
    assert step.weight == 6.0


def test_collated_prompts_point_at_their_last_token() -> None:
    batch = collate_prompts([tokenized(3), tokenized(5)], pad_token_id=0, device=CPU)
    assert batch.last_positions.tolist() == [2, 4]


def test_collated_prompts_are_padded_on_the_right() -> None:
    batch = collate_prompts([tokenized(3), tokenized(5)], pad_token_id=0, device=CPU)
    assert batch.attention_mask.tolist() == [[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]]


def test_packed_prompts_point_at_their_last_token_in_the_row() -> None:
    batch = pack_prompts([tokenized(3), tokenized(5)], device=CPU)
    assert batch.last_positions.tolist() == [2, 7]


def test_packed_steps_cover_every_example_once_per_epoch() -> None:
    examples = [tokenized(random.Random(number).randint(5, 60), number=number) for number in range(200)]
    config = OptimizationConfig(micro_batch_tokens=256, micro_batches_per_step=1, epochs=2, packing=True)
    covered = sorted(
        index for step in plan_value_steps(examples, config) for batch in step.micro_batches for index in batch
    )
    assert covered == sorted(list(range(200)) * 2)


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    config = transformers.Qwen3Config(
        vocab_size=64,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=16,
        max_position_embeddings=64,
    )
    directory = tmp_path_factory.mktemp("tiny") / "model"
    transformers.Qwen3ForCausalLM(config).save_pretrained(directory)
    return directory


def lora_weights(module: torch.nn.Module) -> dict[str, torch.Tensor]:
    return {name: tensor.detach().clone() for name, tensor in peft.get_peft_model_state_dict(module).items()}


@pytest.fixture(scope="module")
def trained_adapter(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, torch.Tensor]]:
    """An adapter whose weights differ from a fresh one's, as after a round of training."""
    saved_module, _ = load_value_model(ValueTrainingConfig(model=str(tiny_model), data="test"), CPU)
    generator = torch.Generator().manual_seed(1)
    with torch.no_grad():
        for parameter in saved_module.parameters():
            if parameter.requires_grad:
                parameter.add_(torch.randn(parameter.shape, generator=generator).to(parameter.dtype))
    directory = tmp_path_factory.mktemp("adapter") / "adapter"
    saved_module.save_pretrained(directory)
    return directory, lora_weights(saved_module)


def test_value_training_starts_from_the_initial_adapter_weights(
    tiny_model: Path, trained_adapter: tuple[Path, dict[str, torch.Tensor]]
) -> None:
    directory, saved = trained_adapter
    config = ValueTrainingConfig(model=str(tiny_model), data="test", initial_adapter=str(directory))
    loaded = lora_weights(load_value_model(config, CPU)[0])
    assert loaded.keys() == saved.keys() and all(torch.equal(loaded[name], saved[name]) for name in saved)


def test_the_initial_adapter_is_trained(
    tiny_model: Path, trained_adapter: tuple[Path, dict[str, torch.Tensor]]
) -> None:
    directory, _ = trained_adapter
    config = ValueTrainingConfig(model=str(tiny_model), data="test", initial_adapter=str(directory))
    _, model = load_value_model(config, CPU)
    trainable = [name for name, parameter in model.named_parameters() if parameter.requires_grad]
    assert trainable and all("lora_" in name for name in trainable)


def test_without_an_initial_adapter_training_starts_fresh(
    tiny_model: Path, trained_adapter: tuple[Path, dict[str, torch.Tensor]]
) -> None:
    _, saved = trained_adapter
    fresh = lora_weights(load_value_model(ValueTrainingConfig(model=str(tiny_model), data="test"), CPU)[0])
    assert not any(torch.equal(fresh[name], saved[name]) for name in saved)


@dataclass(frozen=True)
class SmokeRun:
    result: ValueTrainingResult
    steps: list[ValueStepRecord]
    adapter_directory: Path


def smoke_examples(tokenizer: transformers.PreTrainedTokenizerBase) -> list[TokenizedValueExample]:
    labels = [(LabelKind.EXACT, 1), (LabelKind.EXACT, 4), (LabelKind.AT_LEAST, 3), (LabelKind.DEAD, 0)]
    examples = [
        ValueExample((f"n : ℕ\n⊢ n + {number} = {number} + n",), kind, steps, 1.0, "smoke", str(number), 0)
        for number, (kind, steps) in enumerate(labels * 4)
    ]
    return [tokenize_value_example(tokenizer, example) for example in examples]


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory: pytest.TempPathFactory) -> SmokeRun:
    if not torch.cuda.is_available():
        pytest.skip("needs a GPU")
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(SMOKE_MODEL, local_files_only=True)
    except OSError:
        pytest.skip(f"{SMOKE_MODEL} is not in the Hugging Face cache")
    examples = smoke_examples(tokenizer)
    config = ValueTrainingConfig(
        model=SMOKE_MODEL,
        data="smoke",
        optimization=OptimizationConfig(
            learning_rate=5e-4, warmup_fraction=0.0, micro_batch_tokens=2048, micro_batches_per_step=1, epochs=8
        ),
        evaluation=ValueEvaluationConfig(interval_steps=1000, validation_examples=16),
    )
    steps: list[ValueStepRecord] = []
    evaluations: list[ValueEvaluationRecord] = []
    adapter_directory = tmp_path_factory.mktemp("value") / "adapter"
    result = train_value_model(
        config,
        tokenizer,
        examples,
        examples,
        torch.device("cuda"),
        adapter_directory,
        steps.append,
        evaluations.append,
    )
    return SmokeRun(result, steps, adapter_directory)


def test_value_training_lowers_the_loss_on_seen_examples(smoke_run: SmokeRun) -> None:
    evaluations = smoke_run.result.evaluations
    assert evaluations[-1].value_loss < evaluations[0].value_loss


def test_value_evaluation_runs_before_and_after_training(smoke_run: SmokeRun) -> None:
    assert [evaluation.step for evaluation in smoke_run.result.evaluations] == [0, smoke_run.result.steps]


def test_value_adapter_targets_only_the_language_model_layers(smoke_run: SmokeRun) -> None:
    adapter_config = json.loads((smoke_run.adapter_directory / "adapter_config.json").read_text(encoding="utf-8"))
    assert adapter_config["target_modules"] == LORA_TARGET_PATTERN


def test_every_value_step_reports_a_finite_loss(smoke_run: SmokeRun) -> None:
    assert all(torch.isfinite(torch.tensor(step.value_loss)) for step in smoke_run.steps)
