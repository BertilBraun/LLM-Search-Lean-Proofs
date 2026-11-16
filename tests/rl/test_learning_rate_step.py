import dataclasses
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.rl.expert_iteration_data import parse_expert_iteration_config  # noqa: E402
from lean_search.rl.learning_rate_step import (  # noqa: E402
    NO_VALUE,
    STEP_VARIANTS,
    ArmValues,
    ExpertIterationRoundSize,
    GrpoRoundSize,
    PlanPaths,
    RoundKind,
    RoundRecord,
    RunRates,
    Signal,
    SignalRanking,
    StepReport,
    StepVariant,
    StudyTemplates,
    V0Baseline,
    arm_values,
    chosen_label,
    dry_run_steps,
    expert_iteration_round,
    grpo_phase_config,
    mode_description,
    plan_files,
    rank_arguments,
    read_durations,
    report_markdown,
    round_config_text,
    run_rates,
    signal_variants,
)
from lean_search.rl.probe_rating import DifferenceInterval  # noqa: E402
from lean_search.rl.rate_ranking import HeldOutStates, RateChoice, Variant, VariantReport, choose_rate  # noqa: E402
from lean_search.rl.single_step import SampleSuccess  # noqa: E402
from lean_search.rl.study_configs import merged, with_sampling_mode  # noqa: E402
from lean_search.search import load_run_config  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIGS = REPOSITORY / "experiments/configs/grpo"
SHARED_RUN = "followup_shared_sampling"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


BASE = toml(CONFIGS / "followup/base.toml")
TEMPLATES = StudyTemplates(
    BASE,
    toml(CONFIGS / "phase.toml"),
    toml(CONFIGS / "followup/expert_iteration.toml"),
    {signal: toml(CONFIGS / f"followup/arms/{signal}.toml") for signal in Signal},
)
VISIBLE_MODE = toml(CONFIGS / "followup/modes/visible.toml")


def variant(label: str) -> StepVariant:
    return next(found for found in STEP_VARIANTS if found.label == label)


def test_step_2_has_three_rates_for_a_and_b2_and_four_variants_for_c() -> None:
    counts = [len(signal_variants(signal)) for signal in Signal]
    assert counts == [3, 3, 4]


def test_the_variants_have_distinct_run_names() -> None:
    assert len({found.run_name for found in STEP_VARIANTS}) == len(STEP_VARIANTS)


@pytest.mark.parametrize(
    ("label", "run_name"),
    [("A_2e-5", "step2_A_2e-5"), ("B2_1e-4", "step2_B2_1e-4"), ("C_w4_5e-5", "step2_C_w4_5e-5")],
)
def test_a_variants_run_name_is_its_label_under_step2(label: str, run_name: str) -> None:
    assert variant(label).run_name == run_name


@pytest.mark.parametrize(
    ("label", "slices"),
    [("A_5e-5", (4,)), ("B2_2e-5", (4,)), ("C_w1_1e-4", (4,)), ("C_w4_1e-4", (1, 2, 3, 4))],
)
def test_a_variant_trains_on_the_last_slice_or_cs_whole_window(label: str, slices: tuple[int, ...]) -> None:
    assert variant(label).slices == slices


@pytest.mark.parametrize(
    ("label", "kind"),
    [("A_5e-5", RoundKind.GRPO), ("B2_5e-5", RoundKind.GRPO), ("C_w1_5e-5", RoundKind.EXPERT_ITERATION)],
)
def test_a_and_b2_train_by_grpo_and_c_by_expert_iteration(label: str, kind: RoundKind) -> None:
    assert variant(label).kind == kind


@pytest.mark.parametrize(
    ("label", "shipped"),
    [("A_2e-5", "phase.toml"), ("A_1e-4", "phase.toml"), ("B2_5e-5", "phase_proof_success.toml")],
)
def test_a_grpo_rounds_phase_config_is_its_credits_shipped_phase_at_its_rate(label: str, shipped: str) -> None:
    found = variant(label)
    expected = merged(toml(CONFIGS / shipped), {"policy": {"optimization": {"learning_rate": found.learning_rate}}})
    assert grpo_phase_config(found, TEMPLATES) == expected


def test_a_grpo_round_starts_from_v0_with_v0_as_its_kl_reference() -> None:
    policy = grpo_phase_config(variant("A_5e-5"), TEMPLATES)["policy"]
    v0 = BASE["initial"]["policy_adapter"]
    assert (policy["initial_adapter"], policy["reference_adapter"]) == (v0, v0)


