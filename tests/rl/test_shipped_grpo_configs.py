import tomllib
from pathlib import Path

import pytest

from lean_search.rl.fixed_sets import FixedSetsConfig
from lean_search.rl.loop_config import GrpoLoopConfig, StatementSourceKind, load_loop_config
from lean_search.rl.single_step import SingleStepConfig
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search import PriorityKind, RunConfig, load_run_config
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments" / "configs"
LOOPS = ["grpo/loop.toml", "grpo/loop_overfit.toml"]


def loop(name: str) -> GrpoLoopConfig:
    return load_loop_config(CONFIGS / name)


@pytest.mark.parametrize("name", LOOPS)
def test_loop_search_template_loads(name: str) -> None:
    assert isinstance(load_run_config(CONFIGS.parent.parent / loop(name).sampling.search_config), RunConfig)


@pytest.mark.parametrize("name", LOOPS)
def test_loop_phase_template_loads(name: str) -> None:
    text = (CONFIGS.parent.parent / loop(name).training.phase_config).read_text(encoding="utf-8")
    assert from_json_object(TrainingPhaseConfig, tomllib.loads(text)).policy is not None


@pytest.mark.parametrize("name", LOOPS)
def test_loop_serves_on_every_gpu(name: str) -> None:
    assert {server.gpu for server in loop(name).serving.policy_servers} == {0, 1, 2, 3}


@pytest.mark.parametrize("name", LOOPS)
def test_loop_trains_on_every_gpu(name: str) -> None:
    assert loop(name).training.gpus == (0, 1, 2, 3)


@pytest.mark.parametrize("name", LOOPS)
def test_every_server_sleeps_while_the_loop_trains(name: str) -> None:
    config = loop(name)
    assert config.released_servers() == config.serving.servers


def test_overfit_loop_searches_a_fixed_list() -> None:
    assert loop("grpo/loop_overfit.toml").statements.kind == StatementSourceKind.FIXED


def test_overfit_loop_trains_only_the_policy() -> None:
    assert loop("grpo/loop_overfit.toml").training.value_every_phases == 0


def test_loop_renaming_is_off_by_default() -> None:
    assert not loop("grpo/loop.toml").renaming.enabled


def test_gate_search_has_no_value_model() -> None:
    config = load_run_config(CONFIGS / "grpo/gate_search.toml")
    assert (config.value.model, config.priority.kind) == ("", PriorityKind.CUMULATIVE_LOG_PROBABILITY)


def test_fixed_sets_config_loads() -> None:
    text = (CONFIGS / "grpo/fixed_sets.toml").read_text(encoding="utf-8")
    assert from_json_object(FixedSetsConfig, tomllib.loads(text)).probe_per_stratum * 3 >= 500


def test_single_step_arms_load_their_phase_configs() -> None:
    text = (CONFIGS / "grpo/single_step.toml").read_text(encoding="utf-8")
    config = from_json_object(SingleStepConfig, tomllib.loads(text))
    credits = [
        tomllib.loads((CONFIGS.parent.parent / arm.phase_config).read_text(encoding="utf-8"))["policy"]["data"][
            "credit"
        ]
        for arm in config.arms
    ]
    assert credits == ["per_tactic", "sequence"]


@pytest.mark.parametrize("name", LOOPS)
def test_loop_continues_the_starting_policys_own_adapter(name: str) -> None:
    assert loop(name).initial.policy_adapter.endswith("/adapter")


@pytest.mark.parametrize("name", LOOPS)
def test_loop_replays_the_flattened_sft_data(name: str) -> None:
    training = loop(name).training
    assert (training.lean_replay, training.math_replay) == (
        "reasoning/visible_student_v3_numbered/train.jsonl",
        "reasoning/visible_student_v3_numbered/math.jsonl",
    )


@pytest.mark.parametrize("phase", ["grpo/phase.toml", "grpo/phase_sequence_credit.toml"])
def test_phase_config_starts_where_the_loop_starts(phase: str) -> None:
    policy = tomllib.loads((CONFIGS / phase).read_text(encoding="utf-8"))["policy"]
    starting = loop("grpo/loop.toml")
    expected = (starting.serving.policy_base_model, starting.initial.policy_adapter, starting.initial.policy_adapter)
    assert (policy["model"], policy["initial_adapter"], policy["reference_adapter"]) == expected


def test_single_step_starts_where_the_loop_starts() -> None:
    text = (CONFIGS / "grpo/single_step.toml").read_text(encoding="utf-8")
    config = from_json_object(SingleStepConfig, tomllib.loads(text))
    starting = loop("grpo/loop.toml")
    expected = (starting.serving.policy_base_model, starting.initial.policy_adapter)
    assert (config.policy_base_model, config.policy_adapter) == expected
