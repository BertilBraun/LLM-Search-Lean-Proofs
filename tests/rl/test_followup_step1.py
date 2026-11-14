import dataclasses
import tomllib
from pathlib import Path

import pytest

from lean_search.policy.config import StepLogProbability
from lean_search.rl.probe_evaluation import ProbeCheckpoint, ProbeRunRecord, ProbeRunStart, RunEnvironment
from lean_search.rl.probe_run_list import (
    LEDGER_FILE,
    PlannedRun,
    RunList,
    RunState,
    interleaved,
    probe_arguments,
    read_run_list,
    record_finished,
    run_refusals,
    run_state,
)
from lean_search.rl.step1_settings import StepValue, TokenBudget, automation_constant
from lean_search.rl.study_configs import placeholders
from lean_search.search.records import to_json

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"
STEP1 = FOLLOWUP / "step1"
SEARCH = REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml"
STUDY_CONCURRENCY = 56
SETTINGS = [setting.value for setting in StepLogProbability]


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def planned(name: str, **settings: object) -> PlannedRun:
    run = PlannedRun(name=name, arm="v0", phase=0, policy_adapter="/adapters/v0", value="v0")
    return dataclasses.replace(run, **settings)


def test_the_lists_runs_are_interleaved() -> None:
    first = RunList((planned("a1"), planned("a2"), planned("a3")))
    second = RunList((planned("b1"), planned("b2")))
    assert [run.name for run in interleaved([first, second])] == ["a1", "b1", "a2", "b2", "a3"]


def test_a_name_given_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="more than once"):
        interleaved([RunList((planned("a"),)), RunList((planned("a"),))])


def test_a_run_becomes_its_probe_evaluate_arguments() -> None:
    run = planned("r", value="/adapters/value", value_version=35, search_config="s.toml", problems=200)
    assert probe_arguments(run) == [
        *("--config", "experiments/configs/grpo/followup/probe_evaluation.toml", "--name", "r"),
        *("--arm", "v0", "--phase", "0", "--policy-adapter", "/adapters/v0", "--value", "/adapters/value"),
        *("--value-version", "35", "--search-config", "s.toml", "--problems", "200"),
    ]


def test_the_anchor_flag_is_passed_on() -> None:
    assert probe_arguments(planned("r", anchor=True))[-1] == "--anchor"


def test_placeholders_are_found_in_nested_tables_and_arrays_of_tables() -> None:
    table = {"a": {"b": "PLACEHOLDER x", "c": 1}, "d": [{"e": "PLACEHOLDER y"}], "f": "set"}
    assert placeholders(table) == ["a.b", "d[0].e"]


def write_repository(root: Path, concurrency: int = STUDY_CONCURRENCY, search: str = "") -> Path:
    (root / "search.toml").write_text(search or "[search]\nmax_expansions = 16\n", encoding="utf-8")
    evaluation = f'loop_config = "loop.toml"\nsearch_config = "search.toml"\n[probe]\nconcurrency = {concurrency}\n'
    (root / "evaluation.toml").write_text(evaluation, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("run", "concurrency", "search"),
    [
        (planned("r", config="evaluation.toml", value="PLACEHOLDER: a path"), STUDY_CONCURRENCY, ""),
        (planned("r", config="evaluation.toml"), STUDY_CONCURRENCY, '[search]\nmax_generated_tokens = "PLACEHOLDER"\n'),
        (planned("r", config="evaluation.toml"), 64, ""),
    ],
    ids=["placeholder path", "placeholder in the search config", "another concurrency"],
)
def test_a_run_that_is_not_ready_is_refused(tmp_path: Path, run: PlannedRun, concurrency: int, search: str) -> None:
    assert run_refusals(run, write_repository(tmp_path, concurrency, search), STUDY_CONCURRENCY)


