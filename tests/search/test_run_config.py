from pathlib import Path

import pytest

from lean_search.search import ExpanderKind, ExplorationConfig, HarvestConfig, PriorityKind, load_run_config
from lean_search.search.config import parse_run_config

CONFIG_DIRECTORY = Path(__file__).resolve().parents[2] / "experiments" / "configs"


@pytest.mark.parametrize("path", sorted(CONFIG_DIRECTORY.glob("*.toml")), ids=lambda path: path.stem)
def test_shipped_configs_load(path: Path) -> None:
    assert load_run_config(path).expander.kind in ExpanderKind


def test_grpo_search_config_limits_steps_by_heartbeats() -> None:
    config = load_run_config(CONFIG_DIRECTORY / "grpo" / "search" / "visible_student_v2.toml")
    assert (config.search.tactic_heartbeats, config.automation.heartbeats, config.search.tactic_timeout_seconds) == (
        50_000,
        200_000,
        60.0,
    )


def test_default_limits_are_heartbeats_with_a_wall_clock_emergency_stop() -> None:
    config = parse_run_config("")
    assert (config.search.tactic_heartbeats, config.automation.heartbeats, config.search.tactic_timeout_seconds) == (
        50_000,
        200_000,
        60.0,
    )


def test_baseline_config_sweeps_cheapest_tactics_first() -> None:
    config = load_run_config(CONFIG_DIRECTORY / "phase0_automation_baseline.toml")
    assert config.automation.tactics[:2] == ("decide", "omega")


def test_missing_sections_take_defaults() -> None:
    config = parse_run_config('[priority]\nkind = "a_star"\nvalue_weight = 2\n')
    assert (config.priority.kind, config.priority.value_weight, config.search.max_expansions) == (
        PriorityKind.A_STAR,
        2.0,
        256,
    )


def test_absent_optional_budget_is_none() -> None:
    assert parse_run_config("[search]\nmax_expansions = 8\n").search.max_generated_tokens is None


@pytest.mark.parametrize(
    "text",
    [
        "[search]\nmax_expansion = 8\n",
        "[unknown]\nvalue = 1\n",
        '[search]\nmax_expansions = "many"\n',
        '[priority]\nkind = "random"\n',
        "[automation]\ntactics = [1, 2]\n",
        "[lean]\npool_size = 4\nconcurrency = 8\n",
        "[search]\nmax_expansions = 0\n",
        "[search.exploration]\nepsilon = 1.5\n",
        "[search.exploration]\ntop_k = 0\n",
        "[search.harvest]\nmax_expansions = -1\n",
    ],
)
def test_invalid_config_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(text)


def test_grpo_search_config_harvests_and_explores() -> None:
    search = load_run_config(CONFIG_DIRECTORY / "grpo" / "search" / "visible_student_v2.toml").search
    assert (search.harvest, search.exploration) == (
        HarvestConfig(enabled=True, max_remaining_steps=2.0, max_expansions=16),
        ExplorationConfig(enabled=True, epsilon=0.1, top_k=8, seed=0),
    )


def test_harvesting_and_exploration_are_off_by_default() -> None:
    search = parse_run_config("").search
    assert (search.harvest.enabled, search.exploration.enabled) == (False, False)
