"""The persistent training job's ranks on the CPU with a tiny model: phases with resident models train what a fresh
per-phase job trains, the merge handed off equals the per-phase merge, and preparation during sampling builds the
phase's data."""

import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from graph_trees import GraphBuilder
from tiny_models import CharacterTokenizer, expansion_texts, save_tiny_model

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

import safetensors.torch  # noqa: E402

from lean_search.expert_iteration.toml_text import toml_text  # noqa: E402
from lean_search.policy.adapters import (  # noqa: E402
    ADAPTER_WEIGHTS_FILE,
    PremergedWeights,
    create_zero_adapter,
    handoff_directory,
    premerge_adapter,
    premerged_directory,
    read_premerged,
)
from lean_search.rl.loop import read_phase_outcome  # noqa: E402
from lean_search.rl.loop_services import running_start_ticks  # noqa: E402
from lean_search.rl.policy_data import PolicyDataConfig, build_policy_data, combined_policy_data  # noqa: E402
from lean_search.rl.policy_trainer import GrpoConfig  # noqa: E402
from lean_search.rl.resident_trainer import (  # noqa: E402
    LoopProcess,
    PhasePreparation,
    ResidentInputs,
    TrainerRank,
    WindowPreparation,
)
from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommand, TrainerCommandKind  # noqa: E402
from lean_search.rl.training_phase import (  # noqa: E402
    PhaseInputs,
    PhaseOutcome,
    TrainingPhaseConfig,
    label_phase_data,
    label_value_trees,
    run_training_phase,
)
from lean_search.rl.tree_store import TreeStore  # noqa: E402
from lean_search.rl.tree_summary import TreeSummary  # noqa: E402
from lean_search.search import TreeRecord, read_tree  # noqa: E402
from lean_search.training.data_parallel import SINGLE_PROCESS  # noqa: E402
from lean_search.training.resident import HostDirectories, build_resident_model  # noqa: E402
from lean_search.training.sft import LoraSettings, OptimizationConfig  # noqa: E402
from lean_search.value.graph_trainer import GraphValueConfig  # noqa: E402

CPU = torch.device("cpu")
LORA = LoraSettings(rank=8, alpha=8)
OPTIMIZATION = OptimizationConfig(
    learning_rate=1e-2, warmup_fraction=0.0, micro_batch_tokens=65536, gradient_checkpointing=False
)


def phase_tree(statement: str = "r") -> TreeRecord:
    builder = GraphBuilder("⊢ " + statement * 100, root_value=4.0)
    child = builder.child(builder.root, "⊢ " + "p" * 100, value=2.0, text="intro y")
    builder.failure(builder.root, text="simp at q")
    dead = builder.child(builder.root, "⊢ " + "d" * 100, value=3.0, text="norm_num")
    builder.failure(dead, text="linarith")
    record = builder.record(builder.child(child, text="rfl"))
    return dataclasses.replace(record, expansions=tuple(expansion_texts(record)))


def without_none(table: Mapping[str, object]) -> dict[str, object]:
    return {
        key: without_none(value) if isinstance(value, Mapping) else value
        for key, value in table.items()
        if value is not None
    }


def phase_config(
    model: Path, initial_adapter: str, value: bool = False, optimization: OptimizationConfig = OPTIMIZATION
) -> TrainingPhaseConfig:
    policy = GrpoConfig(
        model=str(model),
        initial_adapter=initial_adapter,
        lora=LORA,
        optimization=optimization,
        passes_per_phase=1,
        scoring_micro_batch_tokens=65536,
    )
    value_config = GraphValueConfig(
        model=str(model), initial_adapter=initial_adapter, lora=LORA, optimization=optimization
    )
    return TrainingPhaseConfig(policy=policy, value=value_config if value else None)


def adapter_weights(adapter: str) -> dict[str, torch.Tensor]:
    return safetensors.torch.load_file(Path(adapter) / ADAPTER_WEIGHTS_FILE)


def same_tensors(first: Mapping[str, torch.Tensor], second: Mapping[str, torch.Tensor]) -> bool:
    return first.keys() == second.keys() and all(torch.equal(first[key], second[key]) for key in first)


