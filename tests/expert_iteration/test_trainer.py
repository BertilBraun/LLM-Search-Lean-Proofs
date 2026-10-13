import dataclasses
import datetime
import json
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest
from expert_trees import TreeBuilder
from loop_fixtures import attempt, write_shard

from lean_search.corpora.records import DataSplit, TracedStep, write_jsonl
from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.digests import (
    DigestConfig,
    VersionedValueExample,
    digest_new_shards,
    digested,
    read_jumps,
    read_policy,
    tree_value_samples,
)
from lean_search.expert_iteration.loop_config import (
    BufferConfig,
    EvaluationLoopConfig,
    InitialModels,
    LoopConfig,
    SearchServiceConfig,
    ServerEndpoint,
    ServingConfig,
    ThinkingConfig,
    TrainingConfig,
)
from lean_search.expert_iteration.preferences import ValueJumpConfig
from lean_search.expert_iteration.replay_buffer import FifoBuffer, ValueSample
from lean_search.expert_iteration.serving import (
    LoopPaths,
    MergedPublisher,
    ModelVersion,
    StopStartRelease,
    read_current,
    record_published,
    write_json_atomically,
)
from lean_search.expert_iteration.shards import Decision, ShardWriter
from lean_search.expert_iteration.thinking import StepReasoning, ThinkingItem, TreeReasoning
from lean_search.expert_iteration.trainer import (
    BufferInflows,
    PhaseData,
    PhaseStage,
    PhaseState,
    PhaseTrainer,
    Progress,
    next_stage,
    phase_trigger,
    policy_settings,
    progress_since,
    read_inflows,
    read_phase_state,
    training_config_text,
    value_gate,
)
from lean_search.search import StepSource
from lean_search.training.dpo_data import read_pairs
from lean_search.training.sft_data import SourceWeight
from lean_search.value.labels import LabelKind, TreeLabelConfig, ValueExample, read_examples, write_examples

TRAINING = TrainingConfig(new_proofs=400, min_minutes=20.0, max_minutes=60.0, minimum_new_proofs=20)
PUBLISHED_AT = "2026-10-12T10:00:00+00:00"
JUMPS = ValueJumpConfig(gate_minimum_states=3)
DIGESTS = DigestConfig(PreferenceConfig(), False, JUMPS, TreeLabelConfig(), 16)


@pytest.mark.parametrize(
    ("progress", "trigger"),
    [
        (Progress(10.0, 900, 400, 450), None),
        (Progress(25.0, 900, 400, 450), "proofs"),
        (Progress(61.0, 300, 30, 30), "time"),
        (Progress(61.0, 300, 10, 10), None),
    ],
)
def test_phase_trigger(progress: Progress, trigger: str | None) -> None:
    assert phase_trigger(progress, TRAINING) == trigger


