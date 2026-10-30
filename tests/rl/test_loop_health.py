import asyncio
import dataclasses
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from loop_fakes import (
    LOOP_TOML,
    FakeEvaluations,
    LoopWorld,
    loop_world,
    merge_by_writing,
    record_version_zero,
    run_until,
)

from lean_search.expert_iteration.serving import (
    MergedPublisher,
    ModelVersion,
    read_current,
    read_versions,
    write_json_atomically,
)
from lean_search.monitoring.alerts import AlertThresholds, run_alerts
from lean_search.monitoring.families import HealthMeasurements, HealthThresholds, PhaseHealth
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.health_checks import (
    append_health,
    clear_health_stop,
    publish_rollback,
    read_health_stop,
    read_rejected_versions,
    roll_back_by_hand,
    rollback_trigger,
)
from lean_search.rl.loop import GrpoLoop, LoopProgress, PhaseStage, read_progress, request_evaluation
from lean_search.rl.training_phase import TrainingPhaseConfig, label_phase_data
from lean_search.rl.tree_store import TreeStore
from lean_search.search.records import from_json_object

HELD_OUT_BLOCK = """[evaluation.held_out_states]
max_expansions = 1
max_wall_seconds = 600.0
concurrency = 4
every_hours = 0.0
at_start = false"""
# Version 0's held-out baseline at the start, then a held-out evaluation after every phase.
HELD_OUT_EVERY_PHASE = LOOP_TOML.replace(
    HELD_OUT_BLOCK, HELD_OUT_BLOCK.replace("every_hours = 0.0", "every_hours = 0.0001").replace("false", "true")
)
# Version 0's baseline, then the held-out valid-Lean rate of each phase's version (the last repeats).
COLLAPSE_ONCE = [(0.8, 0.4), (0.5, 0.4), (0.8, 0.4)]
COLLAPSE_TWICE = [(0.8, 0.4), (0.5, 0.4), (0.5, 0.4)]


def collapsing_world(
    root: Path,
    rates: list[tuple[float, float]],
    toml: str = HELD_OUT_EVERY_PHASE,
    lean_checks: asyncio.Event | None = None,
) -> LoopWorld:
    evaluations = FakeEvaluations(held_out_rates=list(rates), lean_checks=lean_checks)
    world = loop_world(root, toml, evaluations=evaluations)
    record_version_zero(world)
    return world


async def stopped_world(root: Path, rates: list[tuple[float, float]] = COLLAPSE_TWICE) -> LoopWorld:
    """Phase 1 collapses and rolls back to version 0 (version 2), phase 2 collapses again: the loop stops."""
    world = collapsing_world(root, rates)
    await run_until(world, world.loop(), phases=3)
    return world


async def test_a_phase_waits_for_its_trainable_groups(tmp_path: Path) -> None:
    toml = LOOP_TOML.replace("max_sampling_minutes = 2.0", "max_sampling_minutes = 10000.0").replace(
        "min_trainable_groups = 2", "min_trainable_groups = 5"
    )
    world = loop_world(tmp_path, toml)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert sum(entry.summary.trainable_groups for entry in TreeStore(world.paths.trees).phase_entries(1)) >= 5