def merged_weights(directory: Path) -> dict[str, torch.Tensor]:
    weights: dict[str, torch.Tensor] = {}
    for path in sorted(directory.glob("*.safetensors")):
        weights |= safetensors.torch.load_file(path)
    return weights


class ResidentJob:
    """One rank of the persistent job on the CPU, driven by commands as the loop sends them."""

    def __init__(self, root: Path, trees: Path) -> None:
        self.root = root
        self.trees = trees
        self.sequence = 0
        channel = TrainerChannel(root / "channel")
        channel.clear()
        start_ticks = running_start_ticks(os.getpid())
        assert start_ticks is not None
        self.host = HostDirectories(root / "host")
        self.rank = TrainerRank(
            channel,
            self.host,
            ResidentInputs(),
            CPU,
            SINGLE_PROCESS,
            LoopProcess(os.getpid(), start_ticks),
            print,
            lambda model: CharacterTokenizer(),
        )

    def train(self, phase: int, config: TrainingPhaseConfig) -> PhaseOutcome:
        self.sequence += 1
        config_path = self.root / f"phase_{phase}.toml"
        config_path.write_text(toml_text(without_none(dataclasses.asdict(config))), encoding="utf-8")
        output = self.root / f"phase_{phase}"
        value_trees = (str(self.trees),) if config.value is not None else ()
        command = TrainerCommand(
            self.sequence, TrainerCommandKind.TRAIN, phase, str(config_path), str(self.trees), value_trees, str(output)
        )
        self.rank.train(command)
        return read_phase_outcome(output / "phase.json")


@dataclasses.dataclass(frozen=True)
class TwoPhases:
    model: Path
    fresh: tuple[PhaseOutcome, PhaseOutcome]
    resident: tuple[PhaseOutcome, PhaseOutcome]
    job: ResidentJob


def write_trees(directory: Path, records: list[TreeRecord]) -> Path:
    store = TreeStore(directory)
    for record in records:
        store.add(record, 1, 0, None, TreeSummary())
    return store.phase_directory(1)


@pytest.fixture(scope="module")
def two_phases(tmp_path_factory: pytest.TempPathFactory) -> TwoPhases:
    """Two policy phases (the second continuing the first's adapter) by fresh per-phase jobs and by one resident
    rank; the first merges its adapter (per phase beside it, resident into the handoff)."""
    root = tmp_path_factory.mktemp("two_phases")
    model = save_tiny_model(root / "model")
    create_zero_adapter(str(model), root / "start", LORA.rank)
    record = phase_tree()
    trees = write_trees(root / "trees", [record])
    tokenizer = CharacterTokenizer()
    first = run_training_phase(
        phase_config(model, str(root / "start")),
        PhaseInputs(records=[record]),
        tokenizer,
        None,
        CPU,
        root / "fresh_1",
        merge_adapters=True,
    )
    assert first.policy is not None
    second = run_training_phase(
        phase_config(model, first.policy.adapter), PhaseInputs(records=[record]), tokenizer, None, CPU, root / "fresh_2"
    )
    job = ResidentJob(root / "resident", trees)
    resident_first = job.train(1, phase_config(model, str(root / "start")))
    assert resident_first.policy is not None
    resident_second = job.train(2, phase_config(model, resident_first.policy.adapter))
    return TwoPhases(model, (first, second), (resident_first, resident_second), job)


@pytest.mark.parametrize("phase", [0, 1], ids=["first phase", "second phase"])
def test_a_resident_phase_trains_the_adapter_a_fresh_job_trains(two_phases: TwoPhases, phase: int) -> None:
    fresh = two_phases.fresh[phase].policy
    resident = two_phases.resident[phase].policy
    assert fresh is not None and resident is not None
    assert same_tensors(adapter_weights(fresh.adapter), adapter_weights(resident.adapter))


def test_the_handed_off_merge_equals_the_per_phase_merge(two_phases: TwoPhases) -> None:
    fresh = two_phases.fresh[0].policy
    resident = two_phases.resident[0].policy
    assert fresh is not None and resident is not None
    handed_off = handoff_directory(two_phases.job.host.handoff, resident.adapter)
    expected = merged_weights(premerged_directory(Path(fresh.adapter)))
    assert same_tensors(merged_weights(handed_off), expected)


