import tomllib
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

from lean_search.expert_iteration.serving import MergedPublisher, read_current
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.health_checks import clear_health_stop, publish_rollback, read_health_stop
from lean_search.rl.loop import request_evaluation
from lean_search.rl.tree_store import TreeStore

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
COLLAPSE = [(0.8, 0.4), (0.5, 0.4)]


def collapsing_world(root: Path, rates: list[tuple[float, float]] = COLLAPSE) -> LoopWorld:
    world = loop_world(root, HELD_OUT_EVERY_PHASE, evaluations=FakeEvaluations(held_out_rates=list(rates)))
    record_version_zero(world)
    return world


async def stopped_world(root: Path, rates: list[tuple[float, float]] = COLLAPSE) -> LoopWorld:
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


async def test_a_held_out_collapse_stops_the_loop_after_the_phase(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    assert world.phases_done() == 1


async def test_a_held_out_collapse_records_the_last_good_version(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    stop = read_health_stop(world.paths.health_stop)
    assert stop is not None and (stop.policy_version, stop.last_good_version) == (1, 0)


async def test_a_loop_after_a_health_stop_refuses_to_start(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    served = list(world.servers.served)
    with pytest.raises(RuntimeError):
        await run_until(world, world.loop(), phases=2)
    assert world.servers.served == served


async def test_a_cleared_health_stop_lets_the_loop_continue(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path, [*COLLAPSE, (0.8, 0.4)])
    clear_health_stop(world.paths.health_stop)
    await run_until(world, world.loop(), phases=2)
    assert world.phases_done() == 2


async def test_a_rollback_publishes_the_last_good_policy_as_a_new_version(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path)
    publisher = MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing)
    publish_rollback(world.paths.models, publisher, 0)
    current = read_current(world.paths.models)
    assert (current.version, current.policy_adapter, current.trigger) == (2, "", "rollback to v0")


async def test_the_phase_after_a_rollback_continues_the_last_good_policy(tmp_path: Path) -> None:
    world = await stopped_world(tmp_path, [*COLLAPSE, (0.8, 0.4)])
    publish_rollback(
        world.paths.models, MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing), 0
    )
    clear_health_stop(world.paths.health_stop)
    await run_until(world, world.loop(), phases=2)
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
