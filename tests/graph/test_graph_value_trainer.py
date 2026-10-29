import dataclasses
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data  # noqa: E402
from lean_search.search import TreeRecord  # noqa: E402
from lean_search.search.priority import PriorityKind  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig  # noqa: E402
from lean_search.value.benchmark import (  # noqa: E402
    BenchmarkConfig,
    EstimateKind,
    GuidedTrees,
    LabelledTree,
    SearchGuidance,
    TreeProvenance,
    TreeSource,
    ValueBenchmark,
    build_benchmark,
)
from lean_search.value.bins import BIN_COUNT, DEAD_BIN  # noqa: E402
from lean_search.value.gate_statistics import GateConfig  # noqa: E402
from lean_search.value.graph_targets import SourceShares, TargetSource  # noqa: E402
from lean_search.value.graph_trainer import (  # noqa: E402
    GraphValueConfig,
    GraphValueData,
    GraphValueStepRecord,
    RankingScore,
    build_graph_value_data,
    plan_graph_value_steps,
    ranking_losses,
    ranking_scores,
    run_value_gate,
    soft_target_losses,
    train_graph_value_model,
)
from lean_search.value.labels import LabelKind, ValueExample  # noqa: E402
from lean_search.value.ranking import RankingConfig  # noqa: E402

CPU = torch.device("cpu")


def goal(letter: str) -> str:
    """Long goals, so that states differ in much of their prompt for the tiny model's diffuse attention."""
    return "⊢ " + letter * 200


def value_tree() -> TreeRecord:
    """A solved root with a proof-graph child, a dead end, an expanded off-graph branch and a never-expanded child."""
    builder = GraphBuilder(goal("r"), root_value=4.0)
    proof_child = builder.child(builder.root, goal("p"), value=2.0)
    dead = builder.child(builder.root, goal("d"), value=3.0)
    builder.failure(dead)
    expanded = builder.child(builder.root, goal("e"), value=5.0)
    below = builder.child(expanded, goal("f"), value=6.0)
    builder.child(below, goal("g"), value=8.0)
    builder.child(builder.root, goal("n"), value=7.0)
    proof = builder.child(proof_child)
    return builder.record(proof)


def labelled_trees() -> tuple[LabelledTree, ...]:
    return label_phase_data([value_tree()], TrainingPhaseConfig()).trees


VALUE_FREE = TreeProvenance("row2", SearchGuidance.VALUE_FREE, PriorityKind.CUMULATIVE_LOG_PROBABILITY, "")
GUIDED = TreeProvenance("astar", SearchGuidance.VALUE_MODEL, PriorityKind.A_STAR, "value-v0")


def value_benchmark(provenance: TreeProvenance = VALUE_FREE) -> ValueBenchmark:
    return build_benchmark([TreeSource(provenance, labelled_trees())], BenchmarkConfig())


REPLAY = [
    ValueExample(("⊢ v",), LabelKind.EXACT, 2, 1.0, "v0", "v0/a", 0),
    ValueExample(("⊢ w",), LabelKind.DEAD, 0, 1.0, "v0", "v0/b", 0),
    ValueExample(("⊢ u",), LabelKind.AT_LEAST, 3, 1.0, "v0", "v0/c", 0),
]


def value_config(model: str = "unused", **changes: object) -> GraphValueConfig:
    config = GraphValueConfig(
        model=model,
        lora=LoraSettings(rank=8, alpha=8),
        optimization=OptimizationConfig(
            learning_rate=1e-2,
            warmup_fraction=0.0,
            minimum_learning_rate_ratio=1.0,
            micro_batch_tokens=65536,
            micro_batches_per_step=8,
            gradient_checkpointing=False,
        ),
        replay_share=0.5,
    )
    return dataclasses.replace(config, **changes)


def value_data(config: GraphValueConfig | None = None) -> GraphValueData:
    ranking = RankingConfig(proof_over_never_expanded_weight=0.1)
    return build_graph_value_data(labelled_trees(), ranking, REPLAY, CharacterTokenizer(), config or value_config())


def test_both_states_of_every_pair_train_in_the_same_unit() -> None:
    data = value_data()
    assert all(
        any({data.pairs[index].preferred, data.pairs[index].other} <= set(unit.states) for unit in data.units)
        for index in range(len(data.pairs))
    )


def test_two_trees_of_one_statement_keep_their_own_states() -> None:
    builder = GraphBuilder(goal("r"), root_value=4.0)
    builder.failure(builder.child(builder.root, goal("x"), value=3.0))
    other_search = builder.record()
    trees = label_phase_data([value_tree(), other_search], TrainingPhaseConfig()).trees
    data = build_graph_value_data(trees, RankingConfig(), [], CharacterTokenizer(), value_config())
    prompts = ["".join(map(chr, state.input_ids)) for state in data.states]
    assert any(goal("x") in prompt for prompt in prompts)


