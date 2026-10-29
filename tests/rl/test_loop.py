import tomllib
from pathlib import Path

import pytest
from loop_fakes import LOOP_TOML, FakeTrainer, loop_world, record_version_zero, run_until

from lean_search.expert_iteration.serving import ModelVersion, read_current, read_versions
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.loop import (
    PhaseStage,
    evaluation_due,
    phase_config_text,
    read_progress,
    request_evaluation,
    value_published_by,
)
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.tree_store import TreeStore

TEMPLATE = (Path(__file__).resolve().parents[2] / "experiments/configs/grpo/phase.toml").read_text(encoding="utf-8")
VERSION = ModelVersion(3, "phase-3/policy/adapter", "phase-2/value/adapter", "2026-10-29T10:00:00+00:00", "phase 3")


def phase_table(value_share: float = 0.0, train_value: bool = True) -> dict:
    return tomllib.loads(phase_config_text(TEMPLATE, VERSION, 4, value_share, train_value))


def test_phase_config_continues_the_published_policy_adapter() -> None:
    assert phase_table()["policy"]["initial_adapter"] == "phase-3/policy/adapter"


def test_phase_config_continues_the_published_value_adapter() -> None:
    assert phase_table()["value"]["initial_adapter"] == "phase-2/value/adapter"


def test_phase_config_without_value_training_has_no_value_part() -> None:
    assert "value" not in phase_table(train_value=False)


@pytest.mark.parametrize("section", ["reward", "value_targets"])
def test_phase_config_sets_mu_in_reward_and_targets(section: str) -> None:
    assert phase_table(value_share=0.15)[section]["value_share"] == 0.15


def test_phase_config_seeds_each_phase_differently() -> None:
    assert phase_table()["policy"]["optimization"]["seed"] == 4


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


async def test_servers_serve_each_published_version(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.servers.served == [0, 1, 2]


async def test_the_second_phase_continues_from_the_first_phases_adapter(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    second = tomllib.loads(world.trainer.requests[1].config_text)
    assert second["policy"]["initial_adapter"] == read_versions(world.paths.models)[1].policy_adapter


async def test_a_value_model_failing_the_gate_is_not_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=False))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).value_adapter == "value-v0-adapter"


async def test_mu_turns_on_after_a_value_model_passed_the_gate(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    shares = [tomllib.loads(request.config_text)["reward"]["value_share"] for request in world.trainer.requests[:2]]
    assert shares == [0.0, 0.15]


async def test_without_a_benchmark_the_value_model_does_not_train(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=LOOP_TOML.replace('value_benchmark = "gate/benchmark.json.gz"', ""))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert not world.trainer.requests[0].train_value


@pytest.mark.parametrize("family", ["status", "curriculum", "search", "grpo", "timing"])
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
    assert world.evaluations.runs == [(EvaluationKind.MINIF2F, 0)]


async def test_a_request_during_sampling_runs_at_the_next_pause(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=1, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.MINIF2F)
    )
    assert world.evaluations.runs == [(EvaluationKind.MINIF2F, 1)]


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
    assert world.evaluations.runs == [(EvaluationKind.PROBE, 0)]
