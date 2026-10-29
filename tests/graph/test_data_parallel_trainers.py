import dataclasses
import functools
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, expansion_texts, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")
safetensors_torch = pytest.importorskip("safetensors.torch")
distributed = pytest.importorskip("torch.distributed")
multiprocessing = pytest.importorskip("torch.multiprocessing")

from lean_search.policy.adapters import ADAPTER_WEIGHTS_FILE  # noqa: E402
from lean_search.rl.policy_data import PolicyDataConfig, PolicySequence, PolicyTree, build_policy_data  # noqa: E402
from lean_search.rl.policy_trainer import GrpoConfig, train_grpo  # noqa: E402
from lean_search.rl.training_phase import (  # noqa: E402
    PhaseInputs,
    TrainingPhaseConfig,
    label_phase_data,
    run_training_phase,
)
from lean_search.search import TreeRecord  # noqa: E402
from lean_search.training.data_parallel import Ranks, balanced_shards  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig, load_trainable_model  # noqa: E402
from lean_search.training.sft_data import TokenizedExample  # noqa: E402
from lean_search.value.graph_trainer import (  # noqa: E402
    GraphValueConfig,
    GraphValueData,
    build_graph_value_data,
    train_graph_value_model,
)
from lean_search.value.labels import LabelKind, ValueExample  # noqa: E402
from lean_search.value.ranking import RankingConfig  # noqa: E402

CPU = torch.device("cpu")
LORA = LoraSettings(rank=8, alpha=8)
STEP_RECORDS = "steps.json"
# One sequence (or value unit) per micro-batch on every rank: the bf16 forward passes then have the same shapes on one
# rank and on two, and only the order of the fp32 gradient sums differs.
OPTIMIZATION = OptimizationConfig(
    learning_rate=1e-2,
    warmup_fraction=0.0,
    minimum_learning_rate_ratio=1.0,
    micro_batch_tokens=1,
    micro_batches_per_step=64,
    gradient_checkpointing=False,
)


def policy_tree() -> TreeRecord:
    builder = GraphBuilder("⊢ x = 1")
    child = builder.child(builder.root, "⊢ y = 1", text="intro y")
    builder.failure(builder.root, text="simp at q")
    proof = builder.child(child, text="rfl")
    return builder.record(proof)


def policy_sequences() -> tuple[PolicySequence, ...]:
    record = policy_tree()
    groups = label_phase_data([record], TrainingPhaseConfig()).groups
    trees = [PolicyTree(tuple(groups), tuple(expansion_texts(record)))]
    return build_policy_data(trees, CharacterTokenizer(), PolicyDataConfig()).sequences


def policy_replay() -> list[TokenizedExample]:
    return [sequence.tokenized for sequence in policy_sequences()[:3]]


def policy_config(model: Path, published: Path, starting: Path) -> GrpoConfig:
    """One step over every sequence, with replay and a KL penalty to a reference scored apart from the old policy."""
    return GrpoConfig(
        model=str(model),
        initial_adapter=str(published),
        reference_adapter=str(starting),
        lora=LORA,
        optimization=OPTIMIZATION,
        sequences_per_step=8,
        passes_per_phase=1,
        kl_coefficient=0.1,
        replay_weight=0.5,
        replay_sequences_per_step=3,
        scoring_micro_batch_tokens=1,
    )


def goal(letter: str) -> str:
    return "⊢ " + letter * 200


def value_tree() -> TreeRecord:
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


VALUE_REPLAY = [
    ValueExample(("⊢ v",), LabelKind.EXACT, 2, 1.0, "v0", "v0/a", 0),
    ValueExample(("⊢ w",), LabelKind.DEAD, 0, 1.0, "v0", "v0/b", 0),
]


def value_config(model: Path, current: Path) -> GraphValueConfig:
    """Every unit in one step."""
    return GraphValueConfig(
        model=str(model), initial_adapter=str(current), lora=LORA, optimization=OPTIMIZATION, replay_share=0.5
    )


def value_data(config: GraphValueConfig) -> GraphValueData:
    trees = label_phase_data([value_tree()], TrainingPhaseConfig()).trees
    ranking = RankingConfig(proof_over_never_expanded_weight=0.1)
    return build_graph_value_data(trees, ranking, VALUE_REPLAY, CharacterTokenizer(), config)


def train_policy(model: Path, published: Path, starting: Path, output: Path, ranks: Ranks) -> None:
    records: list[object] = []
    config = policy_config(model, published, starting)
    train_grpo(config, 0, policy_sequences(), policy_replay(), CPU, output, records.append, ranks)
    if ranks.is_main:
        (output / STEP_RECORDS).write_text(json.dumps([dataclasses.asdict(record) for record in records]))


def train_value(model: Path, current: Path, output: Path, ranks: Ranks) -> None:
    records: list[object] = []
    config = value_config(model, current)
    train_graph_value_model(config, CharacterTokenizer(), 0, value_data(config), CPU, output, records.append, ranks)
    if ranks.is_main:
        (output / STEP_RECORDS).write_text(json.dumps([dataclasses.asdict(record) for record in records]))


def rank_worker(rank: int, world_size: int, rendezvous: str, train: Callable[[Ranks], None]) -> None:
    torch.set_num_threads(1)
    distributed.init_process_group("gloo", init_method=f"file://{rendezvous}", rank=rank, world_size=world_size)
    try:
        train(Ranks(rank, world_size))
    finally:
        distributed.destroy_process_group()