def test_every_graph_target_trains_once() -> None:
    data = value_data()
    graph_items = [item for item in data.pointwise if item.target is not None]
    assert len(graph_items) == sum(len(tree.targets) for tree in labelled_trees())


def test_censored_replay_examples_are_dropped() -> None:
    assert value_data().dropped_replay_examples == 1


def test_replay_items_are_capped_by_the_usable_examples() -> None:
    assert value_data().replay_items == 2


def test_step_weights_give_each_source_its_share() -> None:
    data = value_data()
    (step,) = plan_graph_value_steps(data, value_config())
    weights = dict(step.pointwise_weights)
    graph = {index: item.target for index, item in enumerate(data.pointwise) if item.target is not None}
    proof_graph = sum(weights[index] for index, target in graph.items() if target.source == TargetSource.PROOF_GRAPH)
    present = {target.source for target in graph.values()}
    shares = SourceShares()
    expected = shares.proof_graph / sum(shares.share(source) for source in present)
    assert proof_graph / sum(weights[index] for index in graph) == pytest.approx(expected)


def test_ranking_loss_raises_the_preferred_state() -> None:
    preferred = torch.zeros(1, requires_grad=True)
    other = torch.zeros(1, requires_grad=True)
    ranking_losses(preferred, other, 1.0).sum().backward()
    assert preferred.grad is not None and other.grad is not None
    assert (preferred.grad.item(), other.grad.item()) == pytest.approx((-0.5, 0.5))


@pytest.mark.parametrize("score", list(RankingScore))
def test_ranking_score_falls_as_the_dead_bin_rises(score: RankingScore) -> None:
    logits = torch.zeros(2, BIN_COUNT)
    logits[1, DEAD_BIN] = 2.0
    scores = ranking_scores(logits, score)
    assert scores[0] > scores[1]


def test_soft_target_loss_with_a_one_hot_target_is_the_cross_entropy() -> None:
    logits = torch.tensor([[0.5, -1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]])
    target = torch.nn.functional.one_hot(torch.tensor([2]), BIN_COUNT).float()
    expected = torch.nn.functional.cross_entropy(logits, torch.tensor([2]))
    assert soft_target_losses(logits, target).item() == pytest.approx(expected.item())


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return save_tiny_model(tmp_path_factory.mktemp("tiny") / "model")


def test_training_lowers_the_ranking_loss(tiny_model: Path, tmp_path: Path) -> None:
    config = value_config(str(tiny_model), optimization=dataclasses.replace(value_config().optimization, epochs=20))
    records: list[GraphValueStepRecord] = []
    train_graph_value_model(config, CharacterTokenizer(), 0, value_data(config), CPU, tmp_path, records.append)
    assert records[-1].ranking_loss < records[0].ranking_loss


def test_gate_scores_every_benchmark_state(tiny_model: Path, tmp_path: Path) -> None:
    config = value_config(str(tiny_model), optimization=dataclasses.replace(value_config().optimization, epochs=2))
    train_graph_value_model(config, CharacterTokenizer(), 0, value_data(config), CPU, tmp_path / "new", print)
    benchmark = value_benchmark()
    scored = run_value_gate(config, CharacterTokenizer(), 0, benchmark, str(tmp_path / "new"), "", CPU)
    assert scored.result.new.states - scored.result.new.states_without_estimate == len(benchmark.states)


def test_gate_scores_both_models_fresh(tiny_model: Path) -> None:
    scored = run_value_gate(value_config(str(tiny_model)), CharacterTokenizer(), 0, value_benchmark(), "", "", CPU)
    assert (scored.result.new.kind, scored.result.current.kind) == (EstimateKind.FRESH, EstimateKind.FRESH)


def test_gate_compares_the_same_model_with_itself_without_a_gain(tiny_model: Path) -> None:
    scored = run_value_gate(value_config(str(tiny_model)), CharacterTokenizer(), 0, value_benchmark(), "", "", CPU)
    assert scored.result.statistic.difference == 0.0


def test_gate_refuses_a_benchmark_from_value_guided_trees(tiny_model: Path) -> None:
    config = value_config(str(tiny_model), gate=GateConfig(min_lower_bound=-2.0))
    scored = run_value_gate(config, CharacterTokenizer(), 0, value_benchmark(GUIDED), "", "", CPU)
    assert not scored.result.passed


def test_gate_only_warns_about_value_guided_trees_when_configured(tiny_model: Path) -> None:
    config = value_config(str(tiny_model), gate=GateConfig(min_lower_bound=-2.0, guided_trees=GuidedTrees.WARN))
    scored = run_value_gate(config, CharacterTokenizer(), 0, value_benchmark(GUIDED), "", "", CPU)
    assert (scored.result.passed, len(scored.result.warnings)) == (True, 1)
