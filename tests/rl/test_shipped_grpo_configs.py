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
def test_loop_trains_on_a_gpu_without_policy_servers(name: str) -> None:
    config = loop(name)
    assert all(server.gpu != config.training.gpu for server in config.serving.servers)


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
