import asyncio
import dataclasses
import tomllib
from pathlib import Path

import pytest
from loop_fakes import (
    LOOP_TOML,
    SERVE_SECONDS,
    FakeEvaluations,
    FakeSearcher,
    FakeTrainer,
    LoopWorld,
    loop_world,
    record_version_zero,
    run_until,
    statement,
    zero,
)

from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.serving import ModelVersion, read_current, read_versions, write_json_atomically
from lean_search.monitoring.families import PauseSegments, ValueAbResult
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.loop import (
    GIB,
    GrpoLoop,
    GrpoLoopPaths,
    PhaseStage,
    TrainingRequest,
    earlier_value_ab_results,
    evaluation_due,
    phase_config_text,
    read_progress,
    request_evaluation,
    value_published_by,
)
from lean_search.rl.loop_config import EvaluationTarget, EvaluationValueModel, parse_loop_config
from lean_search.rl.loop_services import SubprocessTrainer
from lean_search.rl.training_phase import TrainerTimings
from lean_search.rl.tree_store import TreeStore

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


def test_phase_config_gates_against_the_published_value_adapter() -> None:
    assert phase_table()["value"]["published_adapter"] == "phase-2/value/adapter"


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
        ("pause.gate_seconds", 7.0),
        ("pause.merge_seconds", 11.0),
        ("pause.wake_seconds", SERVE_SECONDS.weights),
        ("pause.resume_seconds", SERVE_SECONDS.resume),
    ],
)
async def test_the_timing_line_records_the_pause_segments(tmp_path: Path, column: str, seconds: float) -> None:
    trainer = FakeTrainer(timings=TrainerTimings(gate_seconds=7.0, merge_seconds=11.0))
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


async def test_a_value_model_failing_the_gate_is_not_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=False))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).value_adapter == "value-v0-adapter"


VALUE_AB_TOML = (
    LOOP_TOML
    + """
[evaluation.value_ab]
max_expansions = 16
max_wall_seconds = 600.0
concurrency = 4
every_hours = 1.0
"""
)


def value_shares(world: LoopWorld) -> list[float]:
    return [tomllib.loads(request.config_text)["reward"]["value_share"] for request in world.trainer.requests]


async def test_mu_turns_on_after_the_gate_and_the_value_ab_passed(tmp_path: Path) -> None:
    evaluations = FakeEvaluations(value_ab_passes=True)
    world = loop_world(tmp_path, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=True), evaluations=evaluations)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert value_shares(world)[:2] == [0.0, 0.15]


async def test_mu_stays_off_when_the_value_ab_does_not_pass(tmp_path: Path) -> None:
    world = loop_world(tmp_path, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert value_shares(world)[:2] == [0.0, 0.0]


def worse_value_world(root: Path) -> LoopWorld:
    evaluations = FakeEvaluations(value_ab_worse=True)
    return loop_world(root, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=True), evaluations=evaluations)


async def test_a_value_model_the_ab_finds_worse_is_replaced_by_v0(tmp_path: Path) -> None:
    world = worse_value_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert read_current(world.paths.models).value_adapter == "value-v0-adapter"


async def test_the_servers_serve_v0_after_the_ab_found_the_published_value_model_worse(tmp_path: Path) -> None:
    world = worse_value_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.servers.served[-1] == read_current(world.paths.models).version


async def test_value_training_continues_v0_after_the_ab_found_the_published_model_worse(tmp_path: Path) -> None:
    world = worse_value_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert tomllib.loads(world.trainer.requests[1].config_text)["value"]["initial_adapter"] == "value-v0-adapter"


async def test_mu_turns_off_when_the_ab_finds_the_published_value_model_worse(tmp_path: Path) -> None:
    evaluations = FakeEvaluations(value_ab_passes=True)
    world = loop_world(tmp_path, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=True), evaluations=evaluations)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    evaluations.value_ab_passes, evaluations.value_ab_worse = False, True
    request_evaluation(world.paths, EvaluationKind.VALUE_AB)
    await run_until(world, world.loop(), phases=2)
    assert value_shares(world)[1] == 0.0