def test_the_handed_off_merge_names_its_base_and_adapter(two_phases: TwoPhases) -> None:
    resident = two_phases.resident[1].policy
    assert resident is not None
    handed_off = handoff_directory(two_phases.job.host.handoff, resident.adapter)
    assert read_premerged(handed_off) == PremergedWeights(str(two_phases.model), resident.adapter)


def test_the_resident_phase_counts_the_trees_and_groups(two_phases: TwoPhases) -> None:
    fresh, resident = two_phases.fresh[1], two_phases.resident[1]
    assert (resident.trees, resident.groups) == (fresh.trees, fresh.groups)


def test_the_resident_phase_records_its_parking(two_phases: TwoPhases) -> None:
    assert two_phases.resident[1].timings.park_seconds > 0


def test_the_resident_models_are_built_once(two_phases: TwoPhases) -> None:
    assert two_phases.resident[1].timings.build_seconds < two_phases.resident[0].timings.build_seconds


def test_a_resident_value_phase_trains_the_value_adapter_a_fresh_job_trains(tmp_path: Path) -> None:
    model = save_tiny_model(tmp_path / "model")
    create_zero_adapter(str(model), tmp_path / "start", LORA.rank)
    record = phase_tree()
    trees = write_trees(tmp_path / "trees", [record])
    config = phase_config(model, str(tmp_path / "start"), value=True)
    tokenizer = CharacterTokenizer()
    inputs = PhaseInputs(records=[record], value_records=[record])
    fresh = run_training_phase(config, inputs, tokenizer, tokenizer, CPU, tmp_path / "fresh")
    resident = ResidentJob(tmp_path / "resident", trees).train(1, config)
    assert fresh.value is not None and resident.value is not None
    assert same_tensors(adapter_weights(fresh.value.adapter), adapter_weights(resident.value.adapter))


@pytest.fixture(scope="module")
def compiled_phases(tmp_path_factory: pytest.TempPathFactory) -> list[PhaseOutcome]:
    """Three phases with compiled layers, as the loop runs them: each continues the last adapter, and from the second
    on the starting adapter's weights are swapped in place to score the KL reference, then the trained ones put
    back."""
    root = tmp_path_factory.mktemp("compiled")
    model = save_tiny_model(root / "model")
    start = root / "start"
    create_zero_adapter(str(model), start, LORA.rank)
    job = ResidentJob(root / "resident", write_trees(root / "trees", [phase_tree()]))
    optimization = dataclasses.replace(OPTIMIZATION, compile_layers=True)
    outcomes: list[PhaseOutcome] = []
    adapter = str(start)
    for phase in (1, 2, 3):
        config = phase_config(model, adapter, optimization=optimization)
        assert config.policy is not None
        config = dataclasses.replace(config, policy=dataclasses.replace(config.policy, reference_adapter=str(start)))
        outcomes.append(job.train(phase, config))
        policy = outcomes[-1].policy
        assert policy is not None
        adapter = policy.adapter
    return outcomes


def test_the_first_resident_phase_compiles_the_layers(compiled_phases: list[PhaseOutcome]) -> None:
    assert compiled_phases[0].timings.compiled_graphs > 0


@pytest.mark.parametrize("phase", [1, 2], ids=["second phase", "third phase"])
def test_a_later_resident_phase_compiles_nothing(compiled_phases: list[PhaseOutcome], phase: int) -> None:
    assert compiled_phases[phase].timings.compiled_graphs == 0


def test_preparation_while_sampling_builds_the_phases_policy_data(tmp_path: Path) -> None:
    records = [phase_tree("r"), phase_tree("s")]
    store = TreeStore(tmp_path / "trees")
    store.add(records[0], 1, 0, None, TreeSummary())
    config = TrainingPhaseConfig(policy=GrpoConfig(model="unused"))
    config_text = toml_text(without_none(dataclasses.asdict(config)))
    tokenizer = CharacterTokenizer()
    preparation = PhasePreparation(store.phase_directory(1), config_text, tokenizer)
    store.add(records[1], 1, 0, None, TreeSummary())
    prepared = combined_policy_data(preparation.finish())
    expected = build_policy_data(label_phase_data(records, config).policy_trees, tokenizer, PolicyDataConfig())
    assert prepared == expected


