import dataclasses
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, expansion_texts, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
peft = pytest.importorskip("peft")

from lean_search.policy.adapters import saved_adapter_weights  # noqa: E402
from lean_search.rl.policy_data import PolicyDataConfig, PolicySequence, PolicyTree, build_policy_data  # noqa: E402
from lean_search.rl.policy_trainer import (  # noqa: E402
    CompletionTokenScores,
    GrpoConfig,
    GrpoStepRecord,
    ReferencePolicy,
    compile_warm_up,
    completion_log_probabilities,
    plan_grpo_steps,
    reference_log_probabilities,
    sampler_agreement,
    sampler_agreement_by_version,
    train_grpo,
)
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
    groups = label_phase_data([record], TrainingPhaseConfig()).groups
    trees = [PolicyTree(tuple(groups), tuple(expansion_texts(record)))]
    return build_policy_data(trees, CharacterTokenizer(), PolicyDataConfig()).sequences


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return save_tiny_model(tmp_path_factory.mktemp("tiny") / "model")


def random_adapter(model: Path, directory: Path, seed: int) -> Path:
    """An adapter that changes the model's outputs, as a published policy adapter does."""
    saved, _ = load_trainable_model(str(model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU)
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for parameter in saved.parameters():
            if parameter.requires_grad:
                parameter.add_(torch.randn(parameter.shape, generator=generator).to(parameter.dtype))
    saved.save_pretrained(directory)
    return directory


@pytest.fixture(scope="module")
def perturbed_adapter(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return random_adapter(tiny_model, tmp_path_factory.mktemp("adapter") / "adapter", seed=1)


@pytest.fixture(scope="module")
def starting_adapter(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The starting policy's own adapter, which the published ones continue."""
    return random_adapter(tiny_model, tmp_path_factory.mktemp("starting") / "adapter", seed=2)


def grpo_config(model: Path, passes: int, **changes: object) -> GrpoConfig:
    config = GrpoConfig(
        model=str(model),
        lora=LORA,
        optimization=OptimizationConfig(
            learning_rate=1e-2,
            warmup_fraction=0.0,
            minimum_learning_rate_ratio=1.0,
            micro_batch_tokens=8192,
            gradient_checkpointing=False,
        ),
        sequences_per_step=8,
        passes_per_phase=passes,
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
    temperatures = [sequence.temperature for sequence in sequences()]
    scores = completion_log_probabilities(
        CompletionTokenScores(causal_model), examples, temperatures, 8192, False, 0, CPU
    )
    return [score.sum().item() for score in scores]


def test_the_root_group_trains_both_completions_of_both_samples() -> None:
    assert len(sequences()) == 4


def test_training_raises_the_better_sample_against_the_failing_one(tiny_model: Path, tmp_path: Path) -> None:
    before = summed_log_probabilities(tiny_model, "")
    train(grpo_config(tiny_model, passes=10), tmp_path / "adapter")
    after = summed_log_probabilities(tiny_model, str(tmp_path / "adapter"))
    good = [index for index, sequence in enumerate(sequences()) if sequence.advantages[0] > 0]
    bad = [index for index, sequence in enumerate(sequences()) if sequence.advantages[0] < 0]
    gain = [after[index] - before[index] for index in range(len(before))]
    assert min(gain[index] for index in good) > max(gain[index] for index in bad)


def test_first_step_starts_at_the_data_collecting_policy(tiny_model: Path, tmp_path: Path) -> None:
    records = train(grpo_config(tiny_model, passes=1), tmp_path / "adapter")
    assert records[0].kl_to_data_policy == pytest.approx(0.0, abs=1e-4)


def test_kl_to_the_starting_weights_measures_the_published_adapter(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(tiny_model, passes=1, initial_adapter=str(perturbed_adapter))
    assert train(config, tmp_path / "adapter")[0].kl_to_reference > 1e-3


def test_without_feedback_sequences_the_first_rounds_kl_is_the_whole_kl(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(tiny_model, passes=1, initial_adapter=str(perturbed_adapter))
    first = train(config, tmp_path / "adapter")[0]
    assert first.first_round_kl_to_reference == pytest.approx(first.kl_to_reference)


def test_the_first_rounds_kl_leaves_out_feedback_sequences(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(tiny_model, passes=1, initial_adapter=str(perturbed_adapter))
    feedback = tuple(dataclasses.replace(sequence, feedback=True) for sequence in sequences())
    records: list[GrpoStepRecord] = []
    train_grpo(config, 0, feedback, [], CPU, tmp_path / "adapter", records.append)
    assert records[0].first_round_trained_tokens == 0


def test_kl_to_the_phase_start_is_zero_before_the_first_update(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(
        tiny_model, passes=1, initial_adapter=str(perturbed_adapter), reference=ReferencePolicy.PHASE_START
    )
    assert train(config, tmp_path / "adapter")[0].kl_to_reference == pytest.approx(0.0, abs=1e-4)


def test_kl_to_the_starting_adapter_is_zero_when_the_phase_continues_it(
    tiny_model: Path, starting_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(
        tiny_model, passes=1, initial_adapter=str(starting_adapter), reference_adapter=str(starting_adapter)
    )
    assert train(config, tmp_path / "adapter")[0].kl_to_reference == pytest.approx(0.0, abs=1e-4)


def reference_after_continuing(
    tiny_model: Path, published: Path, starting: Path, **changes: object
) -> tuple[list[torch.Tensor | None], torch.nn.Module]:
    """The reference log-probabilities of a phase continuing `published`, and the module that scored them."""
    config = grpo_config(
        tiny_model, passes=1, initial_adapter=str(published), reference_adapter=str(starting), **changes
    )
    saved, causal_model = load_trainable_model(str(tiny_model), config.optimization, LORA, CPU, str(published))
    causal_model.eval()
    examples = [sequence.tokenized for sequence in sequences()]
    temperatures = [sequence.temperature for sequence in sequences()]
    scorer = CompletionTokenScores(causal_model)
    return reference_log_probabilities(config, saved, scorer, examples, temperatures, [], 0, CPU), saved


def test_the_reference_is_the_starting_adapter(
    tiny_model: Path, perturbed_adapter: Path, starting_adapter: Path
) -> None:
    reference, _ = reference_after_continuing(tiny_model, perturbed_adapter, starting_adapter)
    expected = summed_log_probabilities(tiny_model, str(starting_adapter))
    assert [scores.sum().item() for scores in reference] == pytest.approx(expected, abs=1e-4)


def test_scoring_the_reference_leaves_only_the_published_adapter_trainable(
    tiny_model: Path, perturbed_adapter: Path, starting_adapter: Path
) -> None:
    _, saved = reference_after_continuing(tiny_model, perturbed_adapter, starting_adapter)
    trainable = {name for name, parameter in saved.named_parameters() if parameter.requires_grad}
    assert trainable and all(".default." in name for name in trainable)


def test_scoring_the_reference_puts_the_published_weights_back(
    tiny_model: Path, perturbed_adapter: Path, starting_adapter: Path
) -> None:
    _, saved = reference_after_continuing(tiny_model, perturbed_adapter, starting_adapter)
    published = saved_adapter_weights(perturbed_adapter, CPU)
    weights = peft.get_peft_model_state_dict(saved)
    assert all(torch.equal(weights[name].float(), tensor.float()) for name, tensor in published.items())


@pytest.mark.parametrize(("kl_coefficient", "scored"), [(0.0, 1), (0.1, 4)], ids=["reported only", "penalty"])
def test_reference_scores_a_subsample_unless_the_kl_penalty_trains_on_it(
    tiny_model: Path, perturbed_adapter: Path, starting_adapter: Path, kl_coefficient: float, scored: int
) -> None:
    reference, _ = reference_after_continuing(
        tiny_model, perturbed_adapter, starting_adapter, reference_sequences=1, kl_coefficient=kl_coefficient
    )
    assert sum(scores is not None for scores in reference) == scored


def test_kl_to_the_starting_weights_is_measured_on_the_subsample(
    tiny_model: Path, perturbed_adapter: Path, tmp_path: Path
) -> None:
    config = grpo_config(tiny_model, passes=1, initial_adapter=str(perturbed_adapter), reference_sequences=1)
    assert train(config, tmp_path / "adapter")[0].kl_to_reference > 1e-3


def test_first_step_ratios_are_one_for_both_advantage_signs(tiny_model: Path, tmp_path: Path) -> None:
    ratios = train(grpo_config(tiny_model, passes=1), tmp_path / "adapter")[0].ratios
    assert (ratios.positive.mean_ratio, ratios.negative.mean_ratio) == (pytest.approx(1.0), pytest.approx(1.0))


def test_second_pass_raises_positive_and_lowers_negative_advantage_tokens(tiny_model: Path, tmp_path: Path) -> None:
    result = train_grpo(grpo_config(tiny_model, passes=2), 0, sequences(), [], CPU, tmp_path / "adapter", [].append)
    second = result.ratios_by_pass[1]
    assert second.positive.mean_ratio > 1.0 > second.negative.mean_ratio


def test_replay_examples_report_their_nll(tiny_model: Path, tmp_path: Path) -> None:
    config = grpo_config(tiny_model, passes=1, replay_sequences_per_step=2, replay_weight=0.5)
    replay = [sequence.tokenized for sequence in sequences()[:2]]
    records: list[GrpoStepRecord] = []
    train_grpo(config, 0, sequences(), replay, CPU, tmp_path / "adapter", records.append)
    assert records[0].replay_nll > 0


def test_log_probabilities_divide_the_logits_by_the_temperature(tiny_model: Path) -> None:
    _, causal_model = load_trainable_model(str(tiny_model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU)
    causal_model.eval()
    example = sequences()[0].tokenized
    (scores,) = completion_log_probabilities(CompletionTokenScores(causal_model), [example], [0.5], 8192, False, 0, CPU)
    with torch.no_grad():
        logits = causal_model(input_ids=torch.tensor([example.input_ids])).logits[0, :-1].float()
    targets = torch.tensor(example.input_ids[1:])
    expected = torch.log_softmax(logits / 0.5, dim=-1).gather(-1, targets[:, None])[:, 0][
        example.prompt_token_count - 1 :
    ]
    assert torch.allclose(scores, expected, atol=1e-2)


def test_sampler_agreement_compares_the_recorded_log_probabilities() -> None:
    recorded = sequences()
    old = [torch.full((sequence.tokenized.completion_token_count,), -0.75) for sequence in recorded]
    assert sampler_agreement(recorded, old).mean_difference == pytest.approx(-0.75 - -1.0)


def test_sampler_agreement_is_reported_per_sampling_version() -> None:
    recorded = [dataclasses.replace(sequence, policy_version=index % 2) for index, sequence in enumerate(sequences())]
    old = [
        torch.full((sequence.tokenized.completion_token_count,), -0.5 - sequence.policy_version)
        for sequence in recorded
    ]
    by_version = sampler_agreement_by_version(recorded, old)
    differences = [(entry.policy_version, entry.agreement.mean_difference) for entry in by_version]
    assert differences == [(0, pytest.approx(0.5)), (1, pytest.approx(-0.5))]


@pytest.mark.parametrize(("passes", "steps"), [(1, 1), (2, 2)])
def test_passes_per_phase(tiny_model: Path, passes: int, steps: int) -> None:
    assert len(plan_grpo_steps(sequences(), grpo_config(tiny_model, passes=passes))) == steps


def test_a_sequence_beyond_the_servers_context_is_a_bug(tiny_model: Path, tmp_path: Path) -> None:
    with pytest.raises(AssertionError):
        train(grpo_config(tiny_model, passes=1, max_sequence_tokens=10), tmp_path / "adapter")


def test_the_compile_warm_up_leaves_no_gradients(tiny_model: Path) -> None:
    saved, causal_model = load_trainable_model(
        str(tiny_model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU
    )
    sequence = sequences()[0]
    scorer = CompletionTokenScores(causal_model)
    compile_warm_up(saved, scorer, sequence.tokenized, sequence.temperature, False, 0, CPU)
    assert all(parameter.grad is None for parameter in saved.parameters())
