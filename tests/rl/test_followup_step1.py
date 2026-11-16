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
    evaluation_config,
    interleaved,
    missing_files,
    planned_run_config_sha256,
    probe_arguments,
    read_run_list,
    record_finished,
    run_refusals,
    run_state,
    start_mismatches,
)
from lean_search.rl.step1_settings import TokenBudget, automation_constant
from lean_search.rl.study_configs import placeholders, resolved_toml
from lean_search.search.records import to_json

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"
STEP1 = FOLLOWUP / "step1"
SEARCH = REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml"
PROBE_EVALUATION = FOLLOWUP / "probe_evaluation.toml"
SETTINGS = [setting.value for setting in StepLogProbability]
RUN_LISTS = sorted(STEP1.glob("runs_*.toml"))
# Every evaluation config of the study: the probe's and those over it.
STUDY_EVALUATIONS = [PROBE_EVALUATION, FOLLOWUP / "gate_evaluation.toml", *sorted(STEP1.glob("*_evaluation.toml"))]
STUDY_EVALUATIONS += sorted(STEP1.glob("value_free_*.toml"))


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


STUDY_CONCURRENCY = toml(PROBE_EVALUATION)["probe"]["concurrency"]


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


def test_a_config_over_a_base_changes_only_its_own_keys(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("a = 1\n[t]\nb = 2\nc = 3\n", encoding="utf-8")
    (tmp_path / "over.toml").write_text('base = "base.toml"\n[t]\nc = 4\n', encoding="utf-8")
    assert resolved_toml(tmp_path / "over.toml", tmp_path) == {"a": 1, "t": {"b": 2, "c": 4}}


def write_repository(root: Path, concurrency: int = STUDY_CONCURRENCY, search: str = "") -> Path:
    """The study's search config (or `search`) and follow-up base with value v0 at /adapters/value_v0, beside another
    search config (other.toml: the same with another expansion budget)."""
    (root / "search.toml").write_text(search or SEARCH.read_text(encoding="utf-8"), encoding="utf-8")
    other = SEARCH.read_text(encoding="utf-8").replace("max_expansions = ", "max_expansions = 1", 1)
    (root / "other.toml").write_text(other, encoding="utf-8")
    evaluation = (
        'loop_config = "loop.toml"\nsearch_config = "search.toml"\nprobe_set = "probe.jsonl"\n'
        f"[probe]\nmax_expansions = 16\nconcurrency = {concurrency}\nmax_wall_seconds = 7200.0\n"
    )
    (root / "evaluation.toml").write_text(evaluation, encoding="utf-8")
    base = (FOLLOWUP / "base.toml").read_text(encoding="utf-8")
    value_v0 = toml(FOLLOWUP / "base.toml")["initial"]["value_adapter"]
    (root / "loop.toml").write_text(base.replace(value_v0, "/adapters/value_v0"), encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("run", "concurrency", "search"),
    [
        (planned("r", config="evaluation.toml", value="PLACEHOLDER: a path"), STUDY_CONCURRENCY, ""),
        (planned("r", config="evaluation.toml"), STUDY_CONCURRENCY, '[search]\nmax_generated_tokens = "PLACEHOLDER"\n'),
        (planned("r", config="evaluation.toml"), 56, ""),
        (planned("r", config="evaluation.toml", value="/adapters/value"), STUDY_CONCURRENCY, ""),
        (planned("r", config="evaluation.toml", anchor=True, problems=200), STUDY_CONCURRENCY, ""),
    ],
    ids=["placeholder path", "placeholder in the search config", "another concurrency", "no value version", "anchor"],
)
def test_a_run_that_is_not_ready_is_refused(tmp_path: Path, run: PlannedRun, concurrency: int, search: str) -> None:
    assert run_refusals(run, write_repository(tmp_path, concurrency, search), STUDY_CONCURRENCY)


def test_a_value_free_run_with_an_uncalibrated_constant_is_refused() -> None:
    run = planned("r", value="none", config="experiments/configs/grpo/followup/step1/value_free_block_sum.toml")
    assert any("placeholder" in refusal for refusal in run_refusals(run, REPOSITORY, STUDY_CONCURRENCY))


def test_a_ready_run_is_not_refused(tmp_path: Path) -> None:
    assert run_refusals(planned("r", config="evaluation.toml"), write_repository(tmp_path), STUDY_CONCURRENCY) == []


def test_a_run_without_its_adapter_or_probe_set_on_the_node_is_refused(tmp_path: Path) -> None:
    run = planned("r", config="evaluation.toml", policy_adapter=str(tmp_path / "missing"))
    assert len(missing_files(run, write_repository(tmp_path), tmp_path)) == 2


@pytest.mark.parametrize("path", RUN_LISTS, ids=lambda path: path.name)
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
        "runs_reasoning.toml",
        "runs_optional_v35.toml",
    ],
)
def test_every_run_waiting_for_a_measurement_or_a_path_is_refused(name: str) -> None:
    runs = read_run_list(STEP1 / name).runs
    assert all(run_refusals(run, REPOSITORY, STUDY_CONCURRENCY) for run in runs)


