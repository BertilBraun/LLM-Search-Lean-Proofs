"""A value phase on two gloo ranks (CPU, tiny model), by the persistent job's ranks and by the per-phase job: the merges
they leave for the servers hold the merged weights. transformers writes checkpoint weights only on distributed rank 0,
so a merge on another rank would leave a directory with its marker and no weights."""

import dataclasses
import functools
import os
from pathlib import Path

import pytest
from test_data_parallel_trainers import on_ranks
from test_resident_trainer import merged_weights, phase_config, phase_tree, same_tensors, without_none, write_trees
from tiny_models import CharacterTokenizer, save_tiny_model

torch = pytest.importorskip("torch")

from lean_search.expert_iteration.toml_text import toml_text  # noqa: E402
from lean_search.policy.adapters import (  # noqa: E402
    create_zero_adapter,
    handoff_directory,
    merge_adapter,
    premerged_directory,
)
from lean_search.rl.loop import read_phase_outcome  # noqa: E402
from lean_search.rl.loop_services import running_start_ticks  # noqa: E402
from lean_search.rl.resident_trainer import LoopProcess, ResidentInputs, TrainerRank, parse_phase_config  # noqa: E402
from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommand, TrainerCommandKind  # noqa: E402
from lean_search.rl.training_phase import PhaseInputs, PhaseOutcome, run_training_phase  # noqa: E402
from lean_search.training.data_parallel import Ranks  # noqa: E402
from lean_search.training.resident import HostDirectories  # noqa: E402

CPU = torch.device("cpu")
KINDS = ("policy", "value")


@dataclasses.dataclass(frozen=True)
class RankRuns:
    root: Path
    model: Path

    @property
    def host(self) -> HostDirectories:
        return HostDirectories(self.root / "host")

    def outcome(self, job: str) -> PhaseOutcome:
        return read_phase_outcome(self.root / job / "phase.json")

    def adapter(self, job: str, kind: str) -> str:
        outcome = self.outcome(job)
        trained = outcome.policy if kind == "policy" else outcome.value
        assert trained is not None
        return trained.adapter

    def merge(self, job: str, kind: str) -> Path:
        """Where the job left the kind's new adapter merged: in host memory, or beside the adapter."""
        adapter = self.adapter(job, kind)
        return (
            handoff_directory(self.host.handoff, adapter) if job == "resident" else premerged_directory(Path(adapter))
        )


def value_phase_on_ranks(config_path: Path, trees: Path, root: Path, ranks: Ranks) -> None:
    """The persistent job's ranks train the phase and hand off its merges; then the per-phase job merges its own."""
    loop_process = LoopProcess(os.getppid(), running_start_ticks(os.getppid()) or 0)
    rank = TrainerRank(
        TrainerChannel(root / "channel"),
        HostDirectories(root / "host"),
        ResidentInputs(),
        CPU,
        ranks,
        loop_process,
        print,
        lambda model: CharacterTokenizer(),
    )
    command = TrainerCommand(
        1, TrainerCommandKind.TRAIN, 1, str(config_path), str(trees), (str(trees),), str(root / "resident")
    )
    rank.train(command)
    config = parse_phase_config(config_path.read_text(encoding="utf-8"))
    record = phase_tree()
    tokenizer = CharacterTokenizer()
    inputs = PhaseInputs(records=[record], value_records=[record])
    run_training_phase(config, inputs, tokenizer, tokenizer, CPU, root / "per_phase", ranks, merge_adapters=True)


@pytest.fixture(scope="module")
def rank_runs(tmp_path_factory: pytest.TempPathFactory) -> RankRuns:
    root = tmp_path_factory.mktemp("merges_on_ranks")
    model = save_tiny_model(root / "model")
    create_zero_adapter(str(model), root / "start", 8)
    trees = write_trees(root / "trees", [phase_tree()])
    config_path = root / "phase.toml"
    config = phase_config(model, str(root / "start"), value=True)
    config_path.write_text(toml_text(without_none(dataclasses.asdict(config))), encoding="utf-8")
    TrainerChannel(root / "channel").clear()
    on_ranks(2, functools.partial(value_phase_on_ranks, config_path, trees, root), root / "rendezvous")
    return RankRuns(root, model)


@pytest.mark.parametrize("job", ["resident", "per_phase"])
@pytest.mark.parametrize("kind", KINDS)
def test_a_merge_on_two_ranks_holds_its_weights(rank_runs: RankRuns, job: str, kind: str) -> None:
    assert list(rank_runs.merge(job, kind).glob("*.safetensors"))


@pytest.mark.parametrize("kind", KINDS)
def test_a_merge_handed_off_by_two_ranks_equals_its_adapter_merged_alone(
    rank_runs: RankRuns, kind: str, tmp_path: Path
) -> None:
    merge_adapter(str(rank_runs.model), Path(rank_runs.adapter("resident", kind)), tmp_path / "merged")
    assert same_tensors(merged_weights(rank_runs.merge("resident", kind)), merged_weights(tmp_path / "merged"))
