import asyncio
import dataclasses
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from loop_fakes import (
    LOOP_TOML,
    SERVE_SECONDS,
    FakeEvaluations,
    FakeSearcher,
    FakeTrainer,
    FakeValueScorer,
    LoopWorld,
    loop_world,
    record_version_zero,
    run_until,
    statement,
    zero,
)

from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.serving import ModelVersion, read_current, read_versions, write_json_atomically
from lean_search.monitoring.families import PauseSegments, ValueArmResult
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind, EvaluationRun, EvaluationSummary
from lean_search.rl.fixed_targets import baseline_concurrency
from lean_search.rl.loop import (
    GIB,
    BesideSampling,
    GrpoLoop,
    GrpoLoopPaths,
    PhaseRecord,
    PhaseStage,
    TrainingRequest,
    earlier_value_arm_results,
    evaluation_due,
    phase_config_text,
    probe_baseline_differences,
    read_progress,
    read_value_share,
    request_evaluation,
    set_value_share,
    value_published_by,
)
from lean_search.rl.loop_config import EvaluationTarget, parse_loop_config
from lean_search.rl.loop_services import SubprocessTrainer
from lean_search.rl.training_phase import TrainerTimings
from lean_search.rl.tree_store import TreeStore
from lean_search.rl.value_trends import scored_versions
from lean_search.search.records import from_json_object, to_json

TEMPLATE = (Path(__file__).resolve().parents[2] / "experiments/configs/grpo/phase.toml").read_text(encoding="utf-8")
VERSION = ModelVersion(3, "phase-3/policy/adapter", "phase-2/value/adapter", "2026-10-29T10:00:00+00:00", "phase 3")


def phase_table(value_share: float = 0.0, value_adapter: str | None = "phase-1/value/adapter") -> dict:
    return tomllib.loads(
        phase_config_text(TEMPLATE, "base/model", "sft/adapter", VERSION, 4, value_share, value_adapter)
    )


def test_phase_config_continues_the_published_policy_adapter() -> None:
    assert phase_table()["policy"]["initial_adapter"] == "phase-3/policy/adapter"


def test_phase_config_trains_on_the_served_policy_base() -> None:
    assert phase_table()["policy"]["model"] == "base/model"


def test_phase_config_keeps_the_starting_adapter_as_the_reference() -> None:
    assert phase_table()["policy"]["reference_adapter"] == "sft/adapter"


def test_phase_config_continues_the_given_value_adapter() -> None:
    assert phase_table()["value"]["initial_adapter"] == "phase-1/value/adapter"


def test_phase_config_seeds_the_value_training_per_phase() -> None:
    assert phase_table()["value"]["optimization"]["seed"] == 4


def test_phase_config_without_value_training_has_no_value_part() -> None:
    assert "value" not in phase_table(value_adapter=None)


@pytest.mark.parametrize("section", ["reward", "value_targets"])
def test_phase_config_sets_mu_in_reward_and_targets(section: str) -> None:
    assert phase_table(value_share=0.15)[section]["value_share"] == 0.15


def test_phase_config_seeds_each_phase_differently() -> None:
    assert phase_table()["policy"]["optimization"]["seed"] == 4


def test_phase_config_draws_the_replay_per_phase() -> None:
    assert phase_table()["policy_replay"]["seed"] == "grpo-replay/4"


@pytest.mark.parametrize(
    ("target", "last", "loop_seconds", "at_start", "due"),
    [
        (EvaluationTarget(16, 600.0, 4, every_hours=6.0, at_start=True), None, 0.0, True, True),
        (EvaluationTarget(16, 600.0, 4, every_hours=6.0, at_start=True), 0.0, 0.0, True, False),
        (EvaluationTarget(16, 600.0, 4, every_hours=6.0), 0.0, 5 * 3600.0, False, False),
        (EvaluationTarget(16, 600.0, 4, every_hours=6.0), 0.0, 6 * 3600.0, False, True),
        (EvaluationTarget(16, 600.0, 4, every_hours=0.0), None, 99 * 3600.0, False, False),
    ],
)
def test_evaluation_schedule(
    target: EvaluationTarget, last: float | None, loop_seconds: float, at_start: bool, due: bool
) -> None:
    assert evaluation_due(target, last, loop_seconds, at_start) == due


@pytest.mark.parametrize(("second_value", "published"), [("value-v1", True), ("value-v0", False)])
def test_value_published_by_compares_with_the_previous_version(second_value: str, published: bool) -> None:
    versions = [
        ModelVersion(0, "", "value-v0", "2026-10-29T10:00:00+00:00", "initial"),
        ModelVersion(1, "p1", second_value, "2026-10-29T11:00:00+00:00", "phase 1"),
    ]
    assert value_published_by(versions, 1) == published


async def test_a_phase_publishes_version_one(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).version == 1