def test_a_value_free_run_with_an_uncalibrated_constant_is_refused() -> None:
    run = planned("r", value="none", config="experiments/configs/grpo/followup/step1/value_free_block_sum.toml")
    assert any("placeholder" in refusal for refusal in run_refusals(run, REPOSITORY, STUDY_CONCURRENCY))


def test_a_ready_run_is_not_refused(tmp_path: Path) -> None:
    assert run_refusals(planned("r", config="evaluation.toml"), write_repository(tmp_path), STUDY_CONCURRENCY) == []


@pytest.mark.parametrize("path", sorted(STEP1.glob("runs_*.toml")), ids=lambda path: path.name)
def test_every_step1_run_list_reads(path: Path) -> None:
    assert read_run_list(path).runs


@pytest.mark.parametrize("name", ["runs_anchor.toml", "runs_calibration.toml"])
def test_the_runs_that_need_nothing_measured_are_ready(name: str) -> None:
    runs = read_run_list(STEP1 / name).runs
    assert [refusal for run in runs for refusal in run_refusals(run, REPOSITORY, STUDY_CONCURRENCY)] == []


@pytest.mark.parametrize(
    "name",
    [
        "runs_old_value.toml",
        "runs_value_free_pilots.toml",
        "runs_value_free_full.toml",
        "runs_reasoning_pilot.toml",
        "runs_reasoning.toml",
        "runs_optional_v35.toml",
    ],
)
def test_every_run_waiting_for_a_measurement_or_a_path_is_refused(name: str) -> None:
    runs = read_run_list(STEP1 / name).runs
    assert all(run_refusals(run, REPOSITORY, STUDY_CONCURRENCY) for run in runs)


def test_both_anchor_runs_are_the_ratings_anchor() -> None:
    assert all(run.anchor for run in read_run_list(STEP1 / "runs_anchor.toml").runs)


def test_the_value_free_pilots_try_every_step_log_probability_setting() -> None:
    runs = read_run_list(STEP1 / "runs_value_free_pilots.toml").runs
    settings = [toml(REPOSITORY / run.config)["value_free_priority"]["step_log_probability"] for run in runs]
    assert (sorted(settings), {run.problems for run in runs}) == (sorted(SETTINGS), {200})


@pytest.mark.parametrize("setting", SETTINGS)
def test_a_value_free_config_differs_from_the_probes_only_in_its_value_free_priority(setting: str) -> None:
    changed, probe = toml(STEP1 / f"value_free_{setting}.toml"), toml(FOLLOWUP / "probe_evaluation.toml")
    assert {**changed, "value_free_priority": probe["value_free_priority"]} == probe


@pytest.mark.parametrize("setting", SETTINGS)
def test_a_calibration_config_searches_one_expansion_of_the_calibration_statements(setting: str) -> None:
    changed, probe = toml(STEP1 / f"calibration_{setting}.toml"), toml(FOLLOWUP / "probe_evaluation.toml")
    changed |= {"probe_set": probe["probe_set"], "output": probe["output"]}
    changed["probe"] = {**changed["probe"], "max_expansions": probe["probe"]["max_expansions"]}
    changed["value_free_priority"] = probe["value_free_priority"]
    assert changed == probe


@pytest.mark.parametrize("setting", SETTINGS)
def test_a_calibration_config_searches_with_its_setting(setting: str) -> None:
    assert toml(STEP1 / f"calibration_{setting}.toml")["value_free_priority"]["step_log_probability"] == setting


def test_the_calibration_draws_200_statements_outside_probe_v2_and_its_twins() -> None:
    config, probe = toml(STEP1 / "calibration_statements.toml"), toml(FOLLOWUP / "probe_v2.toml")
    held_out = {probe["output"], probe["twins_output"], *probe["excluded_sets"]}
    assert (sum(config["counts"]), held_out <= set(config["excluded_sets"])) == (200, True)


