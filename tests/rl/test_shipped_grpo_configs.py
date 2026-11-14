import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.policy.config import FeedbackConfig
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.expert_iteration_data import ExpertIterationConfig, parse_expert_iteration_config
from lean_search.rl.fixed_sets import (
    CharacterStrataConfig,
    FixedSetsConfig,
    character_strata,
    validate_character_strata,
)
from lean_search.rl.fixed_targets import baseline_concurrency, baseline_jobs, target_config
from lean_search.rl.loop_config import (
    EvaluationTarget,
    EvaluationValueModel,
    GrpoLoopConfig,
    HealthConfig,
    StatementSourceKind,
    load_loop_config,
)
from lean_search.rl.policy_trainer import GrpoConfig, ReferencePolicy
from lean_search.rl.search_options import OptionsArmConfig, SearchOptions
from lean_search.rl.single_step import SingleStepConfig
from lean_search.rl.training_phase import TrainingPhaseConfig
from lean_search.search import PriorityKind, RunConfig, load_run_config
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments" / "configs"
LOOPS = ["grpo/loop.toml", "grpo/loop_overfit.toml", "grpo/loop_smoke.toml", "grpo/followup/base.toml"]


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


def probe_v2() -> CharacterStrataConfig:
    text = (CONFIGS / "grpo/followup/probe_v2.toml").read_text(encoding="utf-8")
    return from_json_object(CharacterStrataConfig, tomllib.loads(text))


def test_probe_v2_takes_2000_statements_over_the_seven_character_bands() -> None:
    config = probe_v2()
    validate_character_strata(config)
    assert dict(zip(character_strata(config.edges), config.counts, strict=True)) == {
        "0-499": 150,
        "500-999": 250,
        "1000-1499": 350,
        "1500-1999": 350,
        "2000-2999": 400,
        "3000-4499": 300,
        "4500+": 200,
    }


def test_probe_v2_avoids_every_existing_fixed_set() -> None:
    old = from_json_object(
        FixedSetsConfig, tomllib.loads((CONFIGS / "grpo/fixed_sets.toml").read_text(encoding="utf-8"))
    )
    assert set(probe_v2().excluded_sets) == {old.probe_set, old.gate_set, old.overfit_set}


def test_probe_v2_avoids_the_loops_held_out_states() -> None:
    assert probe_v2().held_out_states_file == loop("grpo/loop.toml").evaluation.held_out_states_file


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


@pytest.mark.parametrize(
    "phase", ["grpo/phase.toml", "grpo/phase_sequence_credit.toml", "grpo/phase_proof_success.toml"]
)
def test_phase_config_starts_where_the_loop_starts(phase: str) -> None:
    policy = tomllib.loads((CONFIGS / phase).read_text(encoding="utf-8"))["policy"]
    starting = loop("grpo/loop.toml")
    expected = (starting.serving.policy_base_model, starting.initial.policy_adapter, starting.initial.policy_adapter)
    assert (policy["model"], policy["initial_adapter"], policy["reference_adapter"]) == expected


@pytest.mark.parametrize("other", ["grpo/phase_sequence_credit.toml", "grpo/phase_proof_success.toml"])
def test_other_credit_phase_differs_from_the_phase_only_in_its_credit(other: str) -> None:
    phase, changed = (
        tomllib.loads((CONFIGS / name).read_text(encoding="utf-8")) for name in ("grpo/phase.toml", other)
    )
    changed["policy"]["data"]["credit"] = phase["policy"]["data"]["credit"]
    assert changed == phase


def shipped_policy() -> GrpoConfig:
    text = (CONFIGS / "grpo/phase.toml").read_text(encoding="utf-8")
    policy = from_json_object(TrainingPhaseConfig, tomllib.loads(text)).policy
    assert policy is not None
    return policy


def test_the_phase_penalizes_the_kl_to_the_starting_policy() -> None:
    policy = shipped_policy()
    assert (policy.kl_coefficient, policy.reference) == (0.01, ReferencePolicy.STARTING_WEIGHTS)


def test_the_phase_trains_the_policy_at_2e_5() -> None:
    assert shipped_policy().optimization.learning_rate == 2e-5


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


@pytest.mark.parametrize("name", ["grpo/loop.toml", "grpo/loop_smoke.toml"])
def test_loop_evaluates_beside_sampling_with_the_published_value_model(name: str) -> None:
    evaluation = loop(name).evaluation
    assert (evaluation.beside_sampling, evaluation.value_model) == (True, EvaluationValueModel.PUBLISHED)


def test_the_overfit_loop_evaluates_at_the_pause() -> None:
    assert not loop("grpo/loop_overfit.toml").evaluation.beside_sampling


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


