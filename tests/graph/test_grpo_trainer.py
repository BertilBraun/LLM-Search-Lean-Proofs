import dataclasses
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, expansion_texts, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

from lean_search.rl.advantages import AdvantageConfig  # noqa: E402
from lean_search.rl.policy_data import GroupWeightConfig, PolicySequence, build_policy_data  # noqa: E402
from lean_search.rl.policy_trainer import (  # noqa: E402
    CompletionTokenScores,
    GrpoConfig,
    GrpoStepRecord,
    ReferencePolicy,
    completion_log_probabilities,
    train_grpo,
)
from lean_search.rl.token_credit import CreditMode  # noqa: E402
from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data  # noqa: E402
from lean_search.search import TreeRecord  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig, load_trainable_model  # noqa: E402

CPU = torch.device("cpu")
LORA = LoraSettings(rank=8, alpha=8)
GOOD = "intro y"
BAD = "simp at q"


def policy_tree() -> TreeRecord:
    builder = GraphBuilder("⊢ x = 1")
    child = builder.child(builder.root, "⊢ y = 1", text=GOOD)
    builder.failure(builder.root, text=BAD)
    proof = builder.child(child, text="rfl")
    return builder.record(proof)


def sequences() -> tuple[PolicySequence, ...]:
    record = policy_tree()
    config = TrainingPhaseConfig()
    labelled = label_phase_data([record], config)
    data = build_policy_data(
        labelled.groups,
        expansion_texts(record),
        CharacterTokenizer(),
        config.reward,
        AdvantageConfig(),
        CreditMode.PER_TOKEN,
        GroupWeightConfig(),
        max_prompt_tokens=1000,
        max_completion_tokens=1000,
    )
    return data.sequences


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return save_tiny_model(tmp_path_factory.mktemp("tiny") / "model")


@pytest.fixture(scope="module")
def perturbed_adapter(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An adapter that changes the model's outputs, as a published policy adapter does."""
    saved, _ = load_trainable_model(str(tiny_model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU)
    generator = torch.Generator().manual_seed(1)
    with torch.no_grad():
        for parameter in saved.parameters():
            if parameter.requires_grad:
                parameter.add_(torch.randn(parameter.shape, generator=generator).to(parameter.dtype))
    directory = tmp_path_factory.mktemp("adapter") / "adapter"
    saved.save_pretrained(directory)
    return directory


def grpo_config(model: Path, epochs: int, **changes: object) -> GrpoConfig:
    config = GrpoConfig(
        model=str(model),
        lora=LORA,
        optimization=OptimizationConfig(
            learning_rate=1e-2,
            warmup_fraction=0.0,
            minimum_learning_rate_ratio=1.0,
            epochs=epochs,
            micro_batch_tokens=8192,
            gradient_checkpointing=False,
        ),
        sequences_per_step=8,
        scoring_micro_batch_tokens=8192,
    )
    return dataclasses.replace(config, **changes)


def train(config: GrpoConfig, directory: Path) -> list[GrpoStepRecord]:
    records: list[GrpoStepRecord] = []
    train_grpo(config, 0, sequences(), [], CPU, directory, records.append)
    return records


def summed_log_probabilities(model: Path, adapter: str) -> list[float]:
    saved, causal_model = load_trainable_model(
        str(model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU, adapter
    )
    causal_model.eval()
    examples = [sequence.tokenized for sequence in sequences()]
    scores = completion_log_probabilities(CompletionTokenScores(causal_model), examples, 8192, False, 0, CPU)
    return [score.sum().item() for score in scores]


def test_the_root_group_trains_both_completions_of_both_samples() -> None:
    assert len(sequences()) == 4


def test_training_raises_the_better_sample_against_the_failing_one(tiny_model: Path, tmp_path: Path) -> None:
    before = summed_log_probabilities(tiny_model, "")
    train(grpo_config(tiny_model, epochs=10), tmp_path / "adapter")
    after = summed_log_probabilities(tiny_model, str(tmp_path / "adapter"))
    good = [index for index, sequence in enumerate(sequences()) if sequence.advantages[0] > 0]
    bad = [index for index, sequence in enumerate(sequences()) if sequence.advantages[0] < 0]
    gain = [after[index] - before[index] for index in range(len(before))]
    assert min(gain[index] for index in good) > max(gain[index] for index in bad)


def test_first_step_starts_at_the_data_collecting_policy(tiny_model: Path, tmp_path: Path) -> None:
    records = train(grpo_config(tiny_model, epochs=1), tmp_path / "adapter")
    assert records[0].kl_to_data_policy == pytest.approx(0.0, abs=1e-4)


def test_kl_to_the_starting_weights_measures_the_published_adapter(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(tiny_model, epochs=1, initial_adapter=str(perturbed_adapter))
    assert train(config, tmp_path / "adapter")[0].kl_to_reference > 1e-3


def test_kl_to_the_phase_start_is_zero_before_the_first_update(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(
        tiny_model, epochs=1, initial_adapter=str(perturbed_adapter), reference=ReferencePolicy.PHASE_START
    )
    assert train(config, tmp_path / "adapter")[0].kl_to_reference == pytest.approx(0.0, abs=1e-4)


def test_replay_examples_report_their_nll(tiny_model: Path, tmp_path: Path) -> None:
    config = grpo_config(tiny_model, epochs=1, replay_sequences_per_step=2, replay_weight=0.5)
    replay = [sequence.tokenized for sequence in sequences()[:2]]
    records: list[GrpoStepRecord] = []
    train_grpo(config, 0, sequences(), replay, CPU, tmp_path / "adapter", records.append)
    assert records[0].replay_nll > 0