async def test_a_phase_trains_on_its_own_tree_directory(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.trainer.requests[0].trees == TreeStore(world.paths.trees).phase_directory(1)


async def test_the_training_gpu_is_released_for_each_phase(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.servers.releases == 2


def first_pause(world: LoopWorld) -> list[str]:
    events = world.searcher.events
    start = events.index("pause")
    return events[start : events.index("resume", start) + 1]


async def test_a_pause_sleeps_every_server_trains_then_wakes_them_with_the_new_version(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert first_pause(world) == [
        "pause",
        "stop repls above 0",
        "sleep policy-gpu0",
        "sleep policy-gpu1",
        "sleep value-gpu0",
        "sleep value-gpu1",
        "train 1",
        "wake policy-gpu0 v1",
        "wake policy-gpu1 v1",
        "wake value-gpu0 v1",
        "wake value-gpu1 v1",
        "resume",
    ]


async def test_with_one_training_gpu_the_other_servers_swap_in_place(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=LOOP_TOML.replace("gpus = [0, 1]", "gpus = [0]"))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert first_pause(world) == [
        "pause",
        "stop repls above 0",
        "sleep policy-gpu0",
        "sleep value-gpu0",
        "train 1",
        "wake policy-gpu0 v1",
        "swap policy-gpu1 v1",
        "wake value-gpu0 v1",
        "swap value-gpu1 v1",
        "resume",
    ]


@pytest.mark.parametrize(
    ("column", "seconds"),
    [
        ("pause.value_training_seconds", 7.0),
        ("pause.merge_seconds", 11.0),
        ("pause.wake_seconds", SERVE_SECONDS.weights),
        ("pause.resume_seconds", SERVE_SECONDS.resume),
    ],
)
async def test_the_timing_line_records_the_pause_segments(tmp_path: Path, column: str, seconds: float) -> None:
    trainer = FakeTrainer(timings=TrainerTimings(value_training_seconds=7.0, merge_seconds=11.0))
    world = loop_world(tmp_path, trainer=trainer)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert RunReader(world.paths.directory).series("timing").columns[column][-1] == seconds


async def test_the_pause_segments_start_afresh_each_phase(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_progress(world.paths.progress).pause == PauseSegments()


async def test_servers_serve_each_published_version(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.servers.served == [0, 1, 2]


async def test_searches_hear_each_served_version(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.searcher.policy_versions == [0, 1, 2]


async def test_the_second_phase_continues_from_the_first_phases_adapter(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    second = tomllib.loads(world.trainer.requests[1].config_text)
    assert second["policy"]["initial_adapter"] == read_versions(world.paths.models)[1].policy_adapter


async def test_every_trained_value_model_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).value_adapter == str(
        world.trainer.requests[0].output_directory / "value/adapter"
    )


def value_shares(world: LoopWorld) -> list[float]:
    return [tomllib.loads(request.config_text)["reward"]["value_share"] for request in world.trainer.requests]


async def test_mu_is_zero_until_set(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert value_shares(world) == [0.0, 0.0]


async def test_mu_set_during_a_run_applies_from_the_next_phase_that_trains(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    set_value_share(world.paths, 0.15)
    await run_until(world, world.loop(), phases=2)
    assert value_shares(world)[:2] == [0.0, 0.15]


@pytest.mark.parametrize("section", ["reward", "value_targets"])
async def test_mu_reaches_reward_and_value_targets(tmp_path: Path, section: str) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    set_value_share(world.paths, 0.15)
    await run_until(world, world.loop(), phases=1)
    assert tomllib.loads(world.trainer.requests[0].config_text)[section]["value_share"] == 0.15


async def test_mu_in_effect_is_on_the_value_phase_line(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    set_value_share(world.paths, 0.15)
    await run_until(world, world.loop(), phases=1)
    assert RunReader(world.paths.directory).series("value_phase").columns["value_share"] == [0.15]


async def test_mu_in_effect_is_in_the_phase_record(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    set_value_share(world.paths, 0.15)
    await run_until(world, world.loop(), phases=1)
    assert '"value_share": 0.15' in world.paths.phases.read_text(encoding="utf-8")


def test_mu_turned_off_reads_zero(tmp_path: Path) -> None:
    paths = GrpoLoopPaths(tmp_path, tmp_path, tmp_path, "loop")
    set_value_share(paths, 0.15)
    set_value_share(paths, 0.0)
    assert read_value_share(paths) == 0.0


@pytest.mark.parametrize("value_share", [-0.1, 1.5])
def test_mu_outside_zero_to_one_is_refused(tmp_path: Path, value_share: float) -> None:
    with pytest.raises(ValueError):
        set_value_share(GrpoLoopPaths(tmp_path, tmp_path, tmp_path, "loop"), value_share)


def remaining_adapters(world: LoopWorld, kind: str) -> list[str]:
    root = world.paths.checkpoints_root
    return sorted(path.parent.parent.name for path in root.glob(f"*_phase_*/{kind}/adapter"))


def retention_world(root: Path, adapter_versions: int) -> LoopWorld:
    return loop_world(root, LOOP_TOML + f"\n[retention]\nadapter_versions = {adapter_versions}\n")


async def test_policy_adapters_of_versions_beyond_the_retention_are_deleted(tmp_path: Path) -> None:
    world = retention_world(tmp_path, adapter_versions=2)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=4)
    assert remaining_adapters(world, "policy") == ["test_loop_phase_0003", "test_loop_phase_0004"]


async def test_value_adapters_of_versions_beyond_the_retention_are_deleted(tmp_path: Path) -> None:
    world = retention_world(tmp_path, adapter_versions=2)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=4)
    assert remaining_adapters(world, "value") == ["test_loop_phase_0003", "test_loop_phase_0004"]


async def test_a_retention_of_zero_keeps_every_adapter(tmp_path: Path) -> None:
    world = retention_world(tmp_path, adapter_versions=0)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=3)
    assert len(remaining_adapters(world, "policy")) == 3


def write_value_arm(paths: GrpoLoopPaths, slot: int) -> Path:
    directory = paths.evaluation_directory(EvaluationRun(EvaluationKind.PROBE, slot, value_arm=True), slot)
    write_json_atomically(directory / "comparison.json", dataclasses.replace(zero(ValueArmResult), slot=slot))
    return directory


def test_a_value_arm_pools_with_every_other_value_arm(tmp_path: Path) -> None:
    paths = GrpoLoopPaths(tmp_path, tmp_path, tmp_path, "loop")
    own = [write_value_arm(paths, slot) for slot in (0, 2, 4)][-1]
    assert [result.slot for result in earlier_value_arm_results(paths, own)] == [0, 2]


def write_probe_run(paths: GrpoLoopPaths, slot: int, version: int, solved: int, repeat: int = 0) -> None:
    run = EvaluationRun(EvaluationKind.PROBE, slot, repeat)
    summary = dataclasses.replace(zero(EvaluationSummary), problems=10, solved=solved, slot=slot)
    write_json_atomically(paths.evaluation_directory(run, version) / "summary.json", summary)


def baseline_world(root: Path, slots: dict[int, int]) -> GrpoLoopPaths:
    """Version 0's two runs of each part (solved 4 and 6 of 10: a mean of 0.5), then the given slots' solved counts."""
    paths = GrpoLoopPaths(root, root, root, "loop")
    for part in range(3):
        write_probe_run(paths, part, 0, 4)
        write_probe_run(paths, part, 0, 6, repeat=1)
    for slot, solved in slots.items():
        write_probe_run(paths, slot, slot, solved)
    return paths


LOOP_EVALUATION = parse_loop_config(LOOP_TOML).evaluation
EVALUATION = dataclasses.replace(LOOP_EVALUATION, probe=dataclasses.replace(LOOP_EVALUATION.probe, baseline_runs=2))


def test_a_probe_slot_is_compared_with_version_zeros_runs_of_its_part(tmp_path: Path) -> None:
    paths = baseline_world(tmp_path, {4: 7})
    assert probe_baseline_differences(paths, EVALUATION, 4).this_slot == pytest.approx(0.2)


def test_the_baseline_difference_of_the_last_slots_takes_each_part_once(tmp_path: Path) -> None:
    paths = baseline_world(tmp_path, {3: 5, 4: 7, 5: 9})
    assert probe_baseline_differences(paths, EVALUATION, 5).last_slots == pytest.approx(0.2)


def test_the_baseline_difference_of_the_last_slots_waits_for_every_part(tmp_path: Path) -> None:
    paths = baseline_world(tmp_path, {4: 7, 5: 9})
    assert probe_baseline_differences(paths, EVALUATION, 5).last_slots is None


def test_a_slot_still_running_counts_as_missing(tmp_path: Path) -> None:
    paths = baseline_world(tmp_path, {4: 7, 5: 9})
    paths.evaluation_directory(EvaluationRun(EvaluationKind.PROBE, 3), 3).mkdir(parents=True)
    assert probe_baseline_differences(paths, EVALUATION, 5).last_slots is None


PROBE_EVERY_PHASE = LOOP_TOML.replace(
    "every_hours = 0.0\nat_start = false\n\n[evaluation.held_out_states]",
    "every_hours = 0.001\nat_start = false\n\n[evaluation.held_out_states]",
)


async def test_each_probe_slot_searches_the_next_part(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=3)
    assert world.evaluations.slots()[:3] == [(0, 0), (1, 0), (2, 0)]


async def test_the_next_probe_slot_survives_a_restart(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.slots()[:2] == [(0, 0), (1, 0)]


PROBE_AND_VALUE_EVERY_SECOND_PHASE = PROBE_EVERY_PHASE.replace("value_every_phases = 1\n", "value_every_phases = 2\n")


async def test_each_published_value_model_gets_one_value_arm_at_the_next_slot(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_AND_VALUE_EVERY_SECOND_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=4)
    assert world.evaluations.slots(value_arm=True) == [(1, 0), (3, 0)]


async def test_a_value_arm_survives_a_restart_once(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_AND_VALUE_EVERY_SECOND_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    await run_until(world, world.loop(), phases=3)
    assert world.evaluations.slots(value_arm=True) == [(1, 0)]


async def test_a_value_arm_follows_its_slots_run(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert [run.value_arm for run, _ in world.evaluations.runs] == [False, True]


async def test_a_value_arm_searches_with_the_published_value_model(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    kept, published = world.servers.value_weights[:2]
    assert ("kept_value" in kept, published) == (True, read_versions(world.paths.models)[1].value_weights)


async def test_no_value_arm_runs_while_v0_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE.replace("value_every_phases = 1\n", "value_every_phases = 0\n"))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.slots(value_arm=True) == []


async def test_a_value_arm_finding_the_published_model_worse_changes_nothing(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE, evaluations=FakeEvaluations(value_arm_worse=True))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).value_adapter != world.config.initial.value_adapter


async def test_a_value_arm_finding_the_published_model_worse_alerts_in_the_log(tmp_path: Path) -> None:
    world = loop_world(tmp_path, PROBE_EVERY_PHASE, evaluations=FakeEvaluations(value_arm_worse=True))
    record_version_zero(world)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    assert any(message.startswith("Alert: ") and "worse than v0" in message for message in messages)


async def test_the_served_value_models_score_the_benchmark_once_each(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer())
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert scored_versions(world.paths.value_benchmark)[:2] == [0, 1]


async def test_the_benchmark_trend_compares_with_v0(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer())
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    trend = RunReader(world.paths.directory).series("value_benchmark")
    assert trend.columns["reference_value_version"][:2] == [None, 0]


async def test_the_benchmark_scoring_finishes_before_the_next_pause(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer())
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    events = world.searcher.events
    second_pause = [index for index, event in enumerate(events) if event == "pause"][1]
    assert events[:second_pause].count("scored") == 2


async def test_a_failed_benchmark_scoring_does_not_stop_the_loop(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer(failing=True))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.phases_done() == 2


async def test_a_failed_benchmark_trend_does_not_stop_the_loop(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer(foreign_scorings=2))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.phases_done() == 2


async def test_a_value_version_whose_trend_failed_is_scored_again_after_the_next_phase(tmp_path: Path) -> None:
    world = loop_world(
        tmp_path,
        LOOP_TOML.replace("value_every_phases = 1\n", "value_every_phases = 0\n"),
        scorer=FakeValueScorer(foreign_scorings=1),
    )
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert scored_versions(world.paths.value_benchmark) == [0]


async def test_a_failed_benchmark_trend_is_counted_in_the_status(tmp_path: Path) -> None:
    world = loop_world(tmp_path, scorer=FakeValueScorer(foreign_scorings=1))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert RunReader(world.paths.directory).series("status").columns["value_benchmark_failures"][-1] == 1


MALFORMED = problem_name(statement(1).statement)


async def test_a_tree_whose_summary_fails_is_left_out(tmp_path: Path) -> None:
    world = loop_world(tmp_path, searcher=FakeSearcher(malformed=frozenset({MALFORMED})))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert MALFORMED not in {entry.problem_name for entry in TreeStore(world.paths.trees).entries}


async def test_a_tree_whose_summary_fails_does_not_stop_the_loop(tmp_path: Path) -> None:
    world = loop_world(tmp_path, searcher=FakeSearcher(malformed=frozenset({MALFORMED})))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.phases_done() == 2


async def test_the_probe_runs_with_the_reference_value_model_once_another_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=2, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    assert "kept_value" in world.servers.value_weights[0]


async def test_the_value_servers_return_to_the_published_value_model_after_evaluating(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=2, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    assert world.servers.value_weights[-1] == read_versions(world.paths.models)[1].value_weights


async def test_the_value_servers_swap_only_after_every_server_woke(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=1, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    events = world.servers.events
    first_swap = next(index for index, event in enumerate(events) if event.startswith("value "))
    last_wake = max(index for index, event in enumerate(events) if event.startswith("wake "))
    assert last_wake < first_swap


async def test_evaluations_need_no_value_swap_while_the_reference_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("value_every_phases = 1\n", "value_every_phases = 0\n"))
    record_version_zero(world)
    request_evaluation(world.paths, EvaluationKind.PROBE)
    await run_until(world, world.loop(), phases=1)
    assert world.servers.value_weights == []


BESIDE_SAMPLING = """
[evaluation]
value_model = "published"
beside_sampling = true

[evaluation.value_arm]
enabled = false
"""
# The probe after every phase beside sampling, the held-out states at every pause from version 0's run on.
BESIDE_EVERY_PHASE = (
    PROBE_EVERY_PHASE.replace(
        "every_hours = 0.0\nat_start = false\n", "every_hours = 0.001\nat_start = true\n"
    ).replace("concurrency = 2\n", "concurrency = 2\nmin_concurrency_beside_evaluations = 1\n")
    + BESIDE_SAMPLING
)
# A requested miniF2F beside sampling from the start, at least one search taking statements meanwhile, and a phase
# that waits for it as long as it takes.
BESIDE_FROM_THE_START = LOOP_TOML.replace(
    "concurrency = 2\n", "concurrency = 2\nmin_concurrency_beside_evaluations = 1\n"
) + BESIDE_SAMPLING.replace("beside_sampling = true\n", "beside_sampling = true\nmax_pause_wait_minutes = 1e9\n")
# The same with the default wait: the clock steps a minute per reading, so a pause gives up waiting quickly.
BESIDE_WAITING_BRIEFLY = BESIDE_FROM_THE_START.replace("max_pause_wait_minutes = 1e9\n", "")


def beside_world(
    root: Path,
    toml: str = BESIDE_FROM_THE_START,
    evaluations: FakeEvaluations | None = None,
    hold: asyncio.Event | None = None,
    searches_reported: int | None = None,
) -> LoopWorld:
    evaluations = evaluations or FakeEvaluations(hold=hold, searches_reported=searches_reported)
    world = loop_world(root, toml, evaluations=evaluations)
    record_version_zero(world)
    request_evaluation(world.paths, EvaluationKind.MINIF2F)
    return world


def minif2f_runs(world: LoopWorld) -> int:
    return sum(run.kind == EvaluationKind.MINIF2F for run, _ in world.evaluations.runs)


async def run_until_condition(loop: GrpoLoop, condition: Callable[[], bool]) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop))
    while not condition() and not task.done():
        await asyncio.sleep(0)
    stop.set()
    await task


@pytest.mark.parametrize(
    "settings",
    [
        'value_model = "initial"\nbeside_sampling = true\n\n[evaluation.value_arm]\nenabled = false\n',
        'value_model = "published"\nbeside_sampling = true\n',
    ],
    ids=["initial value model", "value arm"],
)
def test_evaluations_beside_sampling_need_the_published_value_model_and_no_value_arm(settings: str) -> None:
    floor = LOOP_TOML.replace("concurrency = 2\n", "concurrency = 2\nmin_concurrency_beside_evaluations = 1\n")
    with pytest.raises(ValueError, match="value_model"):
        parse_loop_config(floor + "\n[evaluation]\n" + settings)


async def test_the_probe_runs_beside_sampling_while_the_searches_are_open(tmp_path: Path) -> None:
    world = loop_world(tmp_path, BESIDE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.searches_open_during(EvaluationKind.PROBE)[:1] == [True]


async def test_the_held_out_states_still_run_at_the_pause(tmp_path: Path) -> None:
    world = loop_world(tmp_path, BESIDE_EVERY_PHASE)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.searches_open_during(EvaluationKind.HELD_OUT_STATES)[1:3] == [False, False]


def releasing_when_the_pause_waits(world: LoopWorld) -> GrpoLoop:
    loop = world.loop()

    def log(message: str) -> None:
        if message.startswith("The phase's pause waits"):
            assert world.evaluations.hold is not None
            world.evaluations.hold.set()

    loop.log = log
    return loop


async def test_no_server_sleeps_or_swaps_under_an_evaluation_beside_sampling(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event())
    await run_until(world, releasing_when_the_pause_waits(world), phases=2)
    assert world.servers.changed_under_evaluation == []


async def test_searches_above_the_limit_take_no_statement_while_an_evaluation_runs(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event())
    await run_until_condition(world.loop(), lambda: len(world.searcher.searched) >= 20)
    assert world.searcher.most_in_flight == 1


async def test_searches_fill_the_concurrency_the_evaluation_leaves(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event(), searches_reported=0)
    await run_until_condition(world.loop(), lambda: len(world.searcher.searched) >= 20)
    assert world.searcher.most_in_flight == 2


async def test_searches_above_the_limit_stop_the_idle_repls_beyond_it(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event())
    await run_until_condition(world.loop(), lambda: len(world.searcher.searched) >= 20)
    assert 1 in world.searcher.idle_repl_limits


async def test_the_host_memory_is_logged_around_an_evaluation_beside_sampling(tmp_path: Path) -> None:
    world = beside_world(tmp_path)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    assert [
        message for message in messages if "beside sampling start" in message or "after the evaluations" in message
    ] == [
        "Host memory as the evaluations beside sampling start: not measured",
        "Host memory after the evaluations beside sampling: not measured",
    ]


async def test_the_phase_pause_waits_for_the_evaluation_beside_sampling(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event())
    loop = world.loop()
    searched_when_waiting: list[int] = []

    def log(message: str) -> None:
        if message.startswith("The phase's pause waits"):
            searched_when_waiting.append(len(world.searcher.searched))

    loop.log = log
    await run_until_condition(
        loop,
        lambda: (
            world.searcher.pauses > 0
            or (bool(searched_when_waiting) and len(world.searcher.searched) >= searched_when_waiting[0] + 10)
        ),
    )
    assert world.searcher.pauses == 0


async def test_the_phase_pauses_after_the_whole_evaluation_beside_sampling(tmp_path: Path) -> None:
    world = beside_world(tmp_path, hold=asyncio.Event())
    loop = releasing_when_the_pause_waits(world)
    released_log = loop.log
    requested_at_the_pause: list[bool] = []

    def log(message: str) -> None:
        released_log(message)
        if message.startswith("Phase 1: "):
            requested_at_the_pause.append((world.paths.requests / EvaluationKind.MINIF2F).exists())

    loop.log = log
    await run_until(world, loop, phases=1)
    assert requested_at_the_pause == [False]


async def test_a_phase_waits_at_most_its_longest_wait_for_an_evaluation_beside_sampling(tmp_path: Path) -> None:
    world = beside_world(tmp_path, BESIDE_WAITING_BRIEFLY, hold=asyncio.Event())
    await run_until(world, world.loop(), phases=1)
    assert world.phases_done() == 1


async def test_an_evaluation_cut_off_by_the_pause_runs_again_after_it(tmp_path: Path) -> None:
    world = beside_world(tmp_path, BESIDE_WAITING_BRIEFLY, hold=asyncio.Event())
    await run_until_condition(world.loop(), lambda: minif2f_runs(world) == 2)
    assert world.phases_done() == 1


async def test_an_evaluation_cut_off_by_the_pause_is_recorded_with_the_phase(tmp_path: Path) -> None:
    world = beside_world(tmp_path, BESIDE_WAITING_BRIEFLY, hold=asyncio.Event())
    await run_until(world, world.loop(), phases=1)
    record = json.loads(world.paths.phases.read_text(encoding="utf-8").splitlines()[0])
    assert record["beside_sampling"]["failed"] == ["minif2f"]


async def test_a_finished_evaluation_beside_sampling_is_recorded_with_the_phase(tmp_path: Path) -> None:
    world = beside_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    record = json.loads(world.paths.phases.read_text(encoding="utf-8").splitlines()[0])
    assert record["beside_sampling"]["finished"] == ["minif2f"]


def test_a_phase_record_without_evaluations_beside_sampling_reads() -> None:
    fields = json.loads(to_json(zero(PhaseRecord)))
    del fields["beside_sampling"]
    assert from_json_object(PhaseRecord, fields).beside_sampling == BesideSampling()


async def test_a_failed_evaluation_beside_sampling_does_not_stop_the_loop(tmp_path: Path) -> None:
    world = beside_world(tmp_path, evaluations=FakeEvaluations(failures=1))
    await run_until(world, world.loop(), phases=1)
    assert world.phases_done() == 1


async def test_a_failed_evaluation_beside_sampling_runs_again_after_the_next_pause(tmp_path: Path) -> None:
    world = beside_world(tmp_path, evaluations=FakeEvaluations(failures=1))
    await run_until_condition(world.loop(), lambda: minif2f_runs(world) == 2)
    assert world.phases_done() == 1


async def test_a_failed_evaluation_beside_sampling_alerts_in_the_log(tmp_path: Path) -> None:
    world = beside_world(tmp_path, evaluations=FakeEvaluations(failures=1))
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    assert any(message.startswith("Alert: the minif2f evaluation beside sampling failed") for message in messages)


async def test_a_failed_evaluation_beside_sampling_is_counted_in_the_status(tmp_path: Path) -> None:
    world = beside_world(tmp_path, evaluations=FakeEvaluations(failures=1))
    await run_until(world, world.loop(), phases=1)
    assert RunReader(world.paths.directory).series("status").columns["evaluation_failures"][-1] == 1


@dataclasses.dataclass
class ServerSensitiveEvaluations(FakeEvaluations):
    """Like the evaluation job: a server that stops answering fails the run."""

    async def evaluated(self, run: EvaluationRun, phase: int) -> EvaluationSummary:
        assert self.searcher is not None
        for _ in range(200):
            if self.searcher.servers_down:
                raise RuntimeError("grpo_evaluate.py failed: ConnectError")
            await asyncio.sleep(0.001)
        return await super().evaluated(run, phase)


async def run_with_a_server_dying_during_an_evaluation(root: Path, until: Callable[[LoopWorld], bool]) -> LoopWorld:
    """The miniF2F beside sampling from the start; once the first search finished, a policy server dies."""
    toml = BESIDE_FROM_THE_START.replace(
        "status_seconds = 0.01\n",
        "status_seconds = 0.01\nserver_failure_pause_seconds = 0.0\nserver_failure_window = 4\n",
    )
    world = beside_world(root, toml, evaluations=ServerSensitiveEvaluations())
    stop = asyncio.Event()
    task = asyncio.create_task(world.loop().run(stop))
    while not world.searcher.searched and not task.done():
        await asyncio.sleep(0)
    world.searcher.servers_down.add("policy-gpu0")
    while not until(world) and not task.done():
        await asyncio.sleep(0)
    stop.set()
    await task
    return world


async def test_a_server_dying_during_an_evaluation_beside_sampling_is_restarted(tmp_path: Path) -> None:
    world = await run_with_a_server_dying_during_an_evaluation(tmp_path, lambda world: bool(world.servers.restarted))
    assert world.servers.restarted == ["policy-gpu0"]


async def test_an_evaluation_failing_on_a_dying_server_does_not_stop_the_sampling(tmp_path: Path) -> None:
    world = await run_with_a_server_dying_during_an_evaluation(tmp_path, lambda world: world.phases_done() == 1)
    assert world.phases_done() == 1


async def test_an_evaluation_a_stop_cut_off_runs_beside_sampling_at_the_next_start(tmp_path: Path) -> None:
    world = loop_world(tmp_path, BESIDE_EVERY_PHASE, evaluations=FakeEvaluations(hold=asyncio.Event()))
    record_version_zero(world)
    await run_until_condition(world.loop(), lambda: bool(world.evaluations.slots()))
    world.evaluations.hold = None
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.slots()[:2] == [(0, 0), (0, 0)]


async def test_value_training_continues_the_last_trained_adapter(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    first, second = world.trainer.requests[:2]
    initial = tomllib.loads(second.config_text)["value"]["initial_adapter"]
    assert initial == str(first.output_directory / "value/adapter")


async def test_value_training_sees_the_window_of_recent_phases(tmp_path: Path) -> None:
    toml = LOOP_TOML.replace("value_every_phases = 1\n", "value_every_phases = 1\nvalue_window_phases = 2\n")
    world = loop_world(tmp_path, toml)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=3)
    store = TreeStore(world.paths.trees)
    assert world.trainer.requests[2].value_trees == (store.phase_directory(2), store.phase_directory(3))


async def test_the_value_model_trains_every_second_phase_by_default(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("value_every_phases = 1\n", ""))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=4)
    assert [request.train_value for request in world.trainer.requests] == [False, True, False, True]


@pytest.mark.parametrize(
    "family", ["status", "curriculum", "search", "grpo", "timing", "value_phase", "value_training"]
)
async def test_a_phase_writes_the_dashboard_family(tmp_path: Path, family: str) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert family in RunReader(world.paths.directory).families()


async def test_a_restart_finishes_the_interrupted_training(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(fail_phases={1}))
    record_version_zero(world)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)
    world.trainer.fail_phases.clear()
    await run_until(world, world.loop(), phases=1)
    assert [request.phase for request in world.trainer.requests] == [1, 1]


async def test_a_restart_wakes_no_server_while_an_earlier_loops_job_runs(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(earlier_job="torchrun grpo_phase.py"))
    record_version_zero(world)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)
    assert world.servers.served == []


async def test_an_interrupted_phase_is_recorded_as_training(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(fail_phases={1}))
    record_version_zero(world)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)
    assert read_progress(world.paths.progress).stage == PhaseStage.TRAINING


async def test_a_pending_request_runs_before_the_first_phase(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    request_evaluation(world.paths, EvaluationKind.MINIF2F)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.runs == [(EvaluationRun(EvaluationKind.MINIF2F), 0)]


async def test_a_request_during_sampling_runs_at_the_next_pause(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=1, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.MINIF2F)
    )
    assert world.evaluations.runs == [(EvaluationRun(EvaluationKind.MINIF2F), 1)]


async def test_a_requested_evaluation_runs_once(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    request_evaluation(world.paths, EvaluationKind.MINIF2F)
    await run_until(world, world.loop(), phases=2)
    assert len(world.evaluations.runs) == 1


async def test_a_baseline_evaluation_runs_before_the_first_phase(tmp_path: Path) -> None:
    toml = LOOP_TOML.replace(
        "every_hours = 0.0\nat_start = false\n\n[evaluation.held_out_states]",
        "every_hours = 0.0\nat_start = true\n\n[evaluation.held_out_states]",
    )
    world = loop_world(tmp_path, toml=toml)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.slots() == [(0, 0), (1, 0), (2, 0)]


BASELINE_TOML = LOOP_TOML.replace(
    "every_hours = 0.0\nat_start = false\n\n[evaluation.held_out_states]",
    "every_hours = 0.0\nat_start = true\nbaseline_runs = 2\n\n[evaluation.held_out_states]",
)


async def test_the_baseline_probe_runs_every_part_twice(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.slots() == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]


async def test_version_zeros_baseline_runs_all_at_once(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.most_in_flight == 6


async def test_sampling_starts_after_version_zeros_baselines(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.searched_before[:6] == [0] * 6


async def test_version_zeros_baseline_runs_share_the_concurrency(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML.replace("concurrency = 2\n", "concurrency = 12\n"))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert {run.concurrency for run, _ in world.evaluations.runs} == {2}


@pytest.mark.parametrize(
    ("settings", "concurrency"),
    [("", 16), ("baseline_concurrency = 11\n", 11)],
    ids=["an equal share", "its own"],
)
def test_baseline_concurrency(settings: str, concurrency: int) -> None:
    toml = BASELINE_TOML.replace("concurrency = 2\n", "concurrency = 112\n").replace(
        "baseline_runs = 2\n", f"baseline_runs = 2\n{settings}"
    )
    toml = toml.replace("every_hours = 0.0\nat_start = false\n", "every_hours = 0.0\nat_start = true\n")
    assert baseline_concurrency(parse_loop_config(toml), EvaluationKind.PROBE) == concurrency


@pytest.mark.parametrize("floor", [0, 3])
def test_a_floor_beside_evaluations_outside_the_concurrency_is_refused(floor: int) -> None:
    setting = f"concurrency = 2\nmin_concurrency_beside_evaluations = {floor}\n"
    with pytest.raises(ValueError):
        parse_loop_config(LOOP_TOML.replace("concurrency = 2\n", setting) + BESIDE_SAMPLING)


async def test_a_requested_probe_after_the_baseline_runs_the_next_slot_once(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    request_evaluation(world.paths, EvaluationKind.PROBE)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.slots()[6:] == [(3, 0)]


async def test_the_paused_searches_release_their_lean_memory_before_evaluating(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML + "\n[evaluation]\npaused_repl_memory_gib = 1.0\n")
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.searcher.memory_releases[0] == GIB


async def test_the_paused_searches_release_their_lean_memory_before_training(tmp_path: Path) -> None:
    toml = LOOP_TOML.replace("value_every_phases = 1\n", "value_every_phases = 1\npaused_repl_memory_gib = 2.0\n")
    world = loop_world(tmp_path, toml=toml)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.searcher.memory_releases == [2 * GIB]


async def test_the_host_memory_is_logged_at_the_pause_stages(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    loop.host_memory = lambda: "plenty"
    await run_until(world, loop, phases=1)
    assert [message for message in messages if message.startswith("Host memory")] == [
        "Host memory at the pause: plenty",
        "Host memory before training: plenty",
        "Host memory after training: plenty",
        "Host memory after publishing: plenty",
    ]


async def test_the_gpu_memory_is_logged_before_the_wake(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    loop.gpu_memory = lambda: "GPU 0 2.0 of 24.0 GiB free"
    await run_until(world, loop, phases=1)
    wake = messages.index("GPU memory before the wake: GPU 0 2.0 of 24.0 GiB free")
    assert messages[wake + 1].startswith("Published version 1")


FAILING = problem_name(statement(0).statement)


def failing_world(root: Path, failures: int) -> LoopWorld:
    toml = LOOP_TOML.replace("status_seconds = 0.01\n", "status_seconds = 0.01\nserver_failure_pause_seconds = 0.0\n")
    return loop_world(root, toml=toml, searcher=FakeSearcher({FAILING: failures}))


async def run_until_searched(world: LoopWorld, loop: GrpoLoop, times: int) -> None:
    """Runs the loop until FAILING was searched `times` times, then stops it (the stop writes a last status)."""
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop))
    while world.searcher.searched.count(FAILING) < times and not task.done():
        await asyncio.sleep(0)
    stop.set()
    await task


def last_status(world: LoopWorld, column: str) -> float | None:
    return RunReader(world.paths.directory).series("status").columns[column][-1]


async def test_server_failures_are_counted_in_the_status(tmp_path: Path) -> None:
    world = failing_world(tmp_path, failures=2)
    record_version_zero(world)
    await run_until_searched(world, world.loop(), times=3)
    assert last_status(world, "server_failures") == 2


async def test_a_statement_is_given_up_after_its_retries(tmp_path: Path) -> None:
    world = failing_world(tmp_path, failures=10)
    record_version_zero(world)
    await run_until_searched(world, world.loop(), times=4)
    assert last_status(world, "statements_given_up") == 1


async def test_a_statement_is_not_given_up_within_its_retries(tmp_path: Path) -> None:
    world = failing_world(tmp_path, failures=10)
    record_version_zero(world)
    await run_until_searched(world, world.loop(), times=3)
    assert last_status(world, "statements_given_up") == 0


def dead_server_world(root: Path, settings: str = "") -> LoopWorld:
    toml = LOOP_TOML.replace(
        "status_seconds = 0.01\n",
        f"status_seconds = 0.01\nserver_failure_pause_seconds = 0.0\nserver_failure_window = 4\n{settings}",
    )
    world = loop_world(root, toml=toml)
    world.servers.down.add("policy-gpu1")
    return world


def events_from_the_first_pause(world: LoopWorld) -> list[str]:
    events = world.searcher.events
    return events[events.index("pause") :]


async def test_a_dead_server_is_restarted(tmp_path: Path) -> None:
    world = dead_server_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.servers.restarted == ["policy-gpu1"]


async def test_the_searches_pause_while_a_dead_server_restarts(tmp_path: Path) -> None:
    world = dead_server_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert events_from_the_first_pause(world)[:3] == ["pause", "restart policy-gpu1 v0", "resume"]


async def test_a_server_that_stays_down_stops_the_loop(tmp_path: Path) -> None:
    world = dead_server_world(tmp_path)
    world.servers.restarts_fail = True
    record_version_zero(world)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)


async def test_without_restarts_a_dead_server_stops_the_loop(tmp_path: Path) -> None:
    world = dead_server_world(tmp_path, "restart_dead_servers = false\n")
    record_version_zero(world)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)
    assert world.servers.restarted == []


async def test_servers_that_answer_again_are_checked_but_not_restarted(tmp_path: Path) -> None:
    world = dead_server_world(tmp_path)
    world.servers.down.clear()
    world.searcher.server_failures = {problem_name(statement(number).statement): 2 for number in range(6)}
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert events_from_the_first_pause(world)[:2] == ["pause", "resume"]


OVERFULL_GPU = LOOP_TOML.replace(
    'url = "http://127.0.0.1:8100/v1"\n', 'url = "http://127.0.0.1:8100/v1"\nmemory_share = 0.7\n'
).replace('url = "http://127.0.0.1:8200/v1"\n', 'url = "http://127.0.0.1:8200/v1"\nmemory_share = 0.4\n')


@pytest.mark.parametrize(
    "toml",
    [
        LOOP_TOML.replace("gpus = [0, 1]", "gpus = []"),
        LOOP_TOML.replace("gpus = [0, 1]", "gpus = [0, 0]"),
        OVERFULL_GPU,
    ],
    ids=["no gpu", "a gpu twice", "memory shares above one"],
)
def test_an_impossible_gpu_layout_is_refused(toml: str) -> None:
    with pytest.raises(ValueError):
        parse_loop_config(toml)


def training_arguments(root: Path, toml: str) -> list[str]:
    world = loop_world(root, toml=toml)
    request = TrainingRequest(1, "", root / "trees", "run", root / "checkpoints", False)
    return SubprocessTrainer(world.paths, world.config.training).arguments(request, root / "phase.toml")


def test_several_training_gpus_start_a_torchrun_rank_each(tmp_path: Path) -> None:
    arguments = training_arguments(tmp_path, LOOP_TOML)
    assert arguments[1:6] == [
        "-m",
        "torch.distributed.run",
        "--standalone",
        "--nproc-per-node=2",
        "experiments/grpo_phase.py",
    ]


def test_one_training_gpu_starts_a_single_process(tmp_path: Path) -> None:
    assert (
        training_arguments(tmp_path, LOOP_TOML.replace("gpus = [0, 1]", "gpus = [0]"))[1] == "experiments/grpo_phase.py"
    )


def test_the_training_job_merges_the_new_adapters(tmp_path: Path) -> None:
    assert "--merge-adapters" in training_arguments(tmp_path, LOOP_TOML)