def test_progress_counts_harvested_proofs_since_the_publish(tmp_path: Path) -> None:
    writer = ShardWriter(tmp_path, max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.x", proved=True, decision=Decision.SOLVED, finished_at="2026-10-12T09:00:00+00:00"), None)
    harvested = attempt("a.y", proved=True, decision=Decision.SOLVED, finished_at="2026-10-12T10:30:00+00:00")
    writer.write(dataclasses.replace(harvested, harvested_proofs=2), None)
    now = datetime.datetime.fromisoformat("2026-10-12T11:00:00+00:00")
    assert progress_since(tmp_path, PUBLISHED_AT, now) == Progress(60.0, 1, 1, 3)


def estimate(kind: LabelKind, steps: int, value: float) -> VersionedValueExample:
    example = ValueExample((f"⊢ {kind} {steps} {value}",), kind, steps, 1.0, "a", "a.x", 0)
    return VersionedValueExample(1, example, value)


def test_the_gate_opens_for_a_value_model_that_ranks_well() -> None:
    values = [estimate(LabelKind.EXACT, steps, steps + 0.2) for steps in (1, 2, 3, 4)]
    values += [estimate(LabelKind.DEAD, 0, 14.0), estimate(LabelKind.DEAD, 0, 12.0)]
    assert value_gate(values, JUMPS).open


def test_the_gate_stays_closed_when_dead_ends_look_close() -> None:
    values = [estimate(LabelKind.EXACT, steps, steps + 0.2) for steps in (1, 2, 3, 4)]
    values += [estimate(LabelKind.DEAD, 0, 1.0), estimate(LabelKind.DEAD, 0, 1.5)]
    assert not value_gate(values, JUMPS).open


def test_the_gate_stays_closed_without_enough_exact_states() -> None:
    values = [estimate(LabelKind.EXACT, 1, 1.0), estimate(LabelKind.DEAD, 0, 12.0)]
    assert not value_gate(values, JUMPS).open


def test_training_configs_get_the_phase_data_and_initial_adapter() -> None:
    text = training_config_text('model = "m"\n\n[optimization]\nlearning_rate = 1e-05\n', "loop/phase", "/adapter")
    assert tomllib.loads(text) == {
        "model": "m",
        "data": "loop/phase",
        "initial_adapter": "/adapter",
        "optimization": {"learning_rate": 1e-05},
    }


def test_stages_run_in_order() -> None:
    assert [next_stage(stage) for stage in (PhaseStage.PAUSE, PhaseStage.TRAIN, PhaseStage.RESUME)] == [
        PhaseStage.COMPRESS,
        PhaseStage.PUBLISH,
        PhaseStage.DONE,
    ]


def test_the_phase_state_reads_back(tmp_path: Path) -> None:
    paths = LoopPaths(tmp_path, tmp_path, "loop")
    state = PhaseState(3, PhaseStage.TRAIN, "proofs", PUBLISHED_AT, "", "", None)
    write_json_atomically(paths.phase_state, state)
    assert read_phase_state(paths) == state


def test_value_samples_of_a_tree_are_capped_with_exact_labels_first() -> None:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    node = builder.root
    for index in range(5):
        node = builder.child(node, f"⊢ step {index}")
        builder.child(node, f"⊢ side {index}")
        dead = builder.child(node, f"⊢ dead {index}")
        builder.failure(dead, "simp")
    record = builder.record(builder.child(node))
    config = DigestConfig(PreferenceConfig(), False, JUMPS, TreeLabelConfig(), 8)
    kinds = [sample.example.kind for sample in tree_value_samples(record, 1, config)]
    assert kinds == [LabelKind.EXACT] * 6 + [LabelKind.DEAD] * 2


def test_digests_keep_value_jump_pairs_apart(tmp_path: Path) -> None:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    near = builder.child(builder.root, "⊢ near", step="near step")
    far = builder.child(builder.root, "⊢ far", step="far step")
    near.value_estimate, far.value_estimate = 1.0, 6.0
    writer = ShardWriter(tmp_path / "shards", max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.t"), builder.record())
    writer.close()
    digest_new_shards(tmp_path / "shards", tmp_path / "digests", DIGESTS)
    (digest,) = digested(tmp_path / "digests")
    assert ([pair.pair.rejected for pair in read_jumps(digest)], list(read_policy(digest))) == (["far step"], [])


def test_automation_only_proofs_give_no_policy_samples(tmp_path: Path) -> None:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    builder.failure(builder.root, "exact foo")
    proved = builder.child(builder.root, step="norm_num", source=StepSource.AUTOMATION, log_probability=None)
    writer = ShardWriter(tmp_path / "shards", max_attempts=10, max_seconds=1e9)
    writer.write(attempt("a.t", proved=True, decision=Decision.SOLVED), builder.record(proved))
    writer.close()
    (summary,) = digest_new_shards(tmp_path / "shards", tmp_path / "digests", DIGESTS)
    assert (summary.proofs, summary.policy_proofs, summary.policy_samples) == (1, 0, 0)


def create_directory(adapter: str, output_directory: Path) -> None:
    output_directory.mkdir(parents=True)


def loop_config(compress_reasoning: bool = False) -> LoopConfig:
    servers = (
        ServerEndpoint("gpu0", 0, "http://127.0.0.1:8100/v1"),
        ServerEndpoint("gpu1", 1, "http://127.0.0.1:8101/v1"),
    )
    return LoopConfig(
        name="loop",
        initial=InitialModels("/policy", "/value"),
        serving=ServingConfig("base", "base", servers[:1], servers[1:]),
        search=SearchServiceConfig("search.toml"),
        training=TrainingConfig(
            seed="test",
            held_out_fraction=0.0,
            policy_buffer=BufferConfig(initial_capacity=6, minimum_capacity=4, capacity_phases=3.5, reuse=1.0),
            value_buffer=BufferConfig(initial_capacity=50, minimum_capacity=10, capacity_phases=3.5, reuse=1.0),
            traced_sources=(SourceWeight("lean_workbook", 1.0),),
            value_jumps=JUMPS,
            compress_reasoning=compress_reasoning,
        ),
        evaluation=EvaluationLoopConfig("evaluation.toml"),
    )


def traced_step(number: int, split: DataSplit) -> TracedStep:
    goals = (f"⊢ {number} = {number}",)
    return TracedStep(
        "lean_workbook", f"lw/{number}", f"s{number}", split, "", "", 0, 1, 1, goals, "rfl", (), (), 0, 0.0
    )


def phase_trainer(tmp_path: Path) -> tuple[LoopPaths, PhaseTrainer]:
    config = loop_config()
    paths = LoopPaths(tmp_path / "runs", tmp_path / "data", config.name)
    write_jsonl(paths.data_root / "traced" / "steps_train.jsonl", [traced_step(n, DataSplit.TRAIN) for n in range(20)])
    replay = [ValueExample((f"⊢ replay {n}",), LabelKind.EXACT, 1, 1.0, "traced", f"r{n}", 0) for n in range(100)]
    write_examples(paths.data_root / "value" / "v0" / "train.jsonl", replay)
    write_examples(paths.data_root / "value" / "v0" / "validation.jsonl", replay[:5])
    record_published(paths, ModelVersion(0, "/policy", "/value", PUBLISHED_AT, "initial"))
    write_shard(paths.shards, 0, ["a.1", "a.2", "a.3"], solved={"a.1", "a.2"})
    publisher = MergedPublisher(config.serving, tmp_path / "weights", create_directory)
    trainer = PhaseTrainer(config, paths, publisher, StopStartRelease(publisher), tmp_path / "checkpoints", print, True)
    return paths, trainer


def built_phase(tmp_path: Path) -> tuple[LoopPaths, PhaseData]:
    paths, trainer = phase_trainer(tmp_path)
    return paths, trainer.build_data(1)


def test_a_phase_trains_on_as_many_policy_samples_as_it_added(tmp_path: Path) -> None:
    paths, data = built_phase(tmp_path)
    trained = list(read_pairs(paths.phase_data(1) / "policy" / "train.jsonl"))
    assert (data.policy.added, len(trained)) == (2, 2)


def test_the_policy_buffer_starts_with_dataset_steps(tmp_path: Path) -> None:
    _, data = built_phase(tmp_path)
    assert (data.policy.capacity, data.policy.dataset_share) == (7, 5 / 7)


def test_the_value_buffer_takes_the_new_labels(tmp_path: Path) -> None:
    paths, data = built_phase(tmp_path)
    trained = list(read_examples(paths.phase_data(1) / "value" / "train.jsonl"))
    assert (data.value.added, len(trained)) == (6, 6)


def test_the_inflows_are_recorded_for_the_next_phase(tmp_path: Path) -> None:
    paths, _ = built_phase(tmp_path)
    assert read_inflows(paths) == BufferInflows(2.0, 6.0)


def test_the_phase_data_is_written_once(tmp_path: Path) -> None:
    paths, data = built_phase(tmp_path)
    assert json.loads((paths.phase_data(1) / "data.json").read_text(encoding="utf-8"))["new_proofs"] == data.new_proofs


def test_a_stored_buffer_larger_than_the_initial_capacity_loads_whole(tmp_path: Path) -> None:
    _, trainer = phase_trainer(tmp_path)
    data = trainer.build_data(1)
    assert len(trainer.load_policy_buffer()) == data.policy.size == 7


class RecordingRelease:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def release(self, server: ServerEndpoint) -> None:
        self.events.append(f"release {server.name}")

    async def restore(self, server: ServerEndpoint, version: ModelVersion) -> None:
        self.events.append(f"restore {server.name} v{version.version}")


class RecordingSearches:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def pause(self) -> None:
        self.events.append("pause")

    async def resume(self, rescore: bool) -> None:
        self.events.append(f"resume rescore={rescore}")


def idle_trainer(tmp_path: Path, events: list[str]) -> tuple[LoopPaths, PhaseTrainer]:
    """A loop without new shards: its phases train nothing and publish the same adapters."""
    config = loop_config()
    paths = LoopPaths(tmp_path / "runs", tmp_path / "data", config.name)
    write_jsonl(paths.data_root / "traced" / "steps_train.jsonl", [traced_step(n, DataSplit.TRAIN) for n in range(4)])
    write_examples(paths.data_root / "value" / "v0" / "train.jsonl", [])
    write_examples(paths.data_root / "value" / "v0" / "validation.jsonl", [])
    record_published(paths, ModelVersion(0, "/policy", "/value", PUBLISHED_AT, "initial"))
    publisher = MergedPublisher(config.serving, tmp_path / "weights", create_directory)
    return paths, PhaseTrainer(
        config, paths, publisher, RecordingRelease(events), tmp_path / "checkpoints", print, True
    )


async def test_a_phase_pauses_frees_the_gpus_publishes_and_resumes(tmp_path: Path) -> None:
    events: list[str] = []
    _, trainer = idle_trainer(tmp_path, events)
    await trainer.run_phase(
        PhaseState(1, PhaseStage.PAUSE, "time", PUBLISHED_AT, "", "", None), RecordingSearches(events)
    )
    assert events == [
        "pause",
        "release gpu0",
        "release gpu1",
        "restore gpu0 v1",
        "restore gpu1 v1",
        "resume rescore=False",
    ]


async def test_an_interrupted_phase_continues_at_its_stage(tmp_path: Path) -> None:
    events: list[str] = []
    paths, trainer = idle_trainer(tmp_path, events)
    data = trainer.build_data(1)
    state = PhaseState(1, PhaseStage.PUBLISH, "time", PUBLISHED_AT, "/policy", "/value", data)
    await trainer.run_phase(state, None)
    assert (events, read_current(paths).version, read_phase_state(paths).stage) == (
        ["restore gpu0 v1", "restore gpu1 v1"],
        1,
        PhaseStage.DONE,
    )


class FirstSentence:
    async def shorten(self, items: Sequence[ThinkingItem]) -> list[str]:
        return [(item.pair.chosen_reasoning or "").split(".")[0] + "." for item in items]


def compressing_trainer(tmp_path: Path, shortener: FirstSentence | None) -> PhaseTrainer:
    config = loop_config(compress_reasoning=True)
    paths = LoopPaths(tmp_path, tmp_path, config.name)
    publisher = MergedPublisher(config.serving, tmp_path / "weights", create_directory)
    return PhaseTrainer(config, paths, publisher, StopStartRelease(publisher), tmp_path, print, True, shortener)


@pytest.mark.parametrize(
    ("thinking", "settings"),
    [
        (ThinkingConfig(), {}),
        (ThinkingConfig(enabled=True, max_tokens=512), {"thinking_instruction": "", "max_completion_tokens": 576}),
    ],
)
def test_thinking_pairs_train_with_the_searchs_prompt_and_length(
    thinking: ThinkingConfig, settings: dict[str, object]
) -> None:
    assert dict(policy_settings(thinking)) == settings


def thinking_shard(paths: LoopPaths) -> None:
    builder = TreeBuilder("⊢ r", problem_name="a.t")
    builder.failure(builder.root, "exact foo")
    proved = builder.child(builder.root, step="linarith")
    steps = (StepReasoning(0, "linarith", "It is linear. Then a long detour."), StepReasoning(0, "exact foo", "Foo."))
    writer = ShardWriter(paths.shards, max_attempts=10, max_seconds=1e9)
    record = attempt("a.t", proved=True, decision=Decision.SOLVED)
    writer.write(record, builder.record(proved), TreeReasoning("import Mathlib", steps))
    writer.close()


async def test_the_compress_stage_shortens_new_proof_step_reasoning(tmp_path: Path) -> None:
    trainer = compressing_trainer(tmp_path, FirstSentence())
    thinking_shard(trainer.paths)
    await trainer.compress_reasoning()
    (digest,) = digested(trainer.paths.digests)
    assert [versioned.pair.chosen_reasoning for versioned in read_policy(digest)] == ["It is linear."]


def test_a_phase_uses_each_digest_once(tmp_path: Path) -> None:
    paths, trainer = phase_trainer(tmp_path)
    trainer.build_data(1)
    assert trainer.build_data(2).new_proofs == 0


def test_the_value_dataset_is_topped_up_to_its_floor(tmp_path: Path) -> None:
    _, trainer = phase_trainer(tmp_path)
    buffer: FifoBuffer[ValueSample] = FifoBuffer(50, [], minimum_dataset_share=0.1)
    trainer.top_up_value_dataset(buffer, 1)
    assert len(buffer.dataset) == 5


def test_a_phase_trains_on_at_most_its_cap(tmp_path: Path) -> None:
    _, trainer = phase_trainer(tmp_path)
    training = dataclasses.replace(trainer.config.training, max_value_samples=4)
    trainer.config = dataclasses.replace(trainer.config, training=training)
    assert trainer.build_data(1).value.trained == 4


async def test_a_version_not_due_is_not_evaluated(tmp_path: Path) -> None:
    events: list[str] = []
    paths, trainer = idle_trainer(tmp_path, events)
    record_published(paths, ModelVersion(1, "/p", "/v", PUBLISHED_AT, "proofs"))
    await trainer.evaluate_if_due()
    assert not paths.evaluations.exists()
