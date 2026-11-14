import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.loop_config import parse_loop_config
from lean_search.rl.study_configs import ARM_SETTINGS, arm_configs, leaf_keys, merged, placeholders
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments/configs/grpo"
ARMS = sorted((CONFIGS / "followup/arms").glob("*.toml"))
# Each arm's credit and the shipped phase config that carries it.
CREDIT_PHASES = {"A": "phase.toml", "B1": "phase_sequence_credit.toml", "B2": "phase_proof_success.toml"}


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


BASE = toml(CONFIGS / "followup/base.toml")
PHASE = toml(CONFIGS / "phase.toml")


def with_learning_rate(arm: dict, learning_rate: float) -> dict:
    return merged(arm, {"phase": {"policy": {"optimization": {"learning_rate": learning_rate}}}})


def test_the_arms_are_a_b1_and_b2() -> None:
    assert [path.stem for path in ARMS] == sorted(CREDIT_PHASES)


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arm_changes_only_its_credit_learning_rate_seed_offset_and_name(path: Path) -> None:
    assert set(leaf_keys(toml(path))) <= ARM_SETTINGS


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_learning_rate_waits_for_step_2(path: Path) -> None:
    assert placeholders(toml(path)) == ["phase.policy.optimization.learning_rate"]


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arm_with_a_placeholder_is_refused(path: Path) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        arm_configs(toml(path), BASE, PHASE, "phase.toml")


def test_an_arm_changing_anything_else_is_refused() -> None:
    arm = merged(with_learning_rate(toml(ARMS[0]), 5e-5), {"loop": {"sampling": {"concurrency": 30}}})
    with pytest.raises(ValueError, match="sampling.concurrency"):
        arm_configs(arm, BASE, PHASE, "phase.toml")


def test_every_arm_has_its_own_run_name() -> None:
    names = [toml(path)["loop"]["name"] for path in ARMS]
    assert len(set(names)) == len(names) and BASE["name"] not in names


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_loop_config_is_the_base_but_for_its_name_and_phase_config(path: Path) -> None:
    configs = arm_configs(with_learning_rate(toml(path), 5e-5), BASE, PHASE, "/configs/phase.toml")
    base = parse_loop_config(toml_text(BASE))
    training = dataclasses.replace(base.training, phase_config="/configs/phase.toml")
    expected = dataclasses.replace(base, name=toml(path)["loop"]["name"], training=training)
    assert parse_loop_config(toml_text(configs.loop)) == expected


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_phase_config_is_its_credits_shipped_phase_at_the_chosen_rate(path: Path) -> None:
    configs = arm_configs(with_learning_rate(toml(path), 5e-5), BASE, PHASE, "phase.toml")
    shipped = with_learning_rate({"phase": toml(CONFIGS / CREDIT_PHASES[path.stem])}, 5e-5)["phase"]
    written = tomllib.loads(toml_text(configs.phase))
    assert from_json_object(TrainingPhaseConfig, written) == from_json_object(TrainingPhaseConfig, shipped)


def test_the_arms_phase_template_is_the_base_loops() -> None:
    assert BASE["training"]["phase_config"] == "experiments/configs/grpo/phase.toml"