def test_the_loop_probe_has_as_many_repls_as_the_searches_beside_it_at_least() -> None:
    config = loop("grpo/loop.toml")
    assert config.evaluation.probe.concurrency == config.sampling.min_concurrency_beside_evaluations


def test_a_loop_probe_slot_fits_a_phase_and_the_pause_wait() -> None:
    assert loop("grpo/loop.toml").evaluation.probe.max_wall_seconds == 1800.0


def test_version_zeros_baselines_share_the_sampling_concurrency() -> None:
    config = loop("grpo/loop.toml")
    repls = sum(
        baseline_concurrency(config, kind) * baseline_jobs(config.evaluation, kind)
        for kind in EvaluationKind
        if target_config(config.evaluation, kind).at_start
    )
    assert repls == config.sampling.concurrency


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


def test_loop_phases_end_on_300_trainable_groups_within_75_to_120_minutes() -> None:
    training = loop("grpo/loop.toml").training
    assert (training.min_sampling_minutes, training.max_sampling_minutes, training.min_trainable_groups) == (
        75.0,
        120.0,
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


def test_the_loop_runs_the_feedback_a_b() -> None:
    assert loop("grpo/loop.toml").sampling.options_arm.name == "feedback"


def test_the_loop_feedback_a_b_ended_after_three_phases() -> None:
    assert loop("grpo/loop.toml").sampling.options_arm.max_phases == 3


def test_the_loop_feedback_arm_asks_for_4_samples_with_2_failed_attempts_below_2_new_states() -> None:
    feedback = loop("grpo/loop.toml").sampling.options_arm.options.feedback
    assert (feedback.enabled, feedback.min_children, feedback.max_attempts, feedback.sample_count) == (True, 2, 2, 4)


def test_the_loop_feedback_arm_changes_nothing_but_the_feedback_round() -> None:
    options = loop("grpo/loop.toml").sampling.options_arm.options
    assert dataclasses.replace(options, feedback=FeedbackConfig()) == SearchOptions()


def test_the_loop_feeds_35_percent_from_below_the_curriculum_band() -> None:
    assert loop("grpo/loop.toml").statements.curriculum.below_band_share == 0.35


@pytest.mark.parametrize("name", ["grpo/loop_overfit.toml", "grpo/loop_smoke.toml"])
def test_the_other_loops_run_no_a_b(name: str) -> None:
    assert loop(name).sampling.options_arm.name == ""


def expert_iteration(name: str = "expert_iteration_1.toml") -> ExpertIterationConfig:
    return parse_expert_iteration_config((CONFIGS / "grpo" / name).read_text(encoding="utf-8"))


def test_expert_iteration_config_parses() -> None:
    assert expert_iteration().sft.optimization.learning_rate == 5e-5


@pytest.mark.parametrize("name", ["expert_iteration_1.toml", "expert_iteration_1_b.toml", "expert_iteration_1_c.toml"])
def test_round_one_configs_take_their_phases_from_the_reward_fix(name: str) -> None:
    assert expert_iteration(name).data.window_phases == 0


@pytest.mark.parametrize(
    ("name", "run_name", "learning_rate", "epochs"),
    [
        ("expert_iteration_1_b.toml", "grpo_loop_v1_expert_iteration_01b", 1e-4, 1),
        ("expert_iteration_1_c.toml", "grpo_loop_v1_expert_iteration_01c", 1e-4, 2),
    ],
)
def test_expert_iteration_variants_differ_only_in_run_name_learning_rate_and_epochs(
    name: str, run_name: str, learning_rate: float, epochs: int
) -> None:
    variant = expert_iteration(name)
    base = expert_iteration()
    optimization = dataclasses.replace(base.sft.optimization, learning_rate=learning_rate, epochs=epochs)
    expected = dataclasses.replace(
        base, run_name=run_name, sft=dataclasses.replace(base.sft, optimization=optimization)
    )
    assert variant == expected


def test_expert_iteration_trains_on_the_loops_policy_base() -> None:
    assert expert_iteration().sft.model == loop("grpo/loop.toml").serving.policy_base_model


def test_expert_iteration_replays_the_loops_replay() -> None:
    replay = expert_iteration().replay
    training = loop("grpo/loop.toml").training
    assert (replay.lean_replay, replay.math_replay) == (training.lean_replay, training.math_replay)


def test_expert_iteration_reads_the_shipped_loop() -> None:
    assert expert_iteration().data.loop == loop("grpo/loop.toml").name


def test_the_followup_base_differs_from_the_loop_only_in_the_followups_settings() -> None:
    base, old = loop("grpo/followup/base.toml"), loop("grpo/loop.toml")
    curriculum = dataclasses.replace(
        old.statements.curriculum,
        verified="followup/verified_pool_2026-11-01.jsonl",
        verified_sha256="1b216b06e30148a1e652291098c642842dadad83e2a6eaca9b85e3cb2aa5600c",
        proof_steps_weight=0.0,
        root_value_weight=0.0,
        characters_weight=1.0,
        band_width=2.0,
        initial_band_low=10.0,
    )
    statements = dataclasses.replace(
        old.statements,
        curriculum=curriculum,
        held_out=(
            *old.statements.held_out,
            "grpo/fixed_sets/probe_v2.jsonl",
            "grpo/fixed_sets/probe_v2_twins.jsonl",
        ),
        difficulty_band_edges=(5.0, 10.0, 15.0, 20.0, 30.0, 45.0),
    )
    evaluation = dataclasses.replace(
        old.evaluation,
        probe_set="grpo/fixed_sets/probe_v2.jsonl",
        beside_sampling=False,
        probe_parts=1,
        probe=EvaluationTarget(16, 7200.0, 56, every_hours=0.0, at_start=False, baseline_runs=1),
        minif2f=EvaluationTarget(64, 7200.0, 56, every_hours=0.0, at_start=False),
        held_out_states=EvaluationTarget(1, 120.0, 56, every_hours=0.01, at_start=True, baseline_concurrency=56),
    )
    health = dataclasses.replace(
        old.health, reference_phases=1, rollback_window_phases=0, resume_beside_held_out_states=False
    )
    expected = dataclasses.replace(
        old,
        name="grpo_followup_base",
        sampling=dataclasses.replace(old.sampling, concurrency=56, options_arm=OptionsArmConfig()),
        training=dataclasses.replace(old.training, kl_reference_policy_adapter=""),
        statements=statements,
        evaluation=evaluation,
        retention=dataclasses.replace(old.retention, adapter_versions=0),
        health=health,
    )
    assert base == expected


def followup() -> GrpoLoopConfig:
    return loop("grpo/followup/base.toml")


def test_the_followup_base_holds_out_probe_v2_and_its_twins() -> None:
    held_out = followup().statements.held_out
    assert {probe_v2().output, probe_v2().twins_output} <= set(held_out)


def test_the_followup_base_and_probe_v2_read_the_same_frozen_pool() -> None:
    curriculum, probe = followup().statements.curriculum, probe_v2().curriculum
    assert (curriculum.verified, curriculum.verified_sha256) == (probe.verified, probe.verified_sha256)


def test_the_followup_curriculum_bins_are_probe_v2s_bands() -> None:
    edges = followup().statements.difficulty_band_edges
    assert [edge * 100 for edge in edges] == list(probe_v2().edges)


def test_the_followup_probe_records_the_followup_curriculums_difficulty() -> None:
    curriculum = followup().statements.curriculum
    weights = (curriculum.proof_steps_weight, curriculum.root_value_weight, curriculum.characters_weight)
    probe = probe_v2().curriculum
    assert (probe.proof_steps_weight, probe.root_value_weight, probe.characters_weight) == weights


@pytest.mark.parametrize("kind", [EvaluationKind.PROBE, EvaluationKind.MINIF2F])
def test_the_followup_runs_no_probe_or_minif2f_inside_an_arm(kind: EvaluationKind) -> None:
    target = target_config(followup().evaluation, kind)
    assert (target.every_hours, target.at_start) == (0.0, False)


def test_the_followup_runs_nothing_beside_sampling() -> None:
    assert not followup().evaluation.beside_sampling


def test_the_followup_held_out_states_are_due_at_every_pause() -> None:
    assert followup().evaluation.held_out_states.every_hours * 3600 < 60


def test_version_zeros_held_out_baseline_runs_at_the_pauses_concurrency() -> None:
    held_out = followup().evaluation.held_out_states
    assert baseline_concurrency(followup(), EvaluationKind.HELD_OUT_STATES) == held_out.concurrency


def test_the_followup_searches_wait_for_the_held_out_states_last_checks() -> None:
    assert not followup().health.resume_beside_held_out_states


def test_the_followup_sampling_concurrency_is_a_placeholder_within_the_new_nodes_quota() -> None:
    assert followup().sampling.concurrency <= 56


def test_the_followup_held_out_concurrency_is_a_placeholder_within_the_new_nodes_quota() -> None:
    assert followup().evaluation.held_out_states.concurrency <= 56


def test_the_followup_keeps_every_adapter() -> None:
    assert followup().retention.adapter_versions == 0


def test_the_followup_stops_at_the_first_collapse() -> None:
    assert followup().health.rollback_window_phases == 0


def test_each_arms_health_reference_is_its_own_first_phase() -> None:
    assert followup().health.reference_phases == 1