def write_value_ab(paths: GrpoLoopPaths, version: int, published_value_version: int) -> None:
    directory = paths.evaluation_directory(EvaluationKind.VALUE_AB, version, 0, EvaluationValueModel.PUBLISHED)
    result = dataclasses.replace(zero(ValueAbResult), published_value_version=published_value_version)
    write_json_atomically(directory / "comparison.json", result)


def test_value_abs_pool_with_the_other_runs_of_the_same_published_value_model(tmp_path: Path) -> None:
    paths = GrpoLoopPaths(tmp_path, tmp_path, tmp_path, "loop")
    for version, published_value_version in ((2, 1), (3, 2), (4, 2), (5, 2)):
        write_value_ab(paths, version, published_value_version)
    assert len(earlier_value_ab_results(paths, 5, 2)) == 2


async def test_the_value_ab_runs_the_reference_arm_before_the_published_one(tmp_path: Path) -> None:
    world = loop_world(tmp_path, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    arms = [model for kind, model in world.evaluations.value_models if kind == EvaluationKind.VALUE_AB]
    assert arms == [EvaluationValueModel.INITIAL, EvaluationValueModel.PUBLISHED]


async def test_the_value_ab_waits_until_a_value_model_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, VALUE_AB_TOML, trainer=FakeTrainer(value_passes=False))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.value_models == []


async def test_the_probe_runs_with_the_reference_value_model_once_another_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=2, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    assert "kept_value" in world.servers.value_weights[0]


async def test_the_value_servers_return_to_the_published_value_model_after_evaluating(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=2, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    assert world.servers.value_weights[-1] == read_versions(world.paths.models)[1].value_weights


async def test_the_value_servers_swap_only_after_every_server_woke(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=True))
    record_version_zero(world)
    await run_until(
        world, world.loop(), phases=1, on_sampling=lambda: request_evaluation(world.paths, EvaluationKind.PROBE)
    )
    events = world.servers.events
    first_swap = next(index for index, event in enumerate(events) if event.startswith("value "))
    last_wake = max(index for index, event in enumerate(events) if event.startswith("wake "))
    assert last_wake < first_swap


async def test_evaluations_need_no_value_swap_while_the_reference_is_published(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    request_evaluation(world.paths, EvaluationKind.PROBE)
    await run_until(world, world.loop(), phases=1)
    assert world.servers.value_weights == []


async def test_value_training_continues_the_last_trained_adapter(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=False))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    first, second = world.trainer.requests[:2]
    initial = tomllib.loads(second.config_text)["value"]["initial_adapter"]
    assert initial == str(first.output_directory / "value/adapter")


async def test_value_training_gates_against_the_published_adapter(tmp_path: Path) -> None:
    world = loop_world(tmp_path, trainer=FakeTrainer(value_passes=False))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert tomllib.loads(world.trainer.requests[1].config_text)["value"]["published_adapter"] == "value-v0-adapter"


async def test_value_training_sees_the_window_of_recent_phases(tmp_path: Path) -> None:
    toml = LOOP_TOML.replace("value_every_phases = 1\n", "value_every_phases = 1\nvalue_window_phases = 2\n")
    world = loop_world(tmp_path, toml)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=3)
    store = TreeStore(world.paths.trees)
    assert world.trainer.requests[2].value_trees == (store.phase_directory(2), store.phase_directory(3))


async def test_the_value_model_trains_every_fourth_phase_by_default(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("value_every_phases = 1\n", ""))
    record_version_zero(world)
    await run_until(world, world.loop(), phases=4)
    assert [request.train_value for request in world.trainer.requests] == [False, False, False, True]


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


BASELINE_TOML = LOOP_TOML.replace(
    "every_hours = 0.0\nat_start = false\n\n[evaluation.held_out_states]",
    "every_hours = 0.0\nat_start = true\nbaseline_runs = 2\n\n[evaluation.held_out_states]",
)


async def test_the_baseline_probe_runs_a_second_time(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert world.evaluations.repeats == [(EvaluationKind.PROBE, 1)]


async def test_a_requested_probe_after_the_baseline_runs_once(tmp_path: Path) -> None:
    world = loop_world(tmp_path, toml=BASELINE_TOML)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    request_evaluation(world.paths, EvaluationKind.PROBE)
    await run_until(world, world.loop(), phases=2)
    assert world.evaluations.repeats == [(EvaluationKind.PROBE, 1)]


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
