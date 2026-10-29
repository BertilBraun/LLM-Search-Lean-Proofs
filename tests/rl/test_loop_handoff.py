"""The loop's publish from merges the persistent training job hands off in host memory (rl/README.md, "Persistent
trainer"): the servers load them at once, the searches resume, and the version is recorded once on disk."""

import shutil
from pathlib import Path

from loop_fakes import (
    LOOP_TOML,
    FakeTrainer,
    FakeValueScorer,
    LoopWorld,
    hand_off,
    loop_world,
    record_version_zero,
    run_until,
    taking_over_handoff,
)

from lean_search.expert_iteration.serving import MERGED_MARKER, MergedPublisher, read_current, write_json_atomically
from lean_search.monitoring.families import PauseSegments
from lean_search.monitoring.store import RunReader
from lean_search.policy.adapters import PremergedWeights
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.loop import (
    PHASE_OUTCOME_FILE,
    LoopProgress,
    PhaseStage,
    read_phase_outcome,
    request_evaluation,
    with_trainer_timings,
)
from lean_search.rl.training_phase import TrainerTimings, publish_phase
from lean_search.rl.value_trends import scored_versions
from lean_search.training.resident import HostDirectories


def handoff_world(root: Path, trainer: FakeTrainer | None = None, scorer: FakeValueScorer | None = None) -> LoopWorld:
    host = (root / "host").as_posix()
    settings = f'value_every_phases = 1\npersistent = true\nhost_directory = "{host}"\n'
    toml = LOOP_TOML.replace("value_every_phases = 1\n", settings)
    world = loop_world(root, toml=toml, trainer=trainer, scorer=scorer)
    world.trainer.handoff = handoff_root(world)
    world.merge = taking_over_handoff(handoff_root(world), world.searcher.events)
    record_version_zero(world)
    return world


def handoff_root(world: LoopWorld) -> Path:
    return HostDirectories(world.config.host_directory()).handoff


def after_first_pause(world: LoopWorld) -> list[str]:
    events = world.searcher.events
    return events[events.index("pause") :]


async def test_the_servers_load_the_new_version_from_host_memory(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert Path(world.servers.served_policy_weights[1]).parent == handoff_root(world)


async def test_the_version_is_recorded_with_its_weights_on_disk(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    current = read_current(world.paths.models)
    assert (current.version, (Path(current.policy_weights) / MERGED_MARKER).exists()) == (1, True)


async def test_host_memory_is_cleared_once_the_version_is_recorded(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert not handoff_root(world).exists()


async def test_the_searches_resume_before_the_weights_are_written_to_disk(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    events = after_first_pause(world)
    assert events.index("resume") < events.index("write v0001/policy")


async def test_with_evaluations_due_the_weights_are_on_disk_before_they_run(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    loop = world.loop()
    await run_until(world, loop, phases=1, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE))
    events = after_first_pause(world)
    assert events.index("write v0001/policy") < events.index("resume")


async def test_a_new_value_model_is_written_from_host_memory_too(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert "write v0001/value" in after_first_pause(world)


async def test_the_timing_line_records_the_write_to_disk_apart_from_the_pause(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert RunReader(world.paths.directory).series("timing").columns["pause.durable_write_seconds"][-1] > 0


async def interrupted_after_the_wake(world: LoopWorld) -> None:
    """Phase 1 trained and its merges handed off, the loop gone before it recorded version 1."""
    await world.trainer.train(world.loop().training_request(1, value_share=0.0))
    write_json_atomically(world.paths.progress, LoopProgress(phase=1, stage=PhaseStage.PUBLISHING))


async def test_a_restart_before_the_record_serves_the_handed_off_merges_again(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await interrupted_after_the_wake(world)
    await run_until(world, world.loop(), phases=1)
    assert Path(world.servers.served_policy_weights[1]).parent == handoff_root(world)


async def test_a_restart_that_lost_host_memory_serves_merges_from_disk(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await interrupted_after_the_wake(world)
    shutil.rmtree(handoff_root(world))
    await run_until(world, world.loop(), phases=1)
    assert Path(world.servers.served_policy_weights[1]).is_relative_to(world.paths.weights)


async def test_a_restart_before_the_record_records_the_version(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await interrupted_after_the_wake(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).trigger == "phase 1"


async def test_a_restart_after_the_record_clears_host_memory(tmp_path: Path) -> None:
    """The version recorded on disk, the loop gone before it cleared host memory (or stopped while the record's
    thread ran)."""
    world = handoff_world(tmp_path)
    await interrupted_after_the_wake(world)
    outcome = read_phase_outcome(world.paths.phase_checkpoints(1) / PHASE_OUTCOME_FILE)
    publish_phase(
        world.paths.models, MergedPublisher(world.config.serving, world.paths.weights, world.merge), outcome, "phase 1"
    )
    await run_until(world, world.loop(), phases=1)
    assert not handoff_root(world).exists()


def test_a_start_clears_merges_left_in_host_memory_by_a_recorded_phase(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    hand_off(handoff_root(world), PremergedWeights("start-policy", "an adapter of an earlier phase"))
    world.loop().clear_stale_handoff()
    assert not any(handoff_root(world).iterdir())


async def test_a_restart_before_the_record_clears_a_partly_written_merge(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await interrupted_after_the_wake(world)
    partial = handoff_root(world) / "0123456789abcdef.tmp"
    partial.mkdir()
    world.loop().clear_stale_handoff()
    assert not partial.exists()


async def test_each_phase_is_prepared_as_its_sampling_starts(tmp_path: Path) -> None:
    world = handoff_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert [request.phase for request in world.trainer.prepared] == [1, 2]


def test_a_persistent_jobs_model_building_counts_as_its_start() -> None:
    timings = TrainerTimings(build_seconds=30.0, total_seconds=100.0)
    assert with_trainer_timings(PauseSegments(), timings, 110.0).trainer_start_seconds == 40.0


async def test_the_benchmark_is_scored_with_each_value_version_once_recorded(tmp_path: Path) -> None:
    world = handoff_world(tmp_path, scorer=FakeValueScorer())
    await run_until(world, world.loop(), phases=2)
    assert scored_versions(world.paths.value_benchmark)[:2] == [0, 1]


async def test_the_benchmark_scoring_finishes_before_the_next_pause_after_an_early_resume(tmp_path: Path) -> None:
    world = handoff_world(tmp_path, scorer=FakeValueScorer())
    await run_until(world, world.loop(), phases=2)
    events = world.searcher.events
    second_pause = [index for index, event in enumerate(events) if event == "pause"][1]
    assert events[:second_pause].count("scored") == 2
