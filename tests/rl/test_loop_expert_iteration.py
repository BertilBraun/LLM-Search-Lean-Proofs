"""Expert iteration inside the loop (the follow-up's arms C and D) with the loop's fakes: the rounds' schedule, their
data builds, the skip rule, one version per phase, restarts in the build, the training and between the two updates,
seeds and records; and a GRPO-only loop recording exactly what it recorded before rounds joined the loop (its phase
records, metric lines, versions and the phase configs it sent the trainer: tests/rl/golden/grpo_only_loop.json,
captured on master 40c266d). The window reaching before phase 1 is the builder's `phase_window`
(test_expert_iteration_data.py)."""

import dataclasses
import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from loop_fakes import PHASE_TEMPLATE, FakeExpertIterationBuilder, LoopWorld, run_until
from test_loop_budget import (
    PHASE_TREES,
    REPOSITORY,
    TOKEN_TOML,
    CheckedWorld,
    in_stage,
    phase_trees,
    run_while,
    token_world,
)

from lean_search.expert_iteration.serving import ModelVersion, read_versions
from lean_search.rl.expert_iteration_data import ExpertIterationConfig, parse_expert_iteration_config
from lean_search.rl.expert_iteration_rounds import round_config
from lean_search.rl.loop import ExpertIterationSetup, PhaseStage, phase_config_text
from lean_search.rl.loop_config import parse_loop_config

GOLDEN = Path(__file__).resolve().parent / "golden" / "grpo_only_loop.json"
# Wall-clock, machine and per-query readings: they differ run to run.
VOLATILE = ("finished_at", "cpu_counters", "gpus_at_start", "gpus_at_end", "time")
GOLDEN_FAMILIES = ("grpo", "value_training", "budget", "health", "timing")
GOLDEN_TOML = TOKEN_TOML.replace("value_every_phases = 1\n", "value_every_phases = 2\n")


def stable(value: object, root: str) -> object:
    match value:
        case dict():
            return {
                key: stable(item, root)
                for key, item in value.items()
                if key not in VOLATILE and not key.endswith("_seconds")
            }
        case list():
            return [stable(item, root) for item in value]
        case str():
            return value.replace(root, "<root>")
        case _:
            return value