@pytest.mark.parametrize(
    ("label", "directories"),
    [
        ("C_w1_5e-5", (f"{SHARED_RUN}/slices/slice_4",)),
        ("C_w4_1e-4", tuple(f"{SHARED_RUN}/slices/slice_{number}" for number in (1, 2, 3, 4))),
    ],
)
def test_an_expert_iteration_round_reads_its_slices_of_the_shared_run(label: str, directories: tuple) -> None:
    assert expert_iteration_round(variant(label), TEMPLATES, SHARED_RUN).data.tree_directories == directories


def test_an_expert_iteration_round_is_the_recipe_at_its_rate_but_for_what_step_2_fills_in() -> None:
    found = variant("C_w4_1e-4")
    round_config = expert_iteration_round(found, TEMPLATES, SHARED_RUN)
    recipe = parse_expert_iteration_config((CONFIGS / "followup/expert_iteration.toml").read_text(encoding="utf-8"))
    expected = dataclasses.replace(
        recipe,
        run_name="step2_C_w4_1e-4",
        data=dataclasses.replace(recipe.data, loop=SHARED_RUN, tree_directories=round_config.data.tree_directories),
        sft=dataclasses.replace(
            recipe.sft,
            data="step2_C_w4",
            optimization=dataclasses.replace(recipe.sft.optimization, learning_rate=1e-4),
        ),
    )
    assert round_config == expected


def test_both_rates_of_a_window_select_and_replay_the_same_data() -> None:
    first, second = (
        expert_iteration_round(variant(label), TEMPLATES, SHARED_RUN) for label in ("C_w1_5e-5", "C_w1_1e-4")
    )
    assert (first.data, first.replay, first.sft.data) == (second.data, second.replay, second.sft.data)


def test_an_expert_iteration_rounds_config_text_parses_back_to_the_round() -> None:
    found = variant("C_w1_5e-5")
    text = round_config_text(found, TEMPLATES, SHARED_RUN)
    assert parse_expert_iteration_config(text) == expert_iteration_round(found, TEMPLATES, SHARED_RUN)


def test_a_grpo_rounds_config_text_parses_back_to_its_phase_config() -> None:
    found = variant("B2_1e-4")
    assert tomllib.loads(round_config_text(found, TEMPLATES, SHARED_RUN)) == grpo_phase_config(found, TEMPLATES)


PATHS = PlanPaths(
    Path("/state/configs"),
    Path("/checkpoints"),
    Path("/runs"),
    SHARED_RUN,
    "/checkpoints/v0/adapter",
    Path("/data/lean.jsonl"),
    Path("/data/math.jsonl"),
)


def tsv_rows(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines()]


def test_every_round_line_has_nine_fields() -> None:
    assert {len(row) for row in tsv_rows(plan_files(PATHS).rounds)} == {9}


def test_no_plan_field_is_empty_for_bash_to_drop() -> None:
    plan = plan_files(PATHS)
    fields = [field for text in (plan.rounds, plan.builds, plan.held_out) for row in tsv_rows(text) for field in row]
    assert all(fields)


def test_the_rounds_run_in_the_variants_order() -> None:
    assert [row[0] for row in tsv_rows(plan_files(PATHS).rounds)] == [found.label for found in STEP_VARIANTS]


def test_a_grpo_round_line_names_slice_4_and_the_loops_replay() -> None:
    row = tsv_rows(plan_files(PATHS).rounds)[0]
    assert row[5:8] == [f"/runs/{SHARED_RUN}/slices/slice_4", "/data/lean.jsonl", "/data/math.jsonl"]


def test_an_expert_iteration_round_line_has_no_trees_or_replay_of_its_own() -> None:
    row = tsv_rows(plan_files(PATHS).rounds)[-1]
    assert row[5:8] == [NO_VALUE] * 3


@pytest.mark.parametrize(
    ("index", "completion"),
    [
        (0, "/checkpoints/step2_A_2e-5/phase.json /checkpoints/step2_A_2e-5/policy/adapter"),
        (-1, "/checkpoints/step2_C_w4_1e-4/training_summary.json /checkpoints/step2_C_w4_1e-4/adapter"),
    ],
)
def test_a_round_is_complete_only_with_the_files_its_trainer_writes_last(index: int, completion: str) -> None:
    assert tsv_rows(plan_files(PATHS).rounds)[index][8] == completion


def test_one_build_per_window_from_the_first_rates_config() -> None:
    builds = tsv_rows(plan_files(PATHS).builds)
    assert builds == [
        ["step2_C_w1", "/state/configs/C_w1_5e-5.toml"],
        ["step2_C_w4", "/state/configs/C_w4_5e-5.toml"],
    ]