def on_ranks(world_size: int, train: Callable[[Ranks], None], rendezvous: Path) -> None:
    """In fresh processes of one thread each, so that both runs compute alike."""
    multiprocessing.spawn(rank_worker, args=(world_size, str(rendezvous), train), nprocs=world_size)


def random_adapter(model: Path, directory: Path, seed: int) -> Path:
    saved, _ = load_trainable_model(str(model), OptimizationConfig(gradient_checkpointing=False), LORA, CPU)
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for parameter in saved.parameters():
            if parameter.requires_grad:
                parameter.add_(torch.randn(parameter.shape, generator=generator).to(parameter.dtype))
    saved.save_pretrained(directory)
    return directory


@dataclasses.dataclass(frozen=True)
class Runs:
    single: Path
    parallel: Path


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return save_tiny_model(tmp_path_factory.mktemp("tiny") / "model")


@pytest.fixture(scope="module")
def policy_runs(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> Runs:
    root = tmp_path_factory.mktemp("policy")
    published = random_adapter(tiny_model, root / "published", seed=1)
    starting = random_adapter(tiny_model, root / "starting", seed=2)
    for name, world_size in (("single", 1), ("parallel", 2)):
        train = functools.partial(train_policy, tiny_model, published, starting, root / name)
        on_ranks(world_size, train, root / f"rendezvous_{name}")
    return Runs(root / "single", root / "parallel")


@pytest.fixture(scope="module")
def value_runs(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> Runs:
    root = tmp_path_factory.mktemp("value")
    current = random_adapter(tiny_model, root / "current", seed=3)
    for name, world_size in (("single", 1), ("parallel", 2)):
        on_ranks(
            world_size, functools.partial(train_value, tiny_model, current, root / name), root / f"rendezvous_{name}"
        )
    return Runs(root / "single", root / "parallel")


def adapter_difference(runs: Runs) -> float:
    single = safetensors_torch.load_file(runs.single / ADAPTER_WEIGHTS_FILE)
    parallel = safetensors_torch.load_file(runs.parallel / ADAPTER_WEIGHTS_FILE)
    assert single.keys() == parallel.keys()
    return max((single[key] - parallel[key]).abs().max().item() for key in single)


def step_records(directory: Path) -> list[dict[str, float]]:
    return json.loads((directory / STEP_RECORDS).read_text())


def test_two_ranks_take_the_single_process_policy_step(policy_runs: Runs) -> None:
    assert adapter_difference(policy_runs) < 1e-5


@pytest.mark.parametrize("field", ["loss", "policy_loss", "kl_to_reference", "replay_nll", "gradient_norm"])
def test_two_ranks_report_the_single_process_policy_step(policy_runs: Runs, field: str) -> None:
    assert step_records(policy_runs.parallel)[0][field] == pytest.approx(
        step_records(policy_runs.single)[0][field], rel=1e-4
    )


def test_two_ranks_take_the_single_process_value_step(value_runs: Runs) -> None:
    assert adapter_difference(value_runs) < 1e-5


@pytest.mark.parametrize("field", ["pointwise_loss", "ranking_loss", "pair_accuracy", "gradient_norm", "states"])
def test_two_ranks_report_the_single_process_value_step(value_runs: Runs, field: str) -> None:
    assert step_records(value_runs.parallel)[0][field] == pytest.approx(
        step_records(value_runs.single)[0][field], rel=1e-4
    )


def test_the_shards_balance_tokens() -> None:
    assert balanced_shards([0, 1, 2, 3], [10, 1, 1, 8], 2) == [(0,), (1, 2, 3)]


def test_one_shard_keeps_every_index_in_order() -> None:
    assert balanced_shards([3, 1, 2], [5, 9, 1, 7], 1) == [(3, 1, 2)]


@dataclasses.dataclass(frozen=True)
class RankValueOutcome:
    trees: int
    labelled: bool


def value_phase(model: Path, output: Path, ranks: Ranks) -> None:
    """A value-only phase on a window of two trees; each rank writes what its outcome holds."""
    config = TrainingPhaseConfig(value=GraphValueConfig(model=str(model), lora=LORA, optimization=OPTIMIZATION))
    record = value_tree()
    inputs = PhaseInputs(records=[record], value_records=[record, record])
    tokenizer = CharacterTokenizer()
    outcome = run_training_phase(config, inputs, None, tokenizer, CPU, output / "phase", ranks)
    assert outcome.value is not None
    seen = RankValueOutcome(outcome.value.trees, outcome.value.labels is not None)
    (output / f"rank_{ranks.rank}.json").write_text(json.dumps(dataclasses.asdict(seen)))


@pytest.fixture(scope="module")
def value_phase_ranks(tiny_model: Path, tmp_path_factory: pytest.TempPathFactory) -> list[RankValueOutcome]:
    root = tmp_path_factory.mktemp("value_phase")
    on_ranks(2, functools.partial(value_phase, tiny_model, root), root / "rendezvous")
    return [RankValueOutcome(**json.loads((root / f"rank_{rank}.json").read_text())) for rank in range(2)]


def test_every_rank_trains_on_the_whole_value_window(value_phase_ranks: list[RankValueOutcome]) -> None:
    assert [outcome.trees for outcome in value_phase_ranks] == [2, 2]


def test_only_the_main_rank_reports_the_value_labels(value_phase_ranks: list[RankValueOutcome]) -> None:
    assert [outcome.labelled for outcome in value_phase_ranks] == [True, False]