async def test_each_finished_tree_records_its_trainable_groups(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert {entry.summary.trainable_groups for entry in TreeStore(world.paths.trees).entries} == {1}


async def test_each_finished_tree_records_the_loops_expansion_budget(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("concurrency = 2\n", "concurrency = 2\nmax_expansions = 48\n"))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert {entry.summary.expansion_budget for entry in TreeStore(world.paths.trees).entries} == {48}


@pytest.mark.parametrize("family", ["budget", "health"])
async def test_a_phase_writes_its_signals(tmp_path: Path, family: str) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert family in RunReader(world.paths.directory).families()


async def test_the_health_check_reports_to_the_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert "Health of phase 1" in capsys.readouterr().out


async def test_a_healthy_held_out_evaluation_keeps_the_loop_running(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, [(0.8, 0.4), (0.75, 0.4)])
    await run_until(world, world.loop(), phases=2)
    assert world.phases_done() == 2


async def test_a_held_out_collapse_rolls_back_to_the_last_good_version(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=1)
    current = read_current(world.paths.models)
    assert (current.version, current.trigger) == (2, "rollback to v0 after phase 1")


async def test_the_servers_serve_the_rolled_back_version(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=1)
    assert world.servers.served[-1] == 2


async def test_the_searches_continue_after_a_rollback(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=3)
    assert world.phases_done() == 3


async def test_the_phase_after_an_automatic_rollback_trains_on_from_the_rolled_back_policy(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=2)
    assert tomllib.loads(world.trainer.requests[1].config_text)["policy"]["initial_adapter"] == ""


async def test_a_rollback_alerts_in_the_log(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    assert any(message.startswith("Alert: ") and "rolled back to version 0" in message for message in messages)


async def test_a_rollback_is_on_the_dashboard(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=1)
    alerts = run_alerts(RunReader(world.paths.directory), AlertThresholds(), time.time())
    assert "Policy rolled back" in {alert.title for alert in alerts}


async def test_a_second_collapse_within_the_window_stops_the_loop(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    assert world.phases_done() == 2


async def test_with_rollbacks_off_a_collapse_stops_the_loop_after_the_phase(tmp_path: Path) -> None:
    toml = HELD_OUT_EVERY_PHASE + "\n[health]\nrollback_window_phases = 0\n"
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, toml)
    await run_until(world, world.loop(), phases=3)
    assert world.phases_done() == 1


async def test_a_held_out_collapse_records_the_last_good_version(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    stop = read_health_stop(world.paths.health_stop)
    assert stop is not None and (stop.policy_version, stop.last_good_version) == (3, 0)


async def test_a_restart_after_the_rollback_does_not_roll_back_again(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=1)
    progress = read_progress(world.paths.progress)
    write_json_atomically(world.paths.progress, dataclasses.replace(progress, phase=1, stage=PhaseStage.EVALUATING))
    world.paths.phases.unlink()
    await run_until(world, world.loop(), phases=1)
    assert [version.trigger for version in read_versions(world.paths.models)] == [
        "initial",
        "phase 1",
        "rollback to v0 after phase 1",
    ]


async def test_a_missing_version_zero_held_out_baseline_refuses_to_start(tmp_path: Path) -> None:
    toml = HELD_OUT_EVERY_PHASE.replace(
        "every_hours = 0.0001\nat_start = true", "every_hours = 0.0001\nat_start = false"
    )
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, toml)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=1)


async def test_a_drop_of_the_sampled_blocks_valid_lean_brings_the_held_out_states_forward(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    for phase in (1, 2):
        measured = HealthMeasurements(valid_block_rate=1.0)
        append_health(world.paths.health, PhaseHealth(phase, 0, measured, HealthThresholds(0.005, 0.1)))
    write_json_atomically(world.paths.progress, LoopProgress(phase=3))
    await run_until(world, world.loop(), phases=2)
    assert EvaluationKind.HELD_OUT_STATES in {run.kind for run, _ in world.evaluations.runs}


async def test_a_loop_after_a_health_stop_refuses_to_start(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    served = list(world.servers.served)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=3)
    assert world.servers.served == served


async def test_a_cleared_health_stop_lets_the_loop_continue(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path, [*COLLAPSE_TWICE, (0.8, 0.4)])
    clear_health_stop(world.paths.health_stop)
    await run_until(world, world.loop(), phases=3)
    assert world.phases_done() == 3


async def test_a_rollback_publishes_the_last_good_policy_as_a_new_version(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    publisher = MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing)
    publish_rollback(world.paths.models, publisher, 0, rollback_trigger(0))
    current = read_current(world.paths.models)
    assert (current.version, current.policy_adapter, current.trigger) == (4, "", "rollback to v0")


async def test_the_phase_after_a_rollback_continues_the_last_good_policy(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path, [*COLLAPSE_TWICE, (0.8, 0.4)])
    publish_rollback(
        world.paths.models,
        MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing),
        0,
        rollback_trigger(0),
    )
    clear_health_stop(world.paths.health_stop)
    await run_until(world, world.loop(), phases=3)
    assert tomllib.loads(world.trainer.requests[-1].config_text)["policy"]["initial_adapter"] == ""


async def test_the_last_good_versions_adapter_outlives_the_retention(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML + "\n[retention]\nadapter_versions = 2\n")
    record_version_zero(world)
    await run_until(
        world,
        world.loop(),
        phases=4,
        on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.HELD_OUT_STATES),
    )
    remaining = sorted(
        path.parent.parent.name for path in world.paths.checkpoints_root.glob("*_phase_*/policy/adapter")
    )
    assert remaining == ["test_loop_phase_0001", "test_loop_phase_0003", "test_loop_phase_0004"]


