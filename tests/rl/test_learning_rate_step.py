import dataclasses
import hashlib
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from loop_fakes import zero  # noqa: E402

from lean_search.rl.evaluation import EvaluationSummary  # noqa: E402
from lean_search.rl.learning_rate_step import (  # noqa: E402
    STEP_VARIANTS,
    GrpoRoundSize,
    O2Choice,
    PairedRun,
    PlanPaths,
    Ranking,
    RoundRecord,
    RunRates,
    StepReport,
    StepVariant,
    StudyTemplates,
    V0Baseline,
    chosen_label,
    dropped_states,
    grpo_phase_config,
    mode_description,
    o2_rate,
    plan_files,
    rank_arguments,
    read_durations,
    report_markdown,
    round_config_text,
    round_outcome_file,
    round_outcome_problem,
    run_rates,
)
from lean_search.rl.probe_rating import DifferenceInterval  # noqa: E402
from lean_search.rl.rate_ranking import (  # noqa: E402
    HeldOutStates,
    RateChoice,
    Variant,
    VariantReport,
    choose_rate,
    tie_break,
)
from lean_search.rl.single_step import SampleSuccess  # noqa: E402
from lean_search.rl.study_configs import (  # noqa: E402
    merged,
    sampling_record,
    sampling_refusal,
    training_search_refusal,
    with_sampling_mode,
)
from lean_search.rl.training_phase import PhaseOutcome  # noqa: E402
from lean_search.search import load_run_config  # noqa: E402
from lean_search.search.records import to_json  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIGS = REPOSITORY / "experiments/configs/grpo"
SHARED_RUN = "followup_shared_sampling"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


BASE = toml(CONFIGS / "followup/base.toml")
TEMPLATES = StudyTemplates(BASE, toml(CONFIGS / "phase.toml"), toml(CONFIGS / "followup/arms/A.toml"))
VISIBLE_MODE = toml(CONFIGS / "followup/modes/visible.toml")


def variant(label: str) -> StepVariant:
    return next(found for found in STEP_VARIANTS if found.label == label)


def test_step_2_trains_arm_a_at_three_rates() -> None:
    assert [found.rate for found in STEP_VARIANTS] == ["2e-5", "5e-5", "1e-4"]


def test_the_variants_have_distinct_run_names() -> None:
    assert len({found.run_name for found in STEP_VARIANTS}) == len(STEP_VARIANTS)


@pytest.mark.parametrize(("label", "run_name"), [("A_2e-5", "step2_A_2e-5"), ("A_1e-4", "step2_A_1e-4")])
def test_a_variants_run_name_is_its_label_under_step2(label: str, run_name: str) -> None:
    assert variant(label).run_name == run_name


@pytest.mark.parametrize("label", ["A_2e-5", "A_5e-5", "A_1e-4"])
def test_a_rounds_phase_config_is_the_shipped_per_tactic_phase_at_its_rate_and_phase_1s_seeds(label: str) -> None:
    found = variant(label)
    changes = {
        "policy": {
            "optimization": {"learning_rate": found.learning_rate, "seed": 1},
            # Arm A's explanation cap since 2026-11-19, after step 2's rounds.
            "data": {"cap_wasted_block_explanation": True},
        },
        "policy_replay": {"seed": "grpo-replay/1"},
        # Arm A's claim switches since 2026-11-18 (step 2's rounds ran before them).
        "reward": {"claims_earn_progress": False, "unproved_claim_cost": 0.3},
    }
    assert grpo_phase_config(found, TEMPLATES) == merged(toml(CONFIGS / "phase.toml"), changes)


def test_a_round_starts_from_v0_with_v0_as_its_kl_reference() -> None:
    policy = grpo_phase_config(variant("A_5e-5"), TEMPLATES)["policy"]
    v0 = BASE["initial"]["policy_adapter"]
    assert (policy["initial_adapter"], policy["reference_adapter"]) == (v0, v0)


def test_a_rounds_config_text_parses_back_to_its_phase_config() -> None:
    found = variant("A_1e-4")
    assert tomllib.loads(round_config_text(found, TEMPLATES)) == grpo_phase_config(found, TEMPLATES)


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


