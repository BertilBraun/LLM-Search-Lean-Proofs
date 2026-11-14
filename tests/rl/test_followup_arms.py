import tomllib
from pathlib import Path

import pytest

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.study_configs import (
    ARM_SETTINGS,
    SHARED_SAMPLING_SETTINGS,
    OverlayKind,
    leaf_keys,
    merged,
    overlay_configs,
    placeholders,
)
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments/configs/grpo"
ARMS = sorted((CONFIGS / "followup/arms").glob("*.toml"))
SHARED_SAMPLING = CONFIGS / "followup/shared_sampling.toml"
# Each arm's credit and the shipped phase config that carries it.
CREDIT_PHASES = {"A": "phase.toml", "B1": "phase_sequence_credit.toml", "B2": "phase_proof_success.toml"}


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


SHIPPED_BASE = toml(CONFIGS / "followup/base.toml")
# The base as WP1 sets it: B per phase and 16 phases, identical for every arm.
BASE = merged(SHIPPED_BASE, {"training": {"phase_generated_tokens": 12_000_000, "max_phases": 16}})
PHASE = toml(CONFIGS / "phase.toml")


def with_learning_rate(arm: dict, learning_rate: float) -> dict:
    return merged(arm, {"phase": {"policy": {"optimization": {"learning_rate": learning_rate}}}})


def arm_configs(arm: dict, base: dict = BASE) -> object:
    return overlay_configs(OverlayKind.ARM, arm, base, PHASE, "/configs/phase.toml")


def test_the_arms_are_a_b1_and_b2() -> None:
    assert [path.stem for path in ARMS] == sorted(CREDIT_PHASES)


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arm_changes_only_its_credit_learning_rate_seed_offset_and_name(path: Path) -> None:
    assert set(leaf_keys(toml(path))) <= ARM_SETTINGS


def test_a_second_seeds_offset_is_a_top_level_loop_setting() -> None:
    assert "loop.seed_offset" in ARM_SETTINGS


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_learning_rate_waits_for_step_2(path: Path) -> None:
    assert placeholders(toml(path)) == ["phase.policy.optimization.learning_rate"]


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arm_with_a_placeholder_is_refused(path: Path) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        arm_configs(toml(path))


@pytest.mark.parametrize(
    "change",
    [
        {"sampling": {"concurrency": 30}},
        {"training": {"phase_generated_tokens": 6_000_000}},
        {"training": {"max_phases": 8}},
    ],
    ids=["concurrency", "token budget", "phase count"],
)
def test_an_arm_changing_anything_else_is_refused(change: dict) -> None:
    arm = merged(with_learning_rate(toml(ARMS[0]), 5e-5), {"loop": change})
    with pytest.raises(ValueError, match="changes only"):
        arm_configs(arm)


@pytest.mark.parametrize(
    ("missing", "message"),
    [("phase_generated_tokens", "end on minutes"), ("max_phases", "never stop")],
)
def test_an_arm_over_a_base_without_a_token_budget_is_refused(missing: str, message: str) -> None:
    training = {key: value for key, value in BASE["training"].items() if key != missing}
    with pytest.raises(ValueError, match=message):
        arm_configs(with_learning_rate(toml(ARMS[0]), 5e-5), {**BASE, "training": training})


def test_every_arm_has_its_own_run_name() -> None:
    names = [toml(path)["loop"]["name"] for path in ARMS]
    assert len(set(names)) == len(names) and BASE["name"] not in names


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_loop_config_is_the_base_but_for_its_name_and_phase_config(path: Path) -> None:
    configs = arm_configs(with_learning_rate(toml(path), 5e-5))
    expected = merged(BASE, {"name": toml(path)["loop"]["name"], "training": {"phase_config": "/configs/phase.toml"}})
    assert tomllib.loads(toml_text(configs.loop)) == expected


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_phase_config_is_its_credits_shipped_phase_at_the_chosen_rate(path: Path) -> None:
    configs = arm_configs(with_learning_rate(toml(path), 5e-5))
    shipped = with_learning_rate({"phase": toml(CONFIGS / CREDIT_PHASES[path.stem])}, 5e-5)["phase"]
    written = tomllib.loads(toml_text(configs.phase))
    assert from_json_object(TrainingPhaseConfig, written) == from_json_object(TrainingPhaseConfig, shipped)


def test_the_arms_phase_template_is_the_base_loops() -> None:
    assert BASE["training"]["phase_config"] == "experiments/configs/grpo/phase.toml"


def test_the_shared_sampling_run_changes_only_its_name_and_token_budgets() -> None:
    assert set(leaf_keys(toml(SHARED_SAMPLING))) <= SHARED_SAMPLING_SETTINGS


def test_the_shared_sampling_run_samples_48m_tokens_without_a_phase_coming_due() -> None:
    configs = overlay_configs(OverlayKind.SHARED_SAMPLING, toml(SHARED_SAMPLING), BASE, PHASE, "phase.toml")
    training = configs.loop["training"]
    assert (training["max_generated_tokens"], training["phase_generated_tokens"] > 48_000_000) == (48_000_000, True)


def test_a_shared_sampling_run_whose_phase_comes_due_is_refused() -> None:
    overlay = merged(toml(SHARED_SAMPLING), {"loop": {"training": {"phase_generated_tokens": 12_000_000}}})
    with pytest.raises(ValueError, match="would train"):
        overlay_configs(OverlayKind.SHARED_SAMPLING, overlay, BASE, PHASE, "phase.toml")


def test_a_shared_sampling_run_cannot_change_the_policy_update() -> None:
    overlay = merged(toml(SHARED_SAMPLING), {"phase": {"policy": {"data": {"credit": "sequence"}}}})
    with pytest.raises(ValueError, match="changes only"):
        overlay_configs(OverlayKind.SHARED_SAMPLING, overlay, BASE, PHASE, "phase.toml")