def loop_records(world: LoopWorld, root: Path) -> object:
    """What the loop recorded and sent the trainer, without wall-clock, machine and temporary-path detail."""
    phases = [json.loads(line) for line in world.paths.phases.read_text(encoding="utf-8").splitlines()]
    metrics = {
        family: [
            json.loads(line)["fields"]
            for line in (world.paths.directory / "metrics" / f"{family}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for family in GOLDEN_FAMILIES
    }
    requests = [
        {
            "phase": request.phase,
            "config": request.config_text,
            "value_trees": [str(path) for path in request.value_trees],
        }
        for request in world.trainer.requests
    ]
    versions = world.paths.models.versions.read_text(encoding="utf-8").splitlines()
    records = {
        "phases": phases,
        "metrics": metrics,
        "requests": requests,
        "versions": [
            {key: value for key, value in json.loads(line).items() if key != "published_at"} for line in versions
        ],
    }
    return stable(records, str(root))


async def test_a_grpo_only_loop_records_what_it_recorded_before_expert_iteration(tmp_path: Path) -> None:
    world = token_world(tmp_path, GOLDEN_TOML)
    await run_until(world, world.loop(), phases=3)
    assert loop_records(world, tmp_path) == json.loads(GOLDEN.read_text(encoding="utf-8"))


# Expert-iteration rounds in the loop, with the fakes: arm C (a round at every pause, no GRPO update) and arm D (GRPO
# every phase, a round every second phase here), phases on the token budget of test_loop_budget.py.
RECIPE_PATH = REPOSITORY / "experiments/configs/grpo/followup/expert_iteration.toml"
ROUND_SETTINGS = (
    'phase_generated_tokens = 250\npersistent = true\nexpert_iteration_config = "recipe.toml"\n'
    "expert_iteration_window_phases = 2\n"
)
ROUND_TOML = TOKEN_TOML.replace('policy_adapter = ""', 'policy_adapter = "start-adapter"').replace(
    "value_every_phases = 1\n", "value_every_phases = 2\n"
)
C_TOML = ROUND_TOML.replace("phase_generated_tokens = 250\n", ROUND_SETTINGS + 'policy_update = "expert_iteration"\n')
D_TOML = ROUND_TOML.replace(
    "phase_generated_tokens = 250\n",
    ROUND_SETTINGS + 'policy_update = "grpo_and_expert_iteration"\nexpert_iteration_every_phases = 2\n',
)


def recipe() -> ExpertIterationConfig:
    """The follow-up's recipe on the fakes' policy base."""
    shipped = parse_expert_iteration_config(RECIPE_PATH.read_text(encoding="utf-8"))
    return dataclasses.replace(shipped, sft=dataclasses.replace(shipped.sft, model="start-policy"))


@dataclass
class RoundWorld(CheckedWorld):
    builder: FakeExpertIterationBuilder = field(default_factory=FakeExpertIterationBuilder)


def round_world(root: Path, toml: str, builder: FakeExpertIterationBuilder | None = None) -> RoundWorld:
    world = token_world(root, toml)
    builder = builder or FakeExpertIterationBuilder()
    builder.events = world.searcher.events
    fields = {item.name: getattr(world, item.name) for item in dataclasses.fields(world)}
    return RoundWorld(**{**fields, "expert_iteration": ExpertIterationSetup(recipe(), builder)}, builder=builder)


def versions(world: LoopWorld) -> list[ModelVersion]:
    return read_versions(world.paths.models)


def round_phases(world: RoundWorld) -> list[int]:
    return [config.data.last_phase for config in world.builder.builds]


def requests_with_rounds(world: LoopWorld) -> list[int]:
    return [request.phase for request in world.trainer.requests if request.expert_iteration is not None]


def grpo_requests(world: LoopWorld) -> list[int]:
    return [request.phase for request in world.trainer.requests if "policy" in tomllib.loads(request.config_text)]


def round_lines(world: LoopWorld) -> list[dict]:
    path = world.paths.directory / "metrics" / "expert_iteration.jsonl"
    return [json.loads(line)["fields"] for line in path.read_text(encoding="utf-8").splitlines()]


async def ran(world: RoundWorld, phases: int) -> RoundWorld:
    await run_until(world, world.loop(), phases=phases)
    return world


async def test_arm_c_builds_a_round_at_every_pause(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    assert round_phases(world) == [1, 2, 3]


async def test_arm_c_trains_each_round(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    assert requests_with_rounds(world) == [1, 2, 3]


async def test_arm_c_sends_the_trainer_no_grpo_update(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    assert grpo_requests(world) == []


async def test_arm_c_publishes_each_rounds_adapter_as_its_phases_version(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    published = [(version.trigger, Path(version.policy_adapter).parent.name) for version in versions(world)[1:]]
    assert published == [(f"phase {phase}", "expert_iteration") for phase in (1, 2, 3)]


async def test_a_round_continues_the_published_policy(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    continued = [config.sft.initial_adapter for config in world.builder.builds]
    assert continued == [version.policy_adapter for version in versions(world)[:3]]


async def test_a_rounds_window_ends_at_its_phase(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 3)
    windows = [(config.data.last_phase, config.data.window_phases) for config in world.builder.builds]
    assert windows == [(1, 2), (2, 2), (3, 2)]


async def test_a_rounds_data_lies_in_its_phases_directory_of_the_run(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 1)
    assert Path(world.builder.builds[0].sft.data) == world.paths.directory / "expert_iteration" / "phase_0001"


async def test_arm_c_ends_its_phases_at_the_same_token_boundaries(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 4)
    assert phase_trees(world, 4) == PHASE_TREES


async def test_arm_d_builds_a_round_every_n_phases(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 4)
    assert round_phases(world) == [2, 4]


async def test_arm_d_trains_grpo_at_every_pause(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 4)
    assert grpo_requests(world) == [1, 2, 3, 4]


async def test_arm_d_sends_a_round_after_grpo_only_when_due(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 4)
    assert requests_with_rounds(world) == [2, 4]


async def test_arm_d_publishes_one_version_per_phase_its_last_updates(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 4)
    published = [(version.trigger, Path(version.policy_adapter).parent.name) for version in versions(world)[1:]]
    kinds = ["policy", "expert_iteration", "policy", "expert_iteration"]
    assert published == [(f"phase {phase}", kind) for phase, kind in zip((1, 2, 3, 4), kinds, strict=True)]


async def test_the_health_check_judges_the_version_holding_the_round(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 2)
    health = [json.loads(line) for line in world.paths.health.read_text(encoding="utf-8").splitlines()]
    round_version = next(version for version in versions(world) if version.trigger == "phase 2")
    assert (round_version.policy_adapter.endswith("expert_iteration/adapter"), health[-1]["policy_version"]) == (
        True,
        round_version.version,
    )


async def test_arm_ds_round_keeps_the_kl_reference_at_the_start(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 3)
    phase_3 = tomllib.loads(world.trainer.requests[2].config_text)
    assert (
        phase_3["policy"]["initial_adapter"].endswith("expert_iteration/adapter"),
        phase_3["policy"]["reference_adapter"],
    ) == (
        True,
        "start-adapter",
    )


def few_examples(phase: int) -> FakeExpertIterationBuilder:
    return FakeExpertIterationBuilder(examples={phase: 99})


async def test_a_round_with_too_few_examples_does_not_train(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML, few_examples(1)), 2)
    assert requests_with_rounds(world) == [2]


async def test_arm_c_publishes_its_policy_unchanged_after_a_round_too_small_to_train(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML, few_examples(1)), 1)
    first, second = versions(world)[:2]
    assert (second.trigger, second.policy_adapter) == ("phase 1", first.policy_adapter)


async def test_arm_d_publishes_the_grpo_update_alone_after_a_round_too_small_to_train(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML, few_examples(2)), 2)
    assert Path(versions(world)[2].policy_adapter).parent.name == "policy"


async def test_a_round_too_small_to_train_is_recorded_as_skipped_with_its_count(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML, few_examples(1)), 1)
    line = round_lines(world)[0]
    assert (line["skipped"], line["examples"], line["optimizer_steps"]) == (True, 99, 0)


async def test_every_round_writes_its_record(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, D_TOML), 4)
    assert [(line["last_phase"], line["skipped"]) for line in round_lines(world)] == [(2, False), (4, False)]


async def test_a_grpo_only_loop_writes_no_round_records(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    await run_until(world, world.loop(), phases=2)
    assert not (world.paths.directory / "metrics" / "expert_iteration.jsonl").exists()


async def test_arm_cs_value_phase_trains_the_value_model_beside_the_round(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML), 2)
    request = world.trainer.requests[1]
    assert (request.train_value, request.expert_iteration is not None) == (True, True)


async def test_arm_cs_value_phase_without_a_round_trains_the_value_model_alone(tmp_path: Path) -> None:
    world = await ran(round_world(tmp_path, C_TOML, few_examples(2)), 2)
    request = world.trainer.requests[1]
    version = versions(world)[2]
    assert (
        request.train_value,
        request.expert_iteration,
        version.policy_adapter == versions(world)[1].policy_adapter,
        Path(version.value_adapter).parent.name,
    ) == (True, None, True, "value")


async def test_a_restart_during_a_rounds_build_builds_it_again(tmp_path: Path) -> None:
    world = round_world(tmp_path, C_TOML, FakeExpertIterationBuilder(stopped_phases={2}))
    loop = world.loop()
    await run_while(loop, lambda: "build 2" not in world.searcher.events)
    world.searcher.open.set()
    await ran(world, 3)
    assert round_phases(world) == [1, 2, 2, 3]


async def test_a_restart_during_a_rounds_build_trains_each_phase_once(tmp_path: Path) -> None:
    world = round_world(tmp_path, C_TOML, FakeExpertIterationBuilder(stopped_phases={2}))
    loop = world.loop()
    await run_while(loop, lambda: "build 2" not in world.searcher.events)
    world.searcher.open.set()
    await ran(world, 3)
    triggers = [version.trigger for version in versions(world)]
    assert ([request.phase for request in world.trainer.requests], triggers) == (
        [1, 2, 3],
        ["initial", "phase 1", "phase 2", "phase 3"],
    )


async def restart_in_round_training(root: Path) -> RoundWorld:
    """Stopped while phase 2's round trains (its data built), restarted, run to 3 phases."""
    world = round_world(root, C_TOML)
    world.trainer.train_seconds = 0.05
    loop = world.loop()
    await run_while(
        loop,
        lambda: (
            not (
                in_stage(loop, 2, PhaseStage.TRAINING) and any(request.phase == 2 for request in world.trainer.requests)
            )
        ),
    )
    world.trainer.train_seconds = 0.0
    world.searcher.open.set()
    return await ran(world, 3)


async def test_a_restart_during_a_rounds_training_does_not_build_it_again(tmp_path: Path) -> None:
    world = await restart_in_round_training(tmp_path)
    assert round_phases(world) == [1, 2, 3]


async def test_a_restart_during_a_rounds_training_trains_it_again_from_the_published_policy(tmp_path: Path) -> None:
    world = await restart_in_round_training(tmp_path)
    rounds = [request.expert_iteration for request in world.trainer.requests if request.phase == 2]
    sent = [parse_expert_iteration_config(path.read_text(encoding="utf-8")) for path in rounds if path is not None]
    assert [config.sft.initial_adapter for config in sent] == [versions(world)[1].policy_adapter] * 2


async def test_a_restart_during_a_rounds_training_publishes_each_phase_once(tmp_path: Path) -> None:
    world = await restart_in_round_training(tmp_path)
    assert [version.trigger for version in versions(world)] == ["initial", "phase 1", "phase 2", "phase 3"]


async def restart_between_the_updates(root: Path) -> RoundWorld:
    """Arm D stopped after phase 2's GRPO update, before its round finished; restarted, run to 3 phases."""
    world = round_world(root, D_TOML)
    world.trainer.interrupted_phases = {2}
    await run_while(world.loop(), lambda: "interrupted 2" not in world.searcher.events)
    world.searcher.open.set()
    return await ran(world, 3)


async def test_a_restart_between_the_updates_publishes_the_phase_once_with_both(tmp_path: Path) -> None:
    world = await restart_between_the_updates(tmp_path)
    published = [version for version in versions(world) if version.trigger == "phase 2"]
    assert [Path(version.policy_adapter).parent.name for version in published] == ["expert_iteration"]


async def test_a_restart_between_the_updates_trains_the_phase_again_from_the_published_policy(tmp_path: Path) -> None:
    world = await restart_between_the_updates(tmp_path)
    starts = [
        tomllib.loads(request.config_text)["policy"]["initial_adapter"]
        for request in world.trainer.requests
        if request.phase == 2
    ]
    assert starts == [versions(world)[1].policy_adapter] * 2


VERSION_THREE = ModelVersion(3, "phase-3/adapter", "value", "2026-11-16T10:00:00+00:00", "phase 3")


def phase_four_round(seed_offset: int) -> ExpertIterationConfig:
    return round_config(recipe(), "loop", "loop_phase_0004", Path("round"), 4, 2, VERSION_THREE, seed_offset)


def round_seeds(config: ExpertIterationConfig) -> tuple[str, str, int]:
    return config.data.seed, config.replay.seed, config.sft.optimization.seed


def test_without_a_seed_offset_a_rounds_seeds_are_the_recipes_by_phase() -> None:
    expected = ("followup-expert-iteration/phase-4", "followup-expert-iteration/replay/phase-4", 4)
    assert round_seeds(phase_four_round(0)) == expected


@pytest.mark.parametrize("seed", [0, 1, 2], ids=["selection", "replay", "trainer"])
def test_a_seed_offset_moves_each_of_a_rounds_seeds(seed: int) -> None:
    assert round_seeds(phase_four_round(1))[seed] != round_seeds(phase_four_round(0))[seed]


def test_the_hand_run_rounds_seeds_stay_the_recipes() -> None:
    hand_run = parse_expert_iteration_config(
        (REPOSITORY / "experiments/configs/grpo/expert_iteration_1.toml").read_text(encoding="utf-8")
    )
    assert round_seeds(hand_run) == ("grpo-expert-iteration-1", "grpo-expert-iteration-1/replay", 0)


def test_arm_cs_phase_config_has_no_policy_section() -> None:
    text = phase_config_text(PHASE_TEMPLATE, "base", "sft", VERSION_THREE, 4, 0.0, None, grpo=False)
    assert "policy" not in tomllib.loads(text)


def test_a_round_config_names_the_recipes_learning_rate() -> None:
    assert phase_four_round(0).sft.optimization.learning_rate == recipe().sft.optimization.learning_rate


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("persistent = true\n", "", "persistent"),
        ('expert_iteration_config = "recipe.toml"\n', "", "expert_iteration_config"),
        ('policy_adapter = "start-adapter"', 'policy_adapter = ""', "policy_adapter"),
        ("expert_iteration_window_phases = 2\n", "expert_iteration_window_phases = 0\n", "_window_phases"),
    ],
    ids=["without the persistent trainer", "without a recipe", "without a starting adapter", "with a window of 0"],
)
def test_rounds_the_loop_cannot_run_are_refused(old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_loop_config(C_TOML.replace(old, new))


@pytest.mark.parametrize(
    "change",
    [
        lambda shipped: dataclasses.replace(shipped, data=dataclasses.replace(shipped.data, window_phases=4)),
        lambda shipped: dataclasses.replace(shipped, sft=dataclasses.replace(shipped.sft, model="another-base")),
        lambda shipped: dataclasses.replace(
            shipped,
            sft=dataclasses.replace(
                shipped.sft, optimization=dataclasses.replace(shipped.sft.optimization, packing=False)
            ),
        ),
    ],
    ids=["a window of its own", "another base", "another structure than GRPO's"],
)
def test_a_recipe_the_loop_would_overwrite_or_could_not_train_is_refused(
    tmp_path: Path, change: Callable[[ExpertIterationConfig], ExpertIterationConfig]
) -> None:
    world = round_world(tmp_path, D_TOML)
    assert world.expert_iteration is not None
    world.expert_iteration = ExpertIterationSetup(change(world.expert_iteration.recipe), world.builder)
    with pytest.raises(ValueError, match="recipe"):
        world.loop()