def test_both_anchor_runs_are_the_ratings_anchor() -> None:
    assert all(run.anchor for run in read_run_list(STEP1 / "runs_anchor.toml").runs)


def test_run_4s_pilot_comes_before_runs_3_and_4() -> None:
    runs = read_run_list(STEP1 / "runs_reasoning.toml").runs
    assert [run.problems for run in runs] == [200, 0, 0]


def test_the_reasoning_runs_share_the_doubled_wall_cap() -> None:
    runs = read_run_list(STEP1 / "runs_reasoning.toml").runs
    assert {evaluation_config(run, REPOSITORY)["probe"]["max_wall_seconds"] for run in runs} == {14400.0}


def test_the_value_free_pilots_try_every_step_log_probability_setting() -> None:
    runs = read_run_list(STEP1 / "runs_value_free_pilots.toml").runs
    settings = [evaluation_config(run, REPOSITORY)["value_free_priority"]["step_log_probability"] for run in runs]
    assert (sorted(settings), {run.problems for run in runs}) == (sorted(SETTINGS), {200})


def every_planned_run() -> list[PlannedRun]:
    return [run for path in RUN_LISTS for run in read_run_list(path).runs]


def test_every_run_on_a_value_free_config_has_no_value_model() -> None:
    assert {run.value for run in every_planned_run() if "value_free_" in run.config} == {"none"}


def test_every_run_without_a_value_model_searches_on_a_value_free_config() -> None:
    assert all("value_free_" in run.config for run in every_planned_run() if run.value == "none")


@pytest.mark.parametrize("path", STUDY_EVALUATIONS, ids=lambda path: path.name)
def test_every_study_evaluation_config_resolves_to_the_one_probe_concurrency(path: Path) -> None:
    assert resolved_toml(path, REPOSITORY)["probe"]["concurrency"] == STUDY_CONCURRENCY


@pytest.mark.parametrize("path", STUDY_EVALUATIONS[1:], ids=lambda path: path.name)
def test_no_other_study_evaluation_config_changes_the_probe_beyond_its_wall_cap(path: Path) -> None:
    assert (toml(path)["base"], set(toml(path).get("probe", {})) - {"max_wall_seconds"}) == (
        "experiments/configs/grpo/followup/probe_evaluation.toml",
        set(),
    )


@pytest.mark.parametrize("setting", SETTINGS)
def test_a_value_free_config_changes_only_the_value_free_priority(setting: str) -> None:
    assert set(toml(STEP1 / f"value_free_{setting}.toml")) == {"base", "value_free_priority"}


@pytest.mark.parametrize("setting", SETTINGS)
def test_a_value_free_config_carries_a_constant_for_its_own_setting_only(setting: str) -> None:
    priority = resolved_toml(STEP1 / f"value_free_{setting}.toml", REPOSITORY)["value_free_priority"]
    constants = {constant["step_log_probability"] for constant in priority["automation_constants"]}
    assert (priority["step_log_probability"], constants) == (setting, {setting})


