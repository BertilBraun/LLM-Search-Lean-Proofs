import tomllib
from pathlib import Path

import pytest

from lean_search.rl.fixed_sets import FixedSetsConfig
from lean_search.rl.loop_config import (
    EvaluationValueModel,
    GrpoLoopConfig,
    HealthConfig,
    StatementSourceKind,
    load_loop_config,
)
from lean_search.rl.single_step import SingleStepConfig
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search import PriorityKind, RunConfig, load_run_config
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments" / "configs"
LOOPS = ["grpo/loop.toml", "grpo/loop_overfit.toml", "grpo/loop_smoke.toml"]


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


@pytest.mark.parametrize("name", ["grpo/loop.toml", "grpo/loop_smoke.toml"])
def test_loop_trains_with_the_persistent_trainer(name: str) -> None:
    assert loop(name).training.persistent


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
    assert credits == ["per_tactic", "sequence", "per_tactic"]


def test_single_step_compares_the_learning_rates() -> None:
    text = (CONFIGS / "grpo/single_step.toml").read_text(encoding="utf-8")
    config = from_json_object(SingleStepConfig, tomllib.loads(text))
    assert [arm.learning_rate for arm in config.arms] == [None, None, 3e-5]


@pytest.mark.parametrize("name", LOOPS)
def test_loop_continues_the_starting_policys_own_adapter(name: str) -> None:
    assert loop(name).initial.policy_adapter.endswith("/adapter")


@pytest.mark.parametrize("name", ["grpo/loop.toml", "grpo/loop_overfit.toml"])
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


def test_sequence_credit_phase_differs_from_the_phase_only_in_its_credit() -> None:
    phase, sequence = (
        tomllib.loads((CONFIGS / name).read_text(encoding="utf-8"))
        for name in ("grpo/phase.toml", "grpo/phase_sequence_credit.toml")
    )
    sequence["policy"]["data"]["credit"] = phase["policy"]["data"]["credit"]
    assert sequence == phase


def test_progress_per_step_outweighs_the_wasted_tactic_cost() -> None:
    reward = from_json_object(
        TrainingPhaseConfig, tomllib.loads((CONFIGS / "grpo/phase.toml").read_text(encoding="utf-8"))
    ).reward
    assert reward.progress_per_step > reward.wasted_tactic_cost


def test_single_step_starts_where_the_loop_starts() -> None:
    text = (CONFIGS / "grpo/single_step.toml").read_text(encoding="utf-8")
    config = from_json_object(SingleStepConfig, tomllib.loads(text))
    starting = loop("grpo/loop.toml")
    expected = (starting.serving.policy_base_model, starting.initial.policy_adapter)
    assert (config.policy_base_model, config.policy_adapter) == expected


def test_loop_replays_the_v0_value_training_data() -> None:
    assert loop("grpo/loop.toml").training.value_replay == "value/v0/train.jsonl"


@pytest.mark.parametrize("name", LOOPS)
def test_loop_evaluations_search_with_the_starting_value_model(name: str) -> None:
    assert loop(name).evaluation.value_model == EvaluationValueModel.INITIAL


@pytest.mark.parametrize("name", LOOPS)
def test_loop_starts_with_mu_off(name: str) -> None:
    text = (CONFIGS.parent.parent / loop(name).training.phase_config).read_text(encoding="utf-8")
    assert from_json_object(TrainingPhaseConfig, tomllib.loads(text)).reward.value_share == 0.0


def test_the_smoke_loop_trains_on_the_real_phase() -> None:
    assert loop("grpo/loop_smoke.toml").training.phase_config == loop("grpo/loop.toml").training.phase_config


@pytest.mark.parametrize("name", ["grpo/loop.toml", "grpo/loop_smoke.toml"])
def test_loop_scores_the_value_benchmark(name: str) -> None:
    assert loop(name).evaluation.value_benchmark.path.endswith("benchmark.json.gz")


def test_the_loop_probes_a_third_every_two_hours() -> None:
    evaluation = loop("grpo/loop.toml").evaluation
    assert (evaluation.probe_parts, evaluation.probe.every_hours) == (3, 2.0)


def test_the_loop_runs_a_value_arm_every_other_probe_slot() -> None:
    assert loop("grpo/loop.toml").evaluation.value_arm.every_slots == 2


def test_the_overfit_loop_probes_the_whole_set_when_requested() -> None:
    assert loop("grpo/loop_overfit.toml").evaluation.probe_parts == 1


def test_the_smoke_loop_trains_the_value_model_every_phase() -> None:
    assert loop("grpo/loop_smoke.toml").training.value_every_phases == 1


def test_the_smoke_loop_runs_every_evaluation_before_its_first_phase() -> None:
    evaluation = loop("grpo/loop_smoke.toml").evaluation
    assert all(target.at_start for target in (evaluation.probe, evaluation.minif2f, evaluation.held_out_states))


@pytest.mark.parametrize("name", LOOPS)
def test_loop_searches_32_expansions(name: str) -> None:
    assert loop(name).sampling.max_expansions == 32


def test_the_shared_search_template_keeps_its_64_expansions() -> None:
    config = load_run_config(CONFIGS.parent.parent / loop("grpo/loop.toml").sampling.search_config)
    assert config.search.max_expansions == 64


def test_loop_phases_end_on_300_trainable_groups_within_45_to_90_minutes() -> None:
    training = loop("grpo/loop.toml").training
    assert (training.min_sampling_minutes, training.max_sampling_minutes, training.min_trainable_groups) == (
        45.0,
        90.0,
        300,
    )


@pytest.mark.parametrize("name", ["grpo/loop_overfit.toml", "grpo/loop_smoke.toml"])
def test_short_loops_need_fewer_trainable_groups(name: str) -> None:
    assert loop(name).training.min_trainable_groups < loop("grpo/loop.toml").training.min_trainable_groups


def test_the_loop_spells_out_the_default_health_thresholds() -> None:
    assert loop("grpo/loop.toml").health == HealthConfig()


def test_the_loop_stops_below_70_percent_of_version_zeros_valid_lean_rate() -> None:
    assert loop("grpo/loop.toml").health.stop_held_out_valid_fraction == 0.7


def test_the_loop_measures_the_minif2f_baseline_before_its_first_phase() -> None:
    assert loop("grpo/loop.toml").evaluation.minif2f.at_start


def test_the_loop_runs_the_held_out_states_with_every_probe_slot() -> None:
    evaluation = loop("grpo/loop.toml").evaluation
    assert evaluation.held_out_states.every_hours == evaluation.probe.every_hours


def test_the_loop_rolls_back_on_a_first_collapse() -> None:
    assert loop("grpo/loop.toml").health.rollback_window_phases > 0


def test_the_smoke_loop_runs_the_held_out_states_after_every_phase() -> None:
    evaluation = loop("grpo/loop_smoke.toml").evaluation
    assert evaluation.held_out_states.every_hours == evaluation.probe.every_hours
