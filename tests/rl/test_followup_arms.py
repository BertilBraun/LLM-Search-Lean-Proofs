import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.expert_iteration.toml_text import toml_text
from lean_search.rl.expert_iteration_data import ExpertIterationConfig, parse_expert_iteration_config
from lean_search.rl.expert_iteration_rounds import recipe_refusals
from lean_search.rl.loop_config import PolicyUpdate, parse_loop_config
from lean_search.rl.study_configs import (
    ARM_SETTINGS,
    SHARED_SAMPLING_SETTINGS,
    OverlayConfigs,
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
# Each GRPO arm's credit and the shipped phase config that carries it.
CREDIT_PHASES = {"A": "phase.toml", "B1": "phase_sequence_credit.toml", "B2": "phase_proof_success.toml"}
GRPO_ARMS = [path for path in ARMS if path.stem in CREDIT_PHASES]
# The arms whose policy trains in expert-iteration rounds, and what each leaves to step 2.
ROUND_ARMS = {
    "C": ["loop.training.expert_iteration_window_phases", "expert_iteration.sft.optimization.learning_rate"],
    "D": [
        "loop.training.expert_iteration_window_phases",
        "phase.policy.optimization.learning_rate",
        "expert_iteration.sft.optimization.learning_rate",
    ],
}
RECIPE = CONFIGS / "followup/expert_iteration.toml"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


BASE = toml(CONFIGS / "followup/base.toml")
PHASE = toml(CONFIGS / "phase.toml")
RECIPE_TABLE = toml(RECIPE)


def with_learning_rate(arm: dict, learning_rate: float) -> dict:
    return merged(arm, {"phase": {"policy": {"optimization": {"learning_rate": learning_rate}}}})


def arm_configs(arm: dict, base: dict = BASE) -> OverlayConfigs:
    return overlay_configs(
        OverlayKind.ARM, arm, base, PHASE, "/configs/phase.toml", RECIPE_TABLE, "/configs/expert_iteration.toml"
    )


def filled(arm: dict, learning_rate: float = 5e-5, window: int = 4) -> dict:
    """The arm with step 2's choices filled in: every learning rate and the rounds' window."""
    rounds = {"expert_iteration": {"sft": {"optimization": {"learning_rate": learning_rate}}}}
    window_setting = {"loop": {"training": {"expert_iteration_window_phases": window}}}
    with_rounds = merged(merged(arm, rounds), window_setting) if "expert_iteration" in arm else arm
    return with_learning_rate(with_rounds, learning_rate) if "policy" in arm.get("phase", {}) else with_rounds


def test_the_arms_are_a_b1_b2_c_and_d() -> None:
    assert [path.stem for path in ARMS] == sorted([*CREDIT_PHASES, *ROUND_ARMS])


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arm_changes_only_the_arms_settings(path: Path) -> None:
    assert set(leaf_keys(toml(path))) <= ARM_SETTINGS


def test_an_arm_may_change_its_credit_learning_rates_seed_offset_name_and_rounds() -> None:
    assert {
        "loop.name",
        "loop.seed_offset",
        "phase.policy.data.credit",
        "phase.policy.optimization.learning_rate",
        "loop.training.policy_update",
        "loop.training.expert_iteration_every_phases",
        "loop.training.expert_iteration_window_phases",
        "expert_iteration.sft.optimization.learning_rate",
    } == ARM_SETTINGS


def test_a_second_seeds_offset_is_a_top_level_loop_setting() -> None:
    assert "loop.seed_offset" in ARM_SETTINGS


@pytest.mark.parametrize("path", GRPO_ARMS, ids=lambda path: path.stem)
def test_an_arms_learning_rate_waits_for_step_2(path: Path) -> None:
    assert placeholders(toml(path)) == ["phase.policy.optimization.learning_rate"]


@pytest.mark.parametrize("name", ROUND_ARMS)
def test_a_round_arms_learning_rates_and_window_wait_for_step_2(name: str) -> None:
    assert sorted(placeholders(toml(CONFIGS / f"followup/arms/{name}.toml"))) == sorted(ROUND_ARMS[name])


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


@pytest.mark.parametrize("path", GRPO_ARMS, ids=lambda path: path.stem)
def test_an_arms_loop_config_is_the_base_but_for_its_name_and_phase_config(path: Path) -> None:
    configs = arm_configs(with_learning_rate(toml(path), 5e-5))
    expected = merged(BASE, {"name": toml(path)["loop"]["name"], "training": {"phase_config": "/configs/phase.toml"}})
    assert tomllib.loads(toml_text(configs.loop)) == expected


@pytest.mark.parametrize("path", GRPO_ARMS, ids=lambda path: path.stem)
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


@pytest.mark.parametrize("path", ARMS, ids=lambda path: path.stem)
def test_an_arms_loop_config_loads_with_16_phases_of_12m_tokens(path: Path) -> None:
    training = parse_loop_config(toml_text(arm_configs(filled(toml(path))).loop)).training
    assert (training.phase_generated_tokens, training.max_phases, training.last_phase()) == (12_000_000, 16, 16)


def test_the_shared_sampling_run_loads_as_a_sampling_only_run_without_a_phase_count() -> None:
    configs = overlay_configs(OverlayKind.SHARED_SAMPLING, toml(SHARED_SAMPLING), BASE, PHASE, "phase.toml")
    training = parse_loop_config(toml_text(configs.loop)).training
    assert (training.sampling_only(), training.max_phases, training.last_phase()) == (True, 0, None)


def test_a_shared_sampling_run_whose_phase_comes_due_is_refused() -> None:
    overlay = merged(toml(SHARED_SAMPLING), {"loop": {"training": {"phase_generated_tokens": 12_000_000}}})
    with pytest.raises(ValueError, match="would train"):
        overlay_configs(OverlayKind.SHARED_SAMPLING, overlay, BASE, PHASE, "phase.toml")


def test_a_shared_sampling_run_cannot_change_the_policy_update() -> None:
    overlay = merged(toml(SHARED_SAMPLING), {"phase": {"policy": {"data": {"credit": "sequence"}}}})
    with pytest.raises(ValueError, match="changes only"):
        overlay_configs(OverlayKind.SHARED_SAMPLING, overlay, BASE, PHASE, "phase.toml")


def round_arm(name: str, learning_rate: float = 5e-5, window: int = 4) -> OverlayConfigs:
    return arm_configs(filled(toml(CONFIGS / f"followup/arms/{name}.toml"), learning_rate, window))


@pytest.mark.parametrize(
    ("name", "update", "every"),
    [("C", PolicyUpdate.EXPERT_ITERATION, 1), ("D", PolicyUpdate.GRPO_AND_EXPERT_ITERATION, 4)],
)
def test_a_round_arms_loop_config_is_the_base_but_for_its_name_rounds_and_configs(
    name: str, update: PolicyUpdate, every: int
) -> None:
    rounds = {
        "phase_config": "/configs/phase.toml",
        "policy_update": update.value,
        "expert_iteration_every_phases": every,
        "expert_iteration_window_phases": 4,
        "expert_iteration_config": "/configs/expert_iteration.toml",
    }
    expected = merged(BASE, {"name": f"followup_{name}", "training": rounds})
    assert tomllib.loads(toml_text(round_arm(name).loop)) == expected


def test_arm_cs_phase_config_is_the_shipped_phase() -> None:
    written = tomllib.loads(toml_text(round_arm("C").phase))
    assert from_json_object(TrainingPhaseConfig, written) == from_json_object(TrainingPhaseConfig, PHASE)


def test_arm_ds_phase_config_is_arm_as_at_the_same_rate() -> None:
    arm_a = arm_configs(filled(toml(CONFIGS / "followup/arms/A.toml"), 2e-5))
    arm_d = round_arm("D", 2e-5)
    assert tomllib.loads(toml_text(arm_d.phase)) == tomllib.loads(toml_text(arm_a.phase))


def test_arm_ds_loop_config_is_arm_as_plus_the_rounds() -> None:
    rounds = {
        "policy_update",
        "expert_iteration_every_phases",
        "expert_iteration_window_phases",
        "expert_iteration_config",
    }
    arm_a = arm_configs(filled(toml(CONFIGS / "followup/arms/A.toml"))).loop
    arm_d = round_arm("D").loop
    without_rounds = {key: value for key, value in arm_d["training"].items() if key not in rounds}
    assert ({**arm_d, "name": arm_a["name"], "training": without_rounds}) == arm_a


@pytest.mark.parametrize("name", ROUND_ARMS)
def test_a_round_arms_recipe_is_the_shipped_recipe_at_the_chosen_rate(name: str) -> None:
    written = parse_expert_iteration_config(toml_text(round_arm(name, 1e-4).expert_iteration or {}))
    shipped = parse_expert_iteration_config(RECIPE.read_text(encoding="utf-8"))
    optimization = dataclasses.replace(shipped.sft.optimization, learning_rate=1e-4)
    assert written == dataclasses.replace(shipped, sft=dataclasses.replace(shipped.sft, optimization=optimization))


def test_arms_c_and_d_share_one_recipe() -> None:
    assert round_arm("C").expert_iteration == round_arm("D").expert_iteration


@pytest.mark.parametrize("name", ROUND_ARMS)
def test_a_round_arms_recipe_is_one_the_loop_runs(name: str) -> None:
    configs = round_arm(name)
    config = parse_loop_config(toml_text(configs.loop))
    phase = from_json_object(TrainingPhaseConfig, tomllib.loads(toml_text(configs.phase)))
    recipe = parse_expert_iteration_config(toml_text(configs.expert_iteration or {}))
    assert recipe_refusals(config, phase, recipe) == []


def test_the_recipe_is_the_hand_run_rounds_but_for_its_seeds_and_what_the_loop_fills_in() -> None:
    shipped = parse_expert_iteration_config(RECIPE.read_text(encoding="utf-8"))
    hand_run = parse_expert_iteration_config((CONFIGS / "expert_iteration_1.toml").read_text(encoding="utf-8"))
    data = dataclasses.replace(hand_run.data, loop="", last_phase=0, seed=shipped.data.seed)
    replay = dataclasses.replace(hand_run.replay, seed=shipped.replay.seed)
    sft = dataclasses.replace(hand_run.sft, data="")
    expected: ExpertIterationConfig = dataclasses.replace(hand_run, run_name="", data=data, replay=replay, sft=sft)
    assert shipped == expected


@pytest.mark.parametrize(
    ("name", "contradiction"),
    [
        ("A", {"expert_iteration": {"sft": {"optimization": {"learning_rate": 1e-4}}}}),
        ("A", {"loop": {"training": {"expert_iteration_window_phases": 4}}}),
        ("A", {"loop": {"training": {"expert_iteration_every_phases": 4}}}),
        ("C", {"phase": {"policy": {"optimization": {"learning_rate": 5e-5}}}}),
        ("C", {"phase": {"policy": {"data": {"credit": "sequence"}}}}),
    ],
    ids=[
        "a recipe rate in a GRPO arm",
        "a round window in a GRPO arm",
        "a round period in a GRPO arm",
        "a GRPO rate in arm C",
        "a GRPO credit in arm C",
    ],
)
def test_an_arm_setting_what_its_policy_update_never_reads_is_refused(name: str, contradiction: dict) -> None:
    arm = merged(filled(toml(CONFIGS / f"followup/arms/{name}.toml")), contradiction)
    with pytest.raises(ValueError, match="never reads"):
        arm_configs(arm)


def test_arm_d_may_set_both_rates() -> None:
    assert round_arm("D").expert_iteration is not None


@pytest.mark.parametrize("path", GRPO_ARMS, ids=lambda path: path.stem)
def test_a_grpo_arm_gets_no_recipe(path: Path) -> None:
    assert arm_configs(filled(toml(path))).expert_iteration is None