HEALTHY = [(0.8, 0.4), (0.8, 0.4)]
# Searches the loop finishes beside the held-out states' Lean checks before the test ends them.
SEARCHES_BESIDE = 4


async def until(condition: Callable[[], bool], task: asyncio.Task[None], seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and not task.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.001)


@dataclass(frozen=True)
class HeldOutTail:
    """What the first held-out run after a phase saw while it held its Lean checks."""

    searched_beside: int
    next_phase_trees: int
    health_checked: bool
    stopped_by_itself: bool


async def through_a_held_out_tail(
    world: LoopWorld, lean_checks: asyncio.Event, phases: int = 1, loop: GrpoLoop | None = None
) -> HeldOutTail:
    """Runs the loop until the first held-out run after a phase waits on its Lean checks and `SEARCHES_BESIDE` searches
    finished since it started and as many trees landed in the next phase (or a timeout), ends the checks, and runs on
    until `phases` phases closed."""
    stop = asyncio.Event()
    task = asyncio.create_task((loop or world.loop()).run(stop))
    await until(lambda: bool(world.evaluations.generated), task)
    started = len(world.searcher.searched)

    def next_phase_trees() -> int:
        return len(TreeStore(world.paths.trees).phase_entries(2))

    await until(lambda: len(world.searcher.searched) >= started + SEARCHES_BESIDE, task)
    searched_beside = len(world.searcher.searched) - started
    await until(lambda: next_phase_trees() >= SEARCHES_BESIDE, task)
    trees = next_phase_trees()
    health_checked = world.paths.health.exists()
    lean_checks.set()
    await until(lambda: world.phases_done() >= phases, task)
    stopped_by_itself = task.done()
    stop.set()
    await task
    return HeldOutTail(searched_beside, trees, health_checked, stopped_by_itself)