def test_preparation_while_sampling_labels_the_value_window(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "trees")
    store.add(phase_tree("r"), 1, 0, None, TreeSummary())
    config = TrainingPhaseConfig(value=GraphValueConfig(model="unused"))
    preparation = WindowPreparation(
        (store.phase_directory(1), store.phase_directory(2)), toml_text(without_none(dataclasses.asdict(config)))
    )
    store.add(phase_tree("s"), 2, 0, None, TreeSummary())
    expected = label_value_trees(
        [read_tree(tmp_path / "trees" / entry.file, texts=False) for entry in store.entries], config
    )
    assert tuple(tree for trees in preparation.finish() for tree in trees) == expected


def sampled_by_version(record: TreeRecord, versions: Mapping[int, int]) -> TreeRecord:
    """Each node's expansion sampled by the version given for it (by node id), the others by version 0."""
    expansions = tuple(
        dataclasses.replace(expansion, policy_version=versions.get(expansion.node_id, 0))
        for expansion in record.expansions
    )
    return dataclasses.replace(record, expansions=expansions)


EXCLUDING_VERSION_1 = TrainingPhaseConfig(excluded_policy_versions=(1,))


def group_nodes(record: TreeRecord, config: TrainingPhaseConfig) -> list[int]:
    return [group.node_id for group in label_phase_data([record], config).groups]


def test_the_groups_an_excluded_version_sampled_leave_the_policy_data() -> None:
    record = sampled_by_version(phase_tree(), {0: 1})
    assert 0 not in group_nodes(record, EXCLUDING_VERSION_1)


def test_a_tree_an_excluded_version_sampled_in_part_keeps_its_other_groups() -> None:
    record = sampled_by_version(phase_tree(), {0: 1})
    kept = group_nodes(sampled_by_version(phase_tree(), {}), TrainingPhaseConfig())
    assert group_nodes(record, EXCLUDING_VERSION_1) == [node for node in kept if node != 0]


def test_a_tree_an_excluded_version_sampled_leaves_the_value_window() -> None:
    records = [sampled_by_version(phase_tree("r"), {1: 1}), sampled_by_version(phase_tree("s"), {})]
    window = label_value_trees(records, EXCLUDING_VERSION_1)
    assert [tree.record.nodes[0].goals for tree in window] == [records[1].nodes[0].goals]


def test_the_value_windows_preparation_drops_a_tree_an_excluded_version_sampled(tmp_path: Path) -> None:
    store = TreeStore(tmp_path / "trees")
    store.add(sampled_by_version(phase_tree("r"), {1: 1}), 1, 1, None, TreeSummary())
    config = TrainingPhaseConfig(value=GraphValueConfig(model="unused"), excluded_policy_versions=(1,))
    preparation = WindowPreparation((store.phase_directory(1),), toml_text(without_none(dataclasses.asdict(config))))
    assert preparation.finish() == [()]


cuda_only = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a GPU (run on the node)")


@cuda_only
def test_parking_leaves_nothing_of_the_model_on_the_gpu(tmp_path: Path) -> None:
    model = save_tiny_model(tmp_path / "model")
    create_zero_adapter(str(model), tmp_path / "start", LORA.rank)
    device = torch.device("cuda")
    resident = build_resident_model(
        str(model),
        OPTIMIZATION,
        LORA,
        str(tmp_path / "start"),
        tmp_path / "host" / "policy.bin",
        device,
        SINGLE_PROCESS,
    )
    before = torch.cuda.memory_allocated(device)
    resident.unpark()
    resident.park()
    assert torch.cuda.memory_allocated(device) == before


@cuda_only
def test_the_merge_handed_off_on_the_gpu_equals_the_per_phase_gpu_merge(tmp_path: Path) -> None:
    model = save_tiny_model(tmp_path / "model")
    adapter = tmp_path / "phase" / "adapter"
    create_zero_adapter(str(model), adapter, LORA.rank)
    device = torch.device("cuda")
    resident = build_resident_model(
        str(model), OPTIMIZATION, LORA, str(adapter), tmp_path / "host" / "policy.bin", device, SINGLE_PROCESS
    )
    resident.write_merged(PremergedWeights(str(model), str(adapter)), tmp_path / "handoff")
    premerge_adapter(str(model), adapter, device)
    assert same_tensors(merged_weights(tmp_path / "handoff"), merged_weights(premerged_directory(adapter)))
