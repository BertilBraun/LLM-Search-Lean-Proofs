"""The offline arm's shipped configs against the files they derive from, and experiments/offline_arm.py's
held-out-config and probe-list commands."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.rl.loop_config import load_loop_config  # noqa: E402
from lean_search.rl.offline_arm import load_offline_arm_config  # noqa: E402
from lean_search.rl.probe_run_list import PlannedRun  # noqa: E402
from lean_search.rl.study_configs import resolved_toml  # noqa: E402
from lean_search.search import load_run_config  # noqa: E402
from lean_search.search.records import from_json_object  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"
OFFLINE = FOLLOWUP / "offline"
CONFIG = OFFLINE / "offline_arm.toml"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def without(table: dict, section: str, *keys: str) -> dict:
    return {**table, section: {key: value for key, value in table[section].items() if key not in keys}}


def test_the_probe_search_is_run_4s_but_for_budget_and_depth_weight() -> None:
    run_4 = without(
        without(
            toml(FOLLOWUP / "step1/token_capped_no_reasoning.toml"), "search", "max_expansions", "max_generated_tokens"
        ),
        "priority",
        "depth_weight",
    )
    offline = without(
        without(toml(OFFLINE / "search_no_reasoning_16.toml"), "search", "max_expansions"), "priority", "depth_weight"
    )
    assert offline == run_4


def test_the_probe_search_has_16_expansions_depth_weight_0_1_and_no_token_cap() -> None:
    config = load_run_config(OFFLINE / "search_no_reasoning_16.toml")
    found = (config.search.max_expansions, config.priority.depth_weight, config.search.max_generated_tokens)
    assert found == (16, 0.1, None)


def test_the_probe_search_samples_without_reasoning() -> None:
    assert load_run_config(OFFLINE / "search_no_reasoning_16.toml").policy.visible_reasoning is False


def test_the_probe_evaluation_is_the_studys_but_for_cap_and_order() -> None:
    study = resolved_toml(FOLLOWUP / "probe_evaluation.toml", REPOSITORY)
    offline = resolved_toml(OFFLINE / "probe_evaluation.toml", REPOSITORY)
    changed = {
        **study,
        "submission_order": "longest_expected_search_first",
        "expected_search_seconds": "experiments/configs/grpo/followup/probe_v2_expected_search_seconds.tsv",
        "probe": {**study["probe"], "max_wall_seconds": 14400.0},
    }
    assert offline == changed


def test_the_fine_tuning_is_the_expert_iteration_recipes() -> None:
    assert toml(CONFIG)["sft"] == toml(FOLLOWUP / "expert_iteration.toml")["sft"]


def test_the_replay_is_the_expert_iteration_recipes_but_for_seed_and_repetition() -> None:
    recipe = toml(FOLLOWUP / "expert_iteration.toml")["replay"]
    assert {**toml(CONFIG)["replay"], "seed": recipe["seed"], "repeat": False} == {**recipe, "repeat": False}


def test_the_held_out_sets_are_the_arms() -> None:
    assert (
        list(load_offline_arm_config(CONFIG).data.held_out_sets)
        == toml(FOLLOWUP / "base.toml")["statements"]["held_out"]
    )


def test_the_pool_is_the_arms_frozen_pool() -> None:
    curriculum = toml(FOLLOWUP / "base.toml")["statements"]["curriculum"]
    data = load_offline_arm_config(CONFIG).data
    assert (data.pool, data.pool_sha256) == (curriculum["verified"], curriculum["verified_sha256"])


def test_the_walk_uses_the_no_reasoning_modes_search() -> None:
    mode = toml(FOLLOWUP / "modes/no_reasoning.toml")["sampling"]["search_config"]
    assert load_offline_arm_config(CONFIG).walk.search_config == mode


def test_the_starting_adapter_is_v0() -> None:
    assert (
        load_offline_arm_config(CONFIG).initial_policy_adapter
        == toml(FOLLOWUP / "base.toml")["initial"]["policy_adapter"]
    )


def offline_arm(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {
        "LEAN_SEARCH_DATA": str(tmp_path / "data"),
        "LEAN_SEARCH_RUNS": str(tmp_path / "runs"),
        "LEAN_SEARCH_CHECKPOINTS": str(tmp_path / "checkpoints"),
    }
    command = [sys.executable, "experiments/offline_arm.py", "--config", str(CONFIG), *arguments]
    return subprocess.run(command, cwd=REPOSITORY, env=environment, capture_output=True, text=True, check=True)  # noqa: S603


def test_the_held_out_loop_config_samples_with_the_no_reasoning_search(tmp_path: Path) -> None:
    offline_arm(tmp_path, "held-out-config", "--output", str(tmp_path / "loop.toml"))
    mode = toml(FOLLOWUP / "modes/no_reasoning.toml")["sampling"]["search_config"]
    assert load_loop_config(tmp_path / "loop.toml").sampling.search_config == mode


def test_the_held_out_loop_config_keeps_the_bases_held_out_states(tmp_path: Path) -> None:
    offline_arm(tmp_path, "held-out-config", "--output", str(tmp_path / "loop.toml"))
    base = load_loop_config(FOLLOWUP / "base.toml")
    assert load_loop_config(tmp_path / "loop.toml").evaluation == base.evaluation


def test_the_probe_list_runs_the_chosen_rates_adapter(tmp_path: Path) -> None:
    rank = tmp_path / "rank.txt"
    rank.write_text("Chosen: matched_1e-4 (the held-out states decide; tied on the held-out states: matched_1e-4)\n")
    offline_arm(
        tmp_path, "probe-list", "--subset", "matched", "--rank", str(rank), "--output", str(tmp_path / "runs.toml")
    )
    run = from_json_object(PlannedRun, toml(tmp_path / "runs.toml")["runs"][0])
    assert run.policy_adapter == str(tmp_path / "checkpoints/offline_arm_matched_1e-4/adapter")


def test_the_probe_list_searches_with_the_offline_configs_and_value_v0(tmp_path: Path) -> None:
    rank = tmp_path / "rank.txt"
    rank.write_text("Chosen: pool_5e-5 (the held-out states decide; tied on the held-out states: pool_5e-5)\n")
    offline_arm(
        tmp_path, "probe-list", "--subset", "pool", "--rank", str(rank), "--output", str(tmp_path / "runs.toml")
    )
    run = from_json_object(PlannedRun, toml(tmp_path / "runs.toml")["runs"][0])
    found = (run.name, run.value, run.config, run.search_config)
    expected = (
        "offline_arm_pool",
        "v0",
        "experiments/configs/grpo/followup/offline/probe_evaluation.toml",
        "experiments/configs/grpo/followup/offline/search_no_reasoning_16.toml",
    )
    assert found == expected


def test_the_probe_list_refuses_a_choice_of_another_subset(tmp_path: Path) -> None:
    rank = tmp_path / "rank.txt"
    rank.write_text("Chosen: pool_5e-5 (the held-out states decide; tied on the held-out states: pool_5e-5)\n")
    with pytest.raises(subprocess.CalledProcessError):
        offline_arm(
            tmp_path, "probe-list", "--subset", "matched", "--rank", str(rank), "--output", str(tmp_path / "r.toml")
        )