async def test_the_searches_resume_once_the_held_out_states_are_sampled(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    tail = await through_a_held_out_tail(collapsing_world(tmp_path, HEALTHY, lean_checks=lean_checks), lean_checks)
    assert tail.searched_beside >= SEARCHES_BESIDE


async def test_the_searches_beside_the_held_out_states_count_toward_the_next_phase(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    tail = await through_a_held_out_tail(collapsing_world(tmp_path, HEALTHY, lean_checks=lean_checks), lean_checks)
    assert tail.next_phase_trees >= SEARCHES_BESIDE


async def test_the_health_checks_wait_for_the_held_out_result(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    tail = await through_a_held_out_tail(collapsing_world(tmp_path, HEALTHY, lean_checks=lean_checks), lean_checks)
    assert not tail.health_checked


async def test_a_rollback_beside_sampling_pauses_the_searches_around_the_swap(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, lean_checks=lean_checks)
    await through_a_held_out_tail(world, lean_checks)
    events = world.searcher.events
    swaps = [f"swap {name} v2" for name in world.servers.names]
    start = events.index(swaps[0])
    assert events[start - 1 : start + len(swaps) + 1] == ["pause", *swaps, "resume"]


async def test_a_hard_stop_beside_sampling_still_stops_the_loop(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    toml = HELD_OUT_EVERY_PHASE + "\n[health]\nrollback_window_phases = 0\n"
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, toml, lean_checks)
    tail = await through_a_held_out_tail(world, lean_checks, phases=3)
    assert tail.stopped_by_itself


async def test_a_stop_during_the_held_out_states_last_lean_checks_runs_them_again_at_the_restart(
    tmp_path: Path,
) -> None:
    lean_checks = asyncio.Event()
    world = collapsing_world(tmp_path, HEALTHY, lean_checks=lean_checks)
    stop = asyncio.Event()
    task = asyncio.create_task(world.loop().run(stop))
    await until(lambda: bool(world.evaluations.generated), task)
    stop.set()
    await task
    lean_checks.set()
    await run_until(world, world.loop(), phases=1)
    held_out = [phase for run, phase in world.evaluations.runs if run.kind == EvaluationKind.HELD_OUT_STATES]
    assert held_out == [0, 1, 1]


async def test_a_collapse_rejects_the_collapsed_version(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=1)
    assert read_rejected_versions(world.paths.rejected_versions) == (1,)


async def test_a_hard_stop_rejects_the_collapsed_version_too(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    assert read_rejected_versions(world.paths.rejected_versions) == (1, 3)


async def test_the_next_phase_trains_without_the_rejected_versions_samples(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, COLLAPSE_ONCE)
    await run_until(world, world.loop(), phases=2)
    assert tomllib.loads(world.trainer.requests[1].config_text)["excluded_policy_versions"] == [1]


def publisher_of(world: LoopWorld) -> MergedPublisher:
    return MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing)


async def test_a_rollback_by_hand_rejects_the_version_rolled_back_from(tmp_path: Path) -> None:
    world = collapsing_world(tmp_path, HEALTHY)
    await run_until(world, world.loop(), phases=1)
    roll_back_by_hand(world.paths.models, publisher_of(world), 0, world.paths.rejected_versions)
    assert read_rejected_versions(world.paths.rejected_versions) == (1,)


async def test_a_rollback_by_hand_after_a_hard_stop_rejects_nothing_new(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    roll_back_by_hand(world.paths.models, publisher_of(world), 0, world.paths.rejected_versions)
    assert read_rejected_versions(world.paths.rejected_versions) == (1, 3)


def tree_sampling_versions(world: LoopWorld, phase: int) -> set[int | None]:
    return {
        expansion.policy_version
        for record in TreeStore(world.paths.trees).records(phase)
        for expansion in record.expansions
    }


def trained_group_versions(world: LoopWorld, phase: int) -> set[int | None]:
    """The versions that sampled the groups the phase's training request trains on."""
    request = next(request for request in world.trainer.requests if request.phase == phase)
    config = from_json_object(TrainingPhaseConfig, tomllib.loads(request.config_text))
    labelled = label_phase_data(TreeStore(world.paths.trees).records(phase), config)
    versions = set()
    for tree in labelled.policy_trees:
        by_round = {(expansion.node_id, expansion.feedback): expansion.policy_version for expansion in tree.texts}
        versions |= {by_round[group.node_id, group.feedback] for group in tree.groups}
    return versions


async def test_the_collapsed_version_samples_next_phase_trees_beside_the_held_out_tail(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, lean_checks=lean_checks)
    await through_a_held_out_tail(world, lean_checks, phases=2)
    assert 1 in tree_sampling_versions(world, 2)


async def test_no_trained_group_of_the_next_phase_was_sampled_by_the_collapsed_version(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, lean_checks=lean_checks)
    await through_a_held_out_tail(world, lean_checks, phases=2)
    assert 1 not in trained_group_versions(world, 2)


class RecordingPublisher(MergedPublisher):
    def __init__(self, world: LoopWorld) -> None:
        super().__init__(world.config.serving, world.paths.weights, merge_by_writing)
        self.events = world.searcher.events

    def prepare(self, version: ModelVersion) -> ModelVersion:
        self.events.append(f"prepare v{version.version}")
        return super().prepare(version)


async def test_a_rollback_beside_sampling_pauses_the_searches_before_its_merge(tmp_path: Path) -> None:
    lean_checks = asyncio.Event()
    world = collapsing_world(tmp_path, COLLAPSE_ONCE, lean_checks=lean_checks)
    loop = world.loop()
    loop.publisher = RecordingPublisher(world)
    await through_a_held_out_tail(world, lean_checks, loop=loop)
    events = world.searcher.events
    assert events[events.index("prepare v2") - 1] == "pause"