def test_the_calibration_run_is_the_probe_evaluation_on_the_calibration_statements() -> None:
    config = toml(STEP1 / "calibration_evaluation.toml")
    assert (config["probe_set"], config["output"]) == (
        "grpo/fixed_sets/calibration_200.jsonl",
        "calibration_evaluations",
    )


def test_the_calibration_run_searches_with_value_v0() -> None:
    (run,) = read_run_list(STEP1 / "runs_calibration.toml").runs
    assert (run.value, run.config) == ("v0", "experiments/configs/grpo/followup/step1/calibration_evaluation.toml")


def test_the_gate_evaluation_is_the_probe_evaluation_on_the_gate_set_in_its_own_output() -> None:
    gate, probe = resolved_toml(FOLLOWUP / "gate_evaluation.toml", REPOSITORY), toml(PROBE_EVALUATION)
    assert {**gate, "probe_set": probe["probe_set"], "output": probe["output"]} == probe


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


def test_the_automation_constant_is_the_median_over_edges() -> None:
    assert automation_constant(StepLogProbability.BLOCK_SUM, [-1.0, -5.0, -6.0]).constant == -5.0


def test_a_calibration_without_progress_is_refused() -> None:
    with pytest.raises(ValueError, match="No policy step made progress"):
        automation_constant(StepLogProbability.BLOCK_MEAN, [])


def start(**changes: object) -> ProbeRunStart:
    checkpoint = ProbeCheckpoint("v0", 0, "/adapters/v0", "digest", "/adapters/value_v0", "value digest", 0, 0, 0)
    started = ProbeRunStart(
        "r identity", False, checkpoint, "search.toml", "sha", STUDY_CONCURRENCY, 7200.0, 16, "probe.jsonl", "sha"
    )
    return dataclasses.replace(started, **changes)


def matching_start(repository: Path) -> ProbeRunStart:
    """A record of planned("r") with the run config's digest it searches with."""
    return start(run_config_sha256=planned_run_config_sha256(planned("r", config="evaluation.toml"), repository))


def test_a_record_matching_the_list_has_no_mismatch(tmp_path: Path) -> None:
    repository = write_repository(tmp_path)
    assert start_mismatches(planned("r", config="evaluation.toml"), matching_start(repository), repository) == []


def test_a_search_config_moved_with_the_same_contents_still_matches(tmp_path: Path) -> None:
    repository = write_repository(tmp_path)
    (repository / "moved.toml").write_text((repository / "search.toml").read_text(encoding="utf-8"), encoding="utf-8")
    (repository / "evaluation.toml").write_text(
        (repository / "evaluation.toml").read_text(encoding="utf-8").replace("search.toml", "moved.toml"),
        encoding="utf-8",
    )
    assert start_mismatches(planned("r", config="evaluation.toml"), matching_start(repository), repository) == []


@pytest.mark.parametrize(
    "run",
    [
        planned("r", config="evaluation.toml", policy_adapter="/adapters/v1"),
        planned("r", config="evaluation.toml", value="none"),
        planned("r", config="evaluation.toml", problems=200),
        planned("r", config="evaluation.toml", search_config="other.toml"),
    ],
    ids=["another policy", "another value model", "a pilot", "another search config"],
)
def test_a_run_recorded_with_other_settings_than_the_list_asks_is_a_mismatch(tmp_path: Path, run: PlannedRun) -> None:
    repository = write_repository(tmp_path)
    assert start_mismatches(run, matching_start(repository), repository)


def finished(root: Path, name: str, accepted: bool) -> PlannedRun:
    directory = root / "probe_evaluations" / f"probe_{name}"
    directory.mkdir(parents=True)
    environment = RunEnvironment("node", "lean", "vllm", "torch")
    record = ProbeRunRecord(start(identity=f"{name} identity"), environment, 2000, 700, 4, 0.002, (), 0.01, accepted)
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