def test_every_round_line_has_eight_fields() -> None:
    assert {len(row) for row in tsv_rows(plan_files(PATHS).rounds)} == {8}


def test_no_plan_field_is_empty_for_bash_to_drop() -> None:
    plan = plan_files(PATHS)
    fields = [field for text in (plan.rounds, plan.held_out) for row in tsv_rows(text) for field in row]
    assert all(fields)


def test_the_rounds_run_in_the_variants_order() -> None:
    assert [row[0] for row in tsv_rows(plan_files(PATHS).rounds)] == [found.label for found in STEP_VARIANTS]


def test_a_round_line_names_the_shared_phases_trees_and_the_loops_replay() -> None:
    row = tsv_rows(plan_files(PATHS).rounds)[0]
    assert row[4:7] == [f"/runs/{SHARED_RUN}/slices/slice_1", "/data/lean.jsonl", "/data/math.jsonl"]


def test_a_round_is_complete_only_with_the_files_its_trainer_writes_last() -> None:
    completion = "/checkpoints/step2_A_2e-5/phase.json /checkpoints/step2_A_2e-5/policy/adapter"
    assert tsv_rows(plan_files(PATHS).rounds)[0][7] == completion


@pytest.mark.parametrize(
    ("index", "row"),
    [
        (1, ["step2_A_2e-5", "A_2e-5", "1", "/checkpoints/step2_A_2e-5/policy/adapter"]),
        (3, ["step2_A_1e-4", "A_1e-4", "1", "/checkpoints/step2_A_1e-4/policy/adapter"]),
    ],
)
def test_a_variants_held_out_run_evaluates_its_rounds_adapter(index: int, row: list[str]) -> None:
    assert tsv_rows(plan_files(PATHS).held_out)[index] == row