def test_the_calibration_draws_from_probe_v2s_frozen_pool_in_another_order() -> None:
    config, probe = toml(STEP1 / "calibration_statements.toml"), toml(FOLLOWUP / "probe_v2.toml")
    assert (config["curriculum"], config["edges"], config["seed"] != probe["seed"]) == (
        probe["curriculum"],
        probe["edges"],
        True,
    )


def test_the_token_capped_runs_differ_from_the_loops_search_only_in_their_budget_and_depth_term() -> None:
    capped, template = toml(STEP1 / "token_capped_visible.toml"), toml(SEARCH)
    expected = {**template["search"], "max_expansions": 1024, "max_depth": 64}
    expected["max_generated_tokens"] = capped["search"]["max_generated_tokens"]
    template["priority"]["depth_weight"] = 0.0
    assert capped == {**template, "search": expected}


def test_the_no_reasoning_run_differs_from_the_visible_one_only_in_its_reasoning() -> None:
    visible, plain = toml(STEP1 / "token_capped_visible.toml"), toml(STEP1 / "token_capped_no_reasoning.toml")
    visible["policy"]["visible_reasoning"] = False
    assert plain == visible


@pytest.mark.parametrize("name", ["token_capped_visible.toml", "token_capped_no_reasoning.toml"])
def test_the_token_cap_waits_for_the_anchor_run(name: str) -> None:
    assert placeholders(toml(STEP1 / name)) == ["search.max_generated_tokens"]


def test_the_token_cap_is_16_times_the_tokens_per_expansion() -> None:
    assert TokenBudget(searches=2, expansions=30, generated_tokens=51_000).cap(16) == 27_200


def test_the_automation_constant_is_the_median_over_samples() -> None:
    values = [StepValue(-1.0, 1), StepValue(-5.0, 3)]
    assert automation_constant(StepLogProbability.BLOCK_SUM, values).constant == -5.0


def test_a_calibration_without_progress_is_refused() -> None:
    with pytest.raises(ValueError, match="No sample made progress"):
        automation_constant(StepLogProbability.BLOCK_MEAN, [])


def finished(root: Path, name: str, accepted: bool) -> PlannedRun:
    directory = root / "probe_evaluations" / f"probe_{name}"
    directory.mkdir(parents=True)
    checkpoint = ProbeCheckpoint("v0", 0, "/adapters/v0", "digest", "", "", 0, 0, -1)
    start = ProbeRunStart(f"{name} identity", False, checkpoint, "s.toml", "sha", 56, 7200.0, 16, "probe.jsonl", "sha")
    environment = RunEnvironment("node", "lean", "vllm", "torch")
    record = ProbeRunRecord(start, environment, 2000, 700, 4, 0.002, (), 0.01, accepted)
    (directory / "run.json").write_text(to_json(record), encoding="utf-8")
    (directory / "summary.json").write_text('{"wall_seconds": 18000.0}', encoding="utf-8")
    (root / "evaluation.toml").write_text('output = "probe_evaluations"\n', encoding="utf-8")
    return planned(name, config="evaluation.toml")


@pytest.mark.parametrize(("accepted", "state"), [(True, RunState.ACCEPTED), (False, RunState.REJECTED)])
def test_a_finished_runs_state_is_its_run_record(tmp_path: Path, accepted: bool, state: RunState) -> None:
    finished(tmp_path, "r", accepted)
    assert run_state(tmp_path / "probe_evaluations" / "probe_r") == state


def test_a_run_without_its_record_is_pending(tmp_path: Path) -> None:
    assert run_state(tmp_path / "probe_r") == RunState.PENDING


def test_a_finished_run_gets_one_ledger_line_however_often_it_is_recorded(tmp_path: Path) -> None:
    run = finished(tmp_path, "r", True)
    record_finished([run], tmp_path, tmp_path)
    record_finished([run], tmp_path, tmp_path)
    lines = (tmp_path / "probe_evaluations" / LEDGER_FILE).read_text(encoding="utf-8").splitlines()
    assert lines[1:] == ["r\tr identity\t700\t2000\t0.0020\t5.00\tTrue"]
