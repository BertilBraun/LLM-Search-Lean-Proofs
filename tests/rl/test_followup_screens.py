import tomllib
from pathlib import Path
from typing import NamedTuple

import pytest

from lean_search.rl.study_configs import OverlayConfigs, OverlayKind, merged, overlay_configs
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments/configs/grpo"
SCREENS = CONFIGS / "followup/screens"
BASE = tomllib.loads((CONFIGS / "followup/base.toml").read_text(encoding="utf-8"))
PHASE = tomllib.loads((CONFIGS / "phase.toml").read_text(encoding="utf-8"))
RECIPE = tomllib.loads((CONFIGS / "followup/expert_iteration.toml").read_text(encoding="utf-8"))
SCREEN_PHASES = 8


class Screen(NamedTuple):
    arm: str
    learning_rate: float
    # The shipped phase config carrying the arm's credit.
    credit_phase: str


SCREENED = {"A_2e-5": Screen("A", 2e-5, "phase.toml"), "B2_2e-5": Screen("B2", 2e-5, "phase_proof_success.toml")}


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def screen_configs(screen: dict, kind: OverlayKind = OverlayKind.SMOKE) -> OverlayConfigs:
    return overlay_configs(kind, screen, BASE, PHASE, "/configs/phase.toml", RECIPE, "/configs/expert_iteration.toml")


def with_learning_rate(phase: dict, learning_rate: float) -> dict:
    return merged(phase, {"policy": {"optimization": {"learning_rate": learning_rate}}})


def expected_screen(stem: str) -> dict:
    screen = SCREENED[stem]
    changes = {
        "loop": {
            "name": f"followup_screen_{stem}",
            "training": {
                "phase_generated_tokens": BASE["training"]["phase_generated_tokens"],
                "max_phases": SCREEN_PHASES,
                "value_every_phases": BASE["training"]["value_every_phases"],
            },
        },
        "phase": with_learning_rate({}, screen.learning_rate),
    }
    return merged(toml(CONFIGS / f"followup/arms/{screen.arm}.toml"), changes)


def test_the_screens_directory_holds_exactly_the_two_screens() -> None:
    assert sorted(path.stem for path in SCREENS.glob("*.toml")) == sorted(SCREENED)


@pytest.mark.parametrize("stem", SCREENED)
def test_a_screen_is_its_arm_at_its_rate_for_8_phases_under_its_own_name(stem: str) -> None:
    assert toml(SCREENS / f"{stem}.toml") == expected_screen(stem)


@pytest.mark.parametrize("stem", SCREENED)
def test_a_screens_loop_config_is_the_base_but_for_its_name_and_8_phases(stem: str) -> None:
    loop = screen_configs(toml(SCREENS / f"{stem}.toml")).loop
    changes = {
        "name": f"followup_screen_{stem}",
        "training": {"max_phases": SCREEN_PHASES, "phase_config": "/configs/phase.toml"},
    }
    assert loop == merged(BASE, changes)


def test_the_a_screens_phase_config_is_arm_as_at_2e_5() -> None:
    written = screen_configs(toml(SCREENS / "A_2e-5.toml")).phase
    arm_a = toml(CONFIGS / "followup/arms/A.toml")["phase"]
    expected = merged(PHASE, with_learning_rate(arm_a, 2e-5))
    assert from_json_object(TrainingPhaseConfig, written) == from_json_object(TrainingPhaseConfig, expected)


def test_the_b2_screens_phase_config_is_the_shipped_proof_success_phase_at_2e_5() -> None:
    written = screen_configs(toml(SCREENS / "B2_2e-5.toml")).phase
    expected = with_learning_rate(toml(CONFIGS / SCREENED["B2_2e-5"].credit_phase), 2e-5)
    assert from_json_object(TrainingPhaseConfig, written) == from_json_object(TrainingPhaseConfig, expected)


@pytest.mark.parametrize("stem", SCREENED)
def test_a_screen_is_refused_as_an_arm(stem: str) -> None:
    with pytest.raises(ValueError, match="overlay changes only"):
        screen_configs(toml(SCREENS / f"{stem}.toml"), OverlayKind.ARM)
