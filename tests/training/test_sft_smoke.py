import json
from dataclasses import dataclass
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from lean_search.policy.adapters import LORA_TARGET_PATTERN  # noqa: E402
from lean_search.training.sft import (  # noqa: E402
    DistributedContext,
    EvaluationConfig,
    EvaluationRecord,
    FineTuningMethod,
    OptimizationConfig,
    SftConfig,
    StepRecord,
    TrainingResult,
    train,
)
from lean_search.training.sft_data import SftExample, TokenizedExample, tokenize_example  # noqa: E402

MODEL = "Qwen/Qwen3.5-0.8B"

pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a GPU")


@dataclass(frozen=True)
class SmokeRun:
    result: TrainingResult
    steps: list[StepRecord]
    output_directory: Path


def smoke_examples(tokenizer: transformers.PreTrainedTokenizerBase) -> list[TokenizedExample]:
    examples = [
        SftExample("smoke", f"smoke/0/{number}", 0, (f"n : ℕ\n⊢ n + {number} = {number} + n",), "omega")
        for number in range(16)
    ]
    return [tokenize_example(tokenizer, example) for example in examples]


def run_smoke(directory: Path, optimization: OptimizationConfig) -> SmokeRun:
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    except OSError:
        pytest.skip(f"{MODEL} is not in the Hugging Face cache")
    examples = smoke_examples(tokenizer)
    config = SftConfig(
        model=MODEL,
        data="smoke",
        optimization=optimization,
        evaluation=EvaluationConfig(
            interval_steps=1000, validation_examples=8, generation_examples=4, generation_batch_size=4, max_new_tokens=8
        ),
    )
    steps: list[StepRecord] = []
    evaluations: list[EvaluationRecord] = []
    context = DistributedContext(rank=0, world_size=1, device=torch.device("cuda"))
    result = train(config, tokenizer, examples, examples[:8], context, directory, steps.append, evaluations.append)
    return SmokeRun(result, steps, directory)


@pytest.fixture(scope="module")
def lora_run(tmp_path_factory: pytest.TempPathFactory) -> SmokeRun:
    optimization = OptimizationConfig(
        learning_rate=5e-4,
        warmup_fraction=0.0,
        micro_batch_tokens=1024,
        micro_batches_per_step=1,
        epochs=4,
        length_group_examples=16,
    )
    return run_smoke(tmp_path_factory.mktemp("lora") / "adapter", optimization)


@pytest.fixture(scope="module")
def full_run(tmp_path_factory: pytest.TempPathFactory) -> SmokeRun:
    optimization = OptimizationConfig(
        method=FineTuningMethod.FULL, learning_rate=1e-5, micro_batch_tokens=1024, micro_batches_per_step=1, max_steps=2
    )
    return run_smoke(tmp_path_factory.mktemp("full") / "model", optimization)


def test_lora_training_lowers_the_validation_loss_on_seen_examples(lora_run: SmokeRun) -> None:
    evaluations = lora_run.result.evaluations
    assert evaluations[-1].validation_loss < evaluations[0].validation_loss


def test_evaluation_runs_before_and_after_training(lora_run: SmokeRun) -> None:
    assert [evaluation.step for evaluation in lora_run.result.evaluations] == [0, lora_run.result.steps]


def test_the_adapter_targets_only_the_language_model_layers(lora_run: SmokeRun) -> None:
    adapter_config = json.loads((lora_run.output_directory / "adapter_config.json").read_text(encoding="utf-8"))
    assert adapter_config["target_modules"] == LORA_TARGET_PATTERN


def test_every_step_reports_a_finite_loss(lora_run: SmokeRun) -> None:
    assert all(torch.isfinite(torch.tensor(step.loss)) for step in lora_run.steps)


def test_full_fine_tuning_saves_a_loadable_model(full_run: SmokeRun) -> None:
    config = transformers.AutoConfig.from_pretrained(full_run.output_directory)
    assert config.model_type == transformers.AutoConfig.from_pretrained(MODEL).model_type