def test_v0s_held_out_run_comes_first_with_v0s_adapter() -> None:
    assert tsv_rows(plan_files(PATHS).held_out)[0] == ["step2_v0", "v0", "0", "/checkpoints/v0/adapter"]


@pytest.mark.parametrize(
    ("index", "row"),
    [
        (1, ["step2_A_2e-5", "A_2e-5", "1", "/checkpoints/step2_A_2e-5/policy/adapter"]),
        (10, ["step2_C_w4_1e-4", "C_w4_1e-4", "1", "/checkpoints/step2_C_w4_1e-4/adapter"]),
    ],
)
def test_a_variants_held_out_run_evaluates_its_rounds_adapter(index: int, row: list[str]) -> None:
    assert tsv_rows(plan_files(PATHS).held_out)[index] == row


def test_the_ranking_of_a_signal_takes_its_three_variants_against_v0() -> None:
    assert rank_arguments(Signal.A) == [
        "--v0",
        "step2_v0",
        "--variant",
        "A_2e-5",
        "2e-5",
        "step2_A_2e-5",
        "--variant",
        "A_5e-5",
        "5e-5",
        "step2_A_5e-5",
        "--variant",
        "A_1e-4",
        "1e-4",
        "step2_A_1e-4",
    ]


def held_out(label: str, successes: int = 2) -> HeldOutStates:
    return HeldOutStates(label, {f"state_{index}": SampleSuccess(1, 8, successes, 6) for index in range(64)})


def test_c_tied_everywhere_takes_the_lower_rate_with_window_1() -> None:
    variants = [Variant(found.label, found.learning_rate, held_out(found.label)) for found in signal_variants(Signal.C)]
    assert choose_rate(variants).chosen == "C_w1_5e-5"


DRY_RUN = (
    "Continuing v0's adapter /a: 812 expert-iteration, 300 Lean and 90 math replay examples (60%, 30%, 10% of the "
    "completion tokens), 3,000,000 tokens, 9 steps on 4 GPUs; 40 expert-iteration and 1,000 replay validation examples"
)


def test_a_dry_runs_planned_steps_are_read() -> None:
    assert dry_run_steps(DRY_RUN) == 9


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (f"train would refuse: The loop runs (pid 5)\n{DRY_RUN}", "The loop runs"),
        (DRY_RUN.replace("9 steps", "0 steps"), "no optimizer step"),
        ("Continuing v0's adapter", "no step count"),
    ],
    ids=["refused", "no step", "unreadable"],
)
def test_a_dry_run_that_would_not_train_is_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dry_run_steps(text)


def test_the_rankings_choice_is_read_from_its_output() -> None:
    text = "| table |\n\nChosen: A_5e-5 (the held-out states decide; tied on the held-out states: A_5e-5)\n"
    assert chosen_label(text) == "A_5e-5"


def test_a_ranking_output_without_a_choice_is_refused() -> None:
    with pytest.raises(ValueError, match="found 0"):
        chosen_label("Against v0, points\n")


def interval(difference: float, lower: float, upper: float) -> DifferenceInterval:
    return DifferenceInterval(512, difference, lower, upper)


def ranking(signal: Signal, chosen: str, success: DifferenceInterval | None = None) -> SignalRanking:
    reports = tuple(
        VariantReport(
            found.label,
            found.learning_rate,
            interval(0.01, -0.01, 0.03),
            success or interval(0.05, 0.02, 0.08),
            None,
        )
        for found in signal_variants(signal)
    )
    choice = RateChoice(chosen, (chosen,), "the held-out states decide", (), ())
    return SignalRanking(signal, reports, choice)


RANKINGS = (ranking(Signal.A, "A_5e-5"), ranking(Signal.B2, "B2_1e-4"), ranking(Signal.C, "C_w4_5e-5"))


def test_the_arms_take_each_signals_chosen_rate_and_cs_window() -> None:
    assert arm_values(RANKINGS) == ArmValues("5e-5", "1e-4", "5e-5", 4)


