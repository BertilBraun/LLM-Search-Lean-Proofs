import dataclasses
import tomllib
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, expansion_texts, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, record_published  # noqa: E402
from lean_search.rl.grpo_groups import RewardMode  # noqa: E402
from lean_search.rl.policy_trainer import GrpoConfig  # noqa: E402
from lean_search.rl.training_phase import (  # noqa: E402
    PhaseInputs,
    PhaseOutcome,
    TrainingPhaseConfig,
    label_phase_data,
    publish_phase,
    run_training_phase,
)
from lean_search.search import TreeRecord  # noqa: E402
from lean_search.search.records import from_json_object  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig  # noqa: E402
from lean_search.value.benchmark import (  # noqa: E402
    BenchmarkConfig,
    SearchGuidance,
    TreeProvenance,
    TreeSource,
    build_benchmark,
)
from lean_search.value.graph_trainer import GraphValueConfig  # noqa: E402

CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "grpo"
CPU = torch.device("cpu")
LORA = LoraSettings(rank=8, alpha=8)
OPTIMIZATION = OptimizationConfig(
    learning_rate=1e-2, warmup_fraction=0.0, micro_batch_tokens=65536, gradient_checkpointing=False
)


def load(path: Path) -> TrainingPhaseConfig:
    return from_json_object(TrainingPhaseConfig, tomllib.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("*.toml")), ids=lambda path: path.stem)
def test_shipped_phase_configs_train_both_models(path: Path) -> None:
    config = load(path)
    assert config.policy is not None and config.value is not None


def test_control_config_uses_the_outcome_only_reward() -> None:
    assert load(CONFIG_DIRECTORY / "phase_outcome_only.toml").reward.mode == RewardMode.OUTCOME_ONLY


def phase_tree() -> TreeRecord:
    builder = GraphBuilder("⊢ " + "r" * 100, root_value=4.0)
    child = builder.child(builder.root, "⊢ " + "p" * 100, value=2.0, text="intro y")
    builder.failure(builder.root, text="simp at q")
    dead = builder.child(builder.root, "⊢ " + "d" * 100, value=3.0, text="norm_num")
    builder.failure(dead, text="linarith")
    proof = builder.child(child, text="rfl")
    return builder.record(proof)


@pytest.fixture(scope="module")
def phase(tmp_path_factory: pytest.TempPathFactory) -> tuple[PhaseOutcome, Path]:
    model = save_tiny_model(tmp_path_factory.mktemp("tiny") / "model")
    record = phase_tree()
    config = TrainingPhaseConfig(
        policy=GrpoConfig(model=str(model), lora=LORA, optimization=OPTIMIZATION, scoring_micro_batch_tokens=65536),
        value=GraphValueConfig(model=str(model), lora=LORA, optimization=OPTIMIZATION),
    )
    provenance = TreeProvenance("benchmark", SearchGuidance.VALUE_FREE, None, "")
    benchmark = build_benchmark([TreeSource(provenance, label_phase_data([record], config).trees)], BenchmarkConfig())
    inputs = PhaseInputs(records=[record], texts=expansion_texts(record), value_benchmark=benchmark)
    output = tmp_path_factory.mktemp("phase")
    tokenizer = CharacterTokenizer()
    return run_training_phase(config, inputs, tokenizer, tokenizer, CPU, output), output


def test_phase_writes_both_adapters_and_its_outcome(phase: tuple[PhaseOutcome, Path]) -> None:
    _, output = phase
    written = [
        output / "policy" / "adapter" / "adapter_config.json",
        output / "value" / "adapter",
        output / "phase.json",
    ]
    assert all(path.exists() for path in written)


def test_phase_trains_only_the_root_group_with_its_three_samples(phase: tuple[PhaseOutcome, Path]) -> None:
    outcome, _ = phase
    assert outcome.policy is not None and outcome.policy.data.sequences == 3 * 2


class RecordingPublisher:
    """Serves adapters as they are (the loop's MergedPublisher merges them first)."""

    def prepare(self, version: ModelVersion) -> ModelVersion:
        return dataclasses.replace(version, policy_weights=version.policy_adapter, value_weights=version.value_adapter)

    def serve_command(self, version: ModelVersion, server: object) -> str:
        return ""

    def prune(self, current: ModelVersion) -> None:
        pass


def test_published_value_adapter_changes_only_after_a_passed_gate(
    phase: tuple[PhaseOutcome, Path], tmp_path: Path
) -> None:
    outcome, _ = phase
    paths = LoopPaths(tmp_path, tmp_path, "loop")
    record_published(paths, ModelVersion(0, "policy-v0", "value-v0", "", "initial"))
    published = publish_phase(paths, RecordingPublisher(), outcome, "test")
    assert outcome.value is not None
    expected = outcome.value.adapter if outcome.value.accepted else "value-v0"
    assert (published.policy_adapter, published.value_adapter) == (outcome.policy.adapter, expected)