def test_the_ranking_takes_as_three_variants_against_v0() -> None:
    assert rank_arguments() == [
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


def test_a_tied_everywhere_takes_the_lowest_rate() -> None:
    variants = [Variant(found.label, found.learning_rate, held_out(found.label)) for found in STEP_VARIANTS]
    assert choose_rate(variants).chosen == "A_2e-5"


def test_the_rankings_choice_is_read_from_its_output() -> None:
    text = "| table |\n\nChosen: A_5e-5 (the held-out states decide; tied on the held-out states: A_5e-5)\n"
    assert chosen_label(text) == "A_5e-5"


def test_a_ranking_output_without_a_choice_is_refused() -> None:
    with pytest.raises(ValueError, match="found 0"):
        chosen_label("Against v0, points\n")


def interval(difference: float, lower: float, upper: float) -> DifferenceInterval:
    return DifferenceInterval(512, difference, lower, upper)


def ranking(
    chosen: str,
    success: DifferenceInterval | None = None,
    valid: DifferenceInterval | None = None,
) -> Ranking:
    reports = tuple(
        VariantReport(
            found.label,
            found.learning_rate,
            valid or interval(0.01, -0.01, 0.03),
            success or interval(0.05, 0.02, 0.08),
            None,
        )
        for found in STEP_VARIANTS
    )
    return Ranking(reports, RateChoice(chosen, (chosen,), "the held-out states decide", (), ()))


RATES = RunRates("v0", 2945, 0.587, 0.34)
NO_DRIFT = PairedRun(RATES, interval(0.0, -0.01, 0.01), interval(0.0, -0.01, 0.01))
BASELINE = V0Baseline(RATES, NO_DRIFT, NO_DRIFT, True)
O2_RANKING = "/workspace/runs/offline_chain/rank_matched.txt"
O2_SOURCE = f"O2's choice ({O2_RANKING})"
O2_CHOSE_1E_4 = O2Choice(O2_RANKING, "1e-4")
CHOSEN_5E_5 = ranking("A_5e-5")


def step_report(
    chosen: Ranking = CHOSEN_5E_5, baseline: V0Baseline = BASELINE, o2: O2Choice = O2_CHOSE_1E_4
) -> StepReport:
    rounds = tuple(
        RoundRecord(found, GrpoRoundSize(2400, 2300, 18000, 280, 9_000_000, 0.002, 0.01, 1500.0), 1800.0)
        for found in STEP_VARIANTS
    )
    durations = {"s1_sampling": 9000.0, **{f"round_{found.label}": 1800.0 for found in STEP_VARIANTS}}
    return StepReport("abc1234", "visible reasoning", 12_100_000, 20_000, chosen, rounds, baseline, durations, o2, 4)


@pytest.mark.parametrize(
    "line",
    [
        "| arms/A.toml | phase.policy.optimization.learning_rate | 5e-5 | step 2: A's chosen variant |",
        f"| arms/C.toml | expert_iteration.sft.optimization.learning_rate | 1e-4 | {O2_SOURCE} |",
        "| arms/D.toml | phase.policy.optimization.learning_rate | 5e-5 | A's |",
        f"| arms/D.toml | expert_iteration.sft.optimization.learning_rate | 1e-4 | C's: {O2_SOURCE} |",
    ],
)
def test_the_report_states_every_placeholders_value(line: str) -> None:
    assert line in report_markdown(step_report()).splitlines()


def test_the_report_says_cs_and_ds_window_is_already_set() -> None:
    assert "C's and D's window, 4 phases (owner, 2026-11-17), is already in" in report_markdown(step_report())


def test_the_report_leaves_cs_and_ds_rate_open_when_o2_has_not_ranked() -> None:
    missing = O2Choice(O2_RANKING, None, "no such file")
    text = report_markdown(step_report(o2=missing))
    assert f"**O2 not ranked yet** ({O2_RANKING}: no such file)" in text


def test_the_report_does_not_say_o2_is_missing_when_it_ranked() -> None:
    assert "O2 not ranked yet" not in report_markdown(step_report())


@pytest.mark.parametrize(("label", "rate"), [("matched_5e-5", "5e-5"), ("matched_1e-4", "1e-4")])
def test_o2s_rate_is_read_from_its_rankings_choice(label: str, rate: str) -> None:
    text = f"| table |\n\nChosen: {label} (the held-out states decide, on the flattened success; tied: {label})\n"
    assert o2_rate(text, ["5e-5", "1e-4"]) == rate


def test_a_ranking_choosing_another_subset_is_not_o2s_rate() -> None:
    with pytest.raises(ValueError, match="not one of"):
        o2_rate("Chosen: pool_5e-5 (the held-out states decide)\n", ["5e-5", "1e-4"])


def test_a_round_takes_the_arms_phase_1_seeds() -> None:
    config = grpo_phase_config(variant("A_5e-5"), TEMPLATES)
    assert (config["policy"]["optimization"]["seed"], config["policy_replay"]["seed"]) == (1, "grpo-replay/1")


def test_the_report_names_no_arm_b() -> None:
    assert "arms/B" not in report_markdown(step_report())


def test_the_report_shows_each_variant_against_v0_with_its_interval() -> None:
    row = "| A_2e-5 | 2e-5 | +1.0 [-1.0, +3.0] | within noise | +5.0 [+2.0, +8.0] | above v0 |"
    assert row in report_markdown(step_report())


def test_the_report_marks_a_variant_below_v0() -> None:
    row = "| A_5e-5 | 5e-5 | +1.0 [-1.0, +3.0] | within noise | -4.0 [-6.0, -2.0] | below v0 |"
    assert row in report_markdown(step_report(ranking("A_5e-5", interval(-0.04, -0.06, -0.02))))


@pytest.mark.parametrize(
    ("success", "valid", "measure"),
    [
        (interval(-0.04, -0.06, -0.02), None, "success"),
        (None, interval(-0.10, -0.13, -0.07), "valid Lean"),
    ],
    ids=["success", "valid Lean"],
)
def test_the_ranking_warns_when_the_chosen_variant_is_below_v0(
    success: DifferenceInterval | None, valid: DifferenceInterval | None, measure: str
) -> None:
    text = report_markdown(step_report(ranking("A_5e-5", success, valid)))
    assert f"**The chosen variant is below v0 in {measure}.**" in text


def test_the_values_table_says_look_first_when_the_chosen_variant_is_below_v0() -> None:
    text = report_markdown(step_report(ranking("A_5e-5", valid=interval(-0.10, -0.13, -0.07))))
    values = text.split("## Values for the arms")[1].split("| File |")[0]
    assert "**Look first:** A's chosen variant A_5e-5 is below v0 in valid Lean" in values


def test_no_look_first_without_the_chosen_variant_below_v0() -> None:
    assert "Look first" not in report_markdown(step_report())


def test_the_report_flags_v0_drifting_during_the_step() -> None:
    drifted = PairedRun(RATES, interval(-0.03, -0.05, -0.01), interval(0.0, -0.01, 0.01))
    text = report_markdown(step_report(baseline=V0Baseline(RATES, drifted, NO_DRIFT, True)))
    assert "**v0 moved during the step in valid Lean**" in text


def test_the_report_does_not_flag_v0_within_noise_of_itself() -> None:
    assert "v0 moved during the step" not in report_markdown(step_report())


def test_the_report_names_why_the_earlier_v0_run_is_not_compared() -> None:
    baseline = V0Baseline(RATES, NO_DRIFT, "v0: sampled another states file", True)
    text = report_markdown(step_report(baseline=baseline))
    assert "The earlier run is not compared: v0: sampled another states file" in text


def test_a_held_out_runs_dropped_states_are_read_from_its_summary() -> None:
    summary = to_json(dataclasses.replace(zero(EvaluationSummary), dropped=("state_7",)))
    assert dropped_states(summary) == ("state_7",)


@pytest.mark.parametrize(
    ("index", "row"),
    [
        (0, ["step2_v0", "v0", "0", "/checkpoints/v0/adapter"]),
        (-1, ["step2_v0_end", "v0", "0", "/checkpoints/v0/adapter"]),
    ],
    ids=["first", "last"],
)
def test_v0_is_evaluated_first_and_again_after_the_variants(index: int, row: list[str]) -> None:
    assert tsv_rows(plan_files(PATHS).held_out)[index] == row


def test_the_report_flags_a_chosen_rate_within_noise_of_v0() -> None:
    assert "a step too small" in report_markdown(step_report(ranking("A_5e-5", interval(0.01, -0.01, 0.03))))


def test_the_report_does_not_flag_a_chosen_rate_apart_from_v0() -> None:
    assert "a step too small" not in report_markdown(step_report())


def test_the_report_gives_the_shared_samplings_hours() -> None:
    assert "| Shared sampling (one phase, 12M tokens) | 2.50 h |" in report_markdown(step_report())


def test_the_durations_keep_a_steps_last_line() -> None:
    assert read_durations("round_A\t100\t200\nround_A\t300\t700\n") == {"round_A": 400.0}


def test_a_runs_rates_pool_its_samples() -> None:
    run = HeldOutStates("v0", {"a": SampleSuccess(1, 8, 2, 4), "b": SampleSuccess(1, 2, 2, 2)})
    assert run_rates(run) == RunRates("v0", 10, 0.6, 0.4)


def test_the_visible_mode_is_the_bases_own_sampling_with_the_efficiency_switches() -> None:
    sampling = dict(
        BASE["sampling"], search_config=BASE["sampling"]["search_config"].replace(".toml", "_sampling.toml")
    )
    assert with_sampling_mode(BASE, VISIBLE_MODE) == dict(BASE, sampling=sampling)


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


def test_the_report_gives_each_rounds_size() -> None:
    assert "| A_2e-5 | 2400 | 2300 | 18000 | 280 | 9,000,000 |" in report_markdown(step_report())


NO_REASONING_MODE = toml(CONFIGS / "followup/modes/no_reasoning.toml")
NO_REASONING_SEARCH = REPOSITORY / NO_REASONING_MODE["sampling"]["search_config"]


def test_the_no_reasoning_mode_keeps_the_visible_modes_expansions() -> None:
    assert NO_REASONING_MODE["sampling"]["max_expansions"] == VISIBLE_MODE["sampling"]["max_expansions"]


def test_the_no_reasoning_search_samples_without_visible_reasoning() -> None:
    assert load_run_config(NO_REASONING_SEARCH).policy.visible_reasoning is False


def test_the_no_reasoning_search_is_run_4s_without_its_token_cap_and_expansions() -> None:
    run_4 = toml(CONFIGS / "followup/step1/token_capped_no_reasoning.toml")
    for setting in ("max_generated_tokens", "max_expansions"):
        del run_4["search"][setting]
    search = toml(NO_REASONING_SEARCH)
    for setting in ("max_expansions", "result_cache", "timeout_skip", "nlinarith_variant"):
        del search["search"][setting]
    del search["lean"]
    assert search == run_4


def test_the_no_reasoning_search_is_a_training_search() -> None:
    assert training_search_refusal(load_run_config(NO_REASONING_SEARCH)) is None


def test_a_search_with_a_token_cap_is_refused_as_a_training_search() -> None:
    capped = load_run_config(NO_REASONING_SEARCH)
    capped = dataclasses.replace(capped, search=dataclasses.replace(capped.search, max_generated_tokens=26804))
    assert "caps each search at 26,804 generated tokens" in str(training_search_refusal(capped))


def test_the_sampling_record_names_the_search_configs_bytes() -> None:
    record = sampling_record(VISIBLE_MODE["sampling"], REPOSITORY)
    path = REPOSITORY / VISIBLE_MODE["sampling"]["search_config"]
    assert record.search_config_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_an_arm_sampling_as_the_shared_run_is_accepted() -> None:
    record = sampling_record(VISIBLE_MODE["sampling"], REPOSITORY)
    assert sampling_refusal(record, record) is None


@pytest.mark.parametrize(
    "change",
    [
        {"max_expansions": 74},
        {"search_config": "experiments/configs/grpo/search/no_reasoning_student_v2.toml"},
        {"search_config_sha256": "0" * 64},
    ],
    ids=["expansions", "search config", "search config bytes"],
)
def test_an_arm_sampling_otherwise_than_the_shared_run_is_refused(change: dict) -> None:
    shared = sampling_record(VISIBLE_MODE["sampling"], REPOSITORY)
    assert sampling_refusal(dataclasses.replace(shared, **change), shared) is not None


def test_the_tie_rule_takes_the_lower_rate() -> None:
    variants = [Variant(label, rate, held_out(label)) for label, rate in (("high", 1e-4), ("low", 2e-5))]
    assert tie_break(variants).label == "low"


@pytest.mark.parametrize(
    ("mode", "expansions", "binds"),
    [("no_reasoning", 32, False), ("no_reasoning", 48, False), ("no_reasoning", 74, True), ("visible", 32, True)],
    ids=["no reasoning at 32", "no reasoning at 48", "no reasoning at 74", "visible at 32 (cap 16)"],
)
def test_the_mode_description_warns_when_the_depth_cap_can_bind(mode: str, expansions: int, binds: bool) -> None:
    search_config = toml(CONFIGS / f"followup/modes/{mode}.toml")["sampling"]["search_config"]
    description = mode_description(search_config, load_run_config(REPOSITORY / search_config), expansions)
    assert ("the depth cap can bind" in description) == binds


def test_the_multiple_comparisons_note_counts_v0s_two_a_a_intervals() -> None:
    assert "8 95% intervals" in report_markdown(step_report())


def write_round_outcome(checkpoints: Path, found: StepVariant, text: str) -> None:
    path = round_outcome_file(found, checkpoints)
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


def test_a_rounds_phase_json_written_whole_reads_back(tmp_path: Path) -> None:
    write_round_outcome(tmp_path, variant("A_5e-5"), to_json(zero(PhaseOutcome)))
    assert round_outcome_problem(variant("A_5e-5"), tmp_path) is None


def test_a_rounds_phase_json_cut_short_is_not_complete(tmp_path: Path) -> None:
    write_round_outcome(tmp_path, variant("A_5e-5"), to_json(zero(PhaseOutcome))[:40])
    assert "does not read back" in str(round_outcome_problem(variant("A_5e-5"), tmp_path))


def test_the_report_says_only_the_trainer_differs_from_the_arms_first_update() -> None:
    assert "the trainer differs (grpo_phase.py here, the loop's persistent trainer in the arm)" in report_markdown(
        step_report()
    )