def step_report(rankings: tuple[SignalRanking, ...] = RANKINGS) -> StepReport:
    rounds = tuple(
        RoundRecord(
            found,
            GrpoRoundSize(2400, 2300, 18000, 280, 9_000_000, 0.002, 0.01, 1500.0)
            if found.kind == RoundKind.GRPO
            else ExpertIterationRoundSize(800, 300, 90, 9, 9, 3_000_000, 600.0, 0.01),
            1800.0,
        )
        for found in STEP_VARIANTS
    )
    rates = RunRates("v0", 2945, 0.587, 0.34)
    baseline = V0Baseline(rates, rates, interval(0.0, -0.01, 0.01), interval(0.0, -0.01, 0.01), True)
    durations = {"s1_sampling": 9000.0, **{f"round_{found.label}": 1800.0 for found in STEP_VARIANTS}}
    return StepReport("abc1234", "visible reasoning", 48_100_000, 20_000, rankings, rounds, baseline, durations)


@pytest.mark.parametrize(
    "line",
    [
        "| arms/A.toml | phase.policy.optimization.learning_rate | 5e-5 |",
        "| arms/B2.toml | phase.policy.optimization.learning_rate | 1e-4 |",
        "| arms/C.toml | loop.training.expert_iteration_window_phases | 4 |",
        "| arms/C.toml | expert_iteration.sft.optimization.learning_rate | 5e-5 |",
        "| arms/D.toml | loop.training.expert_iteration_window_phases | 4 |",
        "| arms/D.toml | phase.policy.optimization.learning_rate | 5e-5 |",
        "| arms/D.toml | expert_iteration.sft.optimization.learning_rate | 5e-5 |",
    ],
)
def test_the_report_states_every_placeholders_value(line: str) -> None:
    assert line in report_markdown(step_report()).splitlines()


def test_the_report_shows_each_variant_against_v0_with_its_interval() -> None:
    assert "| A_2e-5 | 2e-05 | +1.0 [-1.0, +3.0] | +5.0 [+2.0, +8.0] | yes |" in report_markdown(step_report())


def test_the_report_flags_a_chosen_rate_within_noise_of_v0() -> None:
    rankings = (ranking(Signal.A, "A_5e-5", interval(0.01, -0.01, 0.03)), *RANKINGS[1:])
    assert "a step too small" in report_markdown(step_report(rankings))


def test_the_report_does_not_flag_a_chosen_rate_apart_from_v0() -> None:
    assert "a step too small" not in report_markdown(step_report())


def test_the_report_gives_the_shared_samplings_hours() -> None:
    assert "| Shared sampling (48M tokens) | 2.50 h |" in report_markdown(step_report())


def test_the_durations_keep_a_steps_last_line() -> None:
    assert read_durations("round_A\t100\t200\nround_A\t300\t700\n") == {"round_A": 400.0}


def test_a_runs_rates_pool_its_samples() -> None:
    run = HeldOutStates("v0", {"a": SampleSuccess(1, 8, 2, 4), "b": SampleSuccess(1, 2, 2, 2)})
    assert run_rates(run) == RunRates("v0", 10, 0.6, 0.4)


def test_the_visible_mode_is_the_bases_own_sampling() -> None:
    assert with_sampling_mode(BASE, VISIBLE_MODE) == BASE


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ({"sampling": {"search_config": "x.toml"}}, "misses"),
        ({"sampling": {"search_config": "x.toml", "max_expansions": 32, "concurrency": 56}}, "adds"),
        ({"sampling": {"search_config": "PLACEHOLDER: no-reasoning search", "max_expansions": 32}}, "placeholders"),
        ({"sampling": {"search_config": "x.toml", "max_expansions": 0}}, "positive integer"),
        ({"sampling": {"search_config": "x.toml", "max_expansions": 32.5}}, "positive integer"),
    ],
    ids=["missing expansions", "extra setting", "placeholder", "zero expansions", "fractional expansions"],
)
def test_a_mode_setting_other_than_the_search_and_its_expansions_is_refused(mode: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        with_sampling_mode(BASE, mode)


def test_a_mode_without_reasoning_changes_the_bases_search_and_expansions_only() -> None:
    mode = {"sampling": {"search_config": "no_reasoning.toml", "max_expansions": 74}}
    assert with_sampling_mode(BASE, mode) == merged(BASE, mode)


def test_the_visible_modes_description_names_reasoning_and_expansions() -> None:
    search_config = VISIBLE_MODE["sampling"]["search_config"]
    description = mode_description(search_config, load_run_config(REPOSITORY / search_config), 32)
    assert description.startswith("visible reasoning, 32 expansions per training search")


def test_the_grpo_size_rows_and_the_expert_iteration_rows_fill_two_tables() -> None:
    text = report_markdown(step_report())
    assert ("| A_2e-5 | 2400 |" in text, "| C_w1_5e-5 | 800 |" in text) == (True, True)
