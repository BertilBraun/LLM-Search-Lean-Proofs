import hashlib
import json
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest

from lean_search.data import Problem, Split
from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.rl.evaluation import EvaluationProblem
from lean_search.rl.fixed_targets import first_problems_by_stratum
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunRecord,
    ProbeRunStart,
    ProbeSession,
    RunEnvironment,
    SessionServing,
    distinct_start_orders,
    other_start_order,
    read_sessions,
    start_session,
)
from lean_search.rl.probe_run_list import (
    PlannedRun,
    missing_files,
    planned_run_config_sha256,
    recorded_mismatches,
    recorded_run,
    start_mismatches,
)
from lean_search.rl.study_configs import resolved_toml
from lean_search.rl.submission_order import (
    RecordedRun,
    StartOrder,
    SubmissionOrder,
    configured_start_order,
    expected_search_seconds_text,
    longest_expected_search_first,
    orders_note,
    read_expected_search_seconds,
    uncovered_statements,
)
from lean_search.search.records import from_json_object, to_json

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"
SEARCH = REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml"
STUDY_EVALUATIONS = sorted({*FOLLOWUP.glob("*_evaluation.toml"), *FOLLOWUP.glob("step1/*.toml")})
LONGEST_FIRST = SubmissionOrder.LONGEST_EXPECTED_SEARCH_FIRST


def problem(name: str, stratum: str = "") -> EvaluationProblem:
    return EvaluationProblem(Problem(name, Split.VALID, "", "", "", ""), stratum)


FILE_ORDER = [
    problem("s.short_a", "0-499"),
    problem("s.short_b", "0-499"),
    problem("s.middle_a", "1000-1499"),
    problem("s.middle_b", "1000-1499"),
    problem("s.long_a", "4500+"),
    problem("s.long_b", "4500+"),
]
SECONDS = {"s.short_a": 30.0, "s.short_b": 4000.0, "s.middle_a": 900.0, "s.middle_b": 12.0, "s.long_a": 350.0}


def names(problems: Sequence[EvaluationProblem]) -> list[str]:
    return [item.problem.name for item in problems]


def test_unknown_statements_start_first_then_the_longest_expected() -> None:
    ordered = longest_expected_search_first(FILE_ORDER, SECONDS)
    assert names(ordered) == ["s.long_b", "s.short_b", "s.middle_a", "s.long_a", "s.short_a", "s.middle_b"]


def test_equal_expected_seconds_start_in_file_order() -> None:
    tied = [problem("s.c"), problem("s.a"), problem("s.b")]
    assert names(longest_expected_search_first(tied, {"s.a": 5.0, "s.b": 5.0, "s.c": 5.0})) == ["s.c", "s.a", "s.b"]


def test_statements_without_expected_seconds_start_in_file_order() -> None:
    unknown = [problem("s.c"), problem("s.a"), problem("s.b")]
    assert names(longest_expected_search_first(unknown, {})) == ["s.c", "s.a", "s.b"]


HUNDRED = [problem(f"s.{index:03d}") for index in range(100)]


def test_one_percent_of_statements_without_expected_seconds_is_tolerated() -> None:
    seconds = {item.problem.name: 1.0 for item in HUNDRED[1:]}
    assert uncovered_statements(HUNDRED, seconds) == ["s.000"]


def test_more_than_one_percent_of_statements_without_expected_seconds_is_refused() -> None:
    seconds = {item.problem.name: 1.0 for item in HUNDRED[2:]}
    with pytest.raises(ValueError, match=r"lacks 2 of the run's 100 statements"):
        uncovered_statements(HUNDRED, seconds)


def test_the_order_changes_neither_which_statements_run_nor_how_many() -> None:
    assert sorted(names(longest_expected_search_first(FILE_ORDER, SECONDS))) == sorted(names(FILE_ORDER))


def test_a_pilot_takes_the_statements_file_order_takes_then_orders_them() -> None:
    pilot = longest_expected_search_first(first_problems_by_stratum(FILE_ORDER, 3), SECONDS)
    assert names(pilot) == ["s.middle_a", "s.long_a", "s.short_a"]


def test_an_evaluation_config_without_the_setting_keeps_file_order() -> None:
    config = from_json_object(ProbeEvaluationConfig, {"loop_config": "loop.toml", "search_config": "search.toml"})
    assert (config.submission_order, config.expected_search_seconds) == (SubmissionOrder.FILE, "")


def test_only_the_configs_named_ordered_turn_the_order_on() -> None:
    ordered = [path.name for path in STUDY_EVALUATIONS if "submission_order" in resolved_toml(path, REPOSITORY)]
    assert ordered == ["probe_evaluation_ordered.toml", "token_capped_evaluation_ordered.toml"]


@pytest.mark.parametrize(
    ("order", "expected_seconds"),
    [(LONGEST_FIRST, ""), (SubmissionOrder.FILE, "expected.tsv")],
    ids=["longest first without a file", "a file in file order"],
)
def test_an_order_and_file_that_do_not_go_together_are_refused(
    tmp_path: Path, order: SubmissionOrder, expected_seconds: str
) -> None:
    with pytest.raises(ValueError, match="expected_search_seconds"):
        configured_start_order(order, expected_seconds, tmp_path)


def test_the_configured_order_carries_the_files_digest(tmp_path: Path) -> None:
    (tmp_path / "expected.tsv").write_text("x", encoding="utf-8")
    order = configured_start_order(LONGEST_FIRST, "expected.tsv", tmp_path)
    assert order == StartOrder(LONGEST_FIRST, file_sha256(tmp_path / "expected.tsv"))


def recorded(name: str, wall_seconds: dict[str, float], probe_set_sha256: str = "probe digest") -> RecordedRun:
    return RecordedRun(name, f"{name} identity", probe_set_sha256, wall_seconds)


RUNS = [recorded("run1", {"s.b": 10.0, "s.a": 100.0}), recorded("run2", {"s.a": 300.0, "s.c": 7.0})]


def data_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("#")]


def test_each_statement_gets_the_mean_over_the_runs_that_searched_it_sorted_by_name() -> None:
    assert data_lines(expected_search_seconds_text(RUNS)) == ["s.a\t200.0\t2", "s.b\t10.0\t1", "s.c\t7.0\t1"]


def test_the_header_names_the_probe_set_and_each_run_with_its_identity() -> None:
    header = [line for line in expected_search_seconds_text(RUNS).splitlines() if line.startswith("#")]
    assert header[1:] == [
        "# probe_set_sha256\tprobe digest",
        "# run\trun1\trun1 identity\t2 statements",
        "# run\trun2\trun2 identity\t2 statements",
    ]


def test_the_header_names_the_runs_in_name_order_whatever_order_they_are_given_in() -> None:
    assert expected_search_seconds_text(RUNS[::-1]) == expected_search_seconds_text(RUNS)


def test_runs_of_different_probe_sets_are_refused() -> None:
    with pytest.raises(ValueError, match="different probe sets"):
        expected_search_seconds_text([RUNS[0], recorded("other", {"s.a": 1.0}, "other digest")])


def test_the_written_file_reads_back_as_the_means(tmp_path: Path) -> None:
    (tmp_path / "expected.tsv").write_text(expected_search_seconds_text(RUNS), encoding="utf-8")
    seconds = read_expected_search_seconds(tmp_path / "expected.tsv", "probe digest")
    assert seconds == {"s.a": 200.0, "s.b": 10.0, "s.c": 7.0}


def test_a_file_made_on_another_probe_set_is_refused(tmp_path: Path) -> None:
    (tmp_path / "expected.tsv").write_text(expected_search_seconds_text(RUNS), encoding="utf-8")
    with pytest.raises(ValueError, match="made on probe set probe digest"):
        read_expected_search_seconds(tmp_path / "expected.tsv", "the run's digest")


def write_run(directory: Path, wall_seconds: dict[str, float]) -> None:
    directory.mkdir(parents=True)
    checkpoint = ProbeCheckpoint("v0", 0, "/policy", "p" * 64, "/v0", "v" * 64, 0, 0, 0)
    start = ProbeRunStart("v0 identity", True, checkpoint, "s.toml", "sha", 112, 7200.0, 16, "probe.jsonl", "probe")
    (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
    lines = [
        json.dumps({"problem_name": name, "accounting": {"wall_seconds": seconds}})
        for name, seconds in wall_seconds.items()
    ]
    (directory / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_recorded_run_holds_each_statements_wall_seconds_and_the_runs_identity(tmp_path: Path) -> None:
    write_run(tmp_path / "probe_run1", {"s.a": 12.5, "s.b": 4000.0})
    assert recorded_run(tmp_path / "probe_run1") == RecordedRun(
        "probe_run1", "v0 identity", "probe", {"s.a": 12.5, "s.b": 4000.0}
    )


ORDERED = StartOrder(LONGEST_FIRST, "e" * 64)


def session(order: StartOrder) -> ProbeSession:
    return ProbeSession("s", 0, "p", "v", start_order=order)


def test_a_session_records_its_start_order(tmp_path: Path) -> None:
    checkpoint = ProbeCheckpoint("v0", 0, "/policy", "p" * 64, "/v0", "v" * 64, 0, 0, 0)
    start_session(tmp_path, checkpoint, tmp_path / "results.jsonl", SessionServing(), None, ORDERED)
    assert read_sessions(tmp_path)[0].start_order == ORDERED


def test_a_session_from_before_the_setting_reads_as_file_order(tmp_path: Path) -> None:
    line = '{"session": "s", "results_before": 0, "policy_digest": "p", "value_digest": "v"}\n'
    (tmp_path / "sessions.jsonl").write_text(line, encoding="utf-8")
    assert read_sessions(tmp_path)[0].start_order == StartOrder()


@pytest.mark.parametrize(
    "wanted",
    [ORDERED, StartOrder(LONGEST_FIRST, "f" * 64)],
    ids=["another order", "another expected-seconds file"],
)
def test_a_resume_in_another_order_than_the_first_sessions_is_named(wanted: StartOrder) -> None:
    assert other_start_order([session(StartOrder()), session(wanted)], wanted)


@pytest.mark.parametrize(
    "sessions", [[], [session(ORDERED), session(StartOrder())]], ids=["no session yet", "the first session's order"]
)
def test_a_session_in_the_runs_first_order_is_not_refused(sessions: list[ProbeSession]) -> None:
    assert other_start_order(sessions, ORDERED) == ""


def test_the_run_record_holds_each_order_its_sessions_started_in_once() -> None:
    sessions = [session(StartOrder()), session(StartOrder()), session(ORDERED), session(StartOrder())]
    assert distinct_start_orders(sessions) == (StartOrder(), ORDERED)


def test_runs_in_one_order_get_no_note() -> None:
    assert orders_note([(ORDERED,), (ORDERED,)]) == ""


def test_runs_in_different_orders_get_the_note() -> None:
    assert orders_note([(StartOrder(),), (ORDERED,)]).startswith("orders differ: load pattern differs")


def write_repository(root: Path) -> Path:
    """An evaluation config ordered by expected.tsv over the study's search config and follow-up base."""
    (root / "search.toml").write_text(SEARCH.read_text(encoding="utf-8"), encoding="utf-8")
    evaluation = (
        'loop_config = "loop.toml"\nsearch_config = "search.toml"\nprobe_set = "probe.jsonl"\n'
        'submission_order = "longest_expected_search_first"\nexpected_search_seconds = "expected.tsv"\n'
        "[probe]\nmax_expansions = 16\nconcurrency = 112\nmax_wall_seconds = 7200.0\n"
    )
    (root / "evaluation.toml").write_text(evaluation, encoding="utf-8")
    (root / "loop.toml").write_text((FOLLOWUP / "base.toml").read_text(encoding="utf-8"), encoding="utf-8")
    return root


def order_mismatches(root: Path, recorded_order: StartOrder) -> list[str]:
    """start_mismatches' start-order lines for a run recorded with `recorded_order`."""
    repository = write_repository(root)
    (repository / "expected.tsv").write_text("x", encoding="utf-8")
    run = PlannedRun("r", "v0", 0, "/adapters/v0", "v0", config="evaluation.toml")
    checkpoint = ProbeCheckpoint("v0", 0, "/adapters/v0", "p", "/adapters/value_v0", "v", 0, 0, 0)
    start = ProbeRunStart("r", False, checkpoint, "search.toml", "sha", 112, 7200.0, 16, "probe.jsonl", "sha")
    return [line for line in start_mismatches(run, start, repository, recorded_order) if "start order" in line]


def test_a_run_started_in_file_order_mismatches_a_list_asking_for_another(tmp_path: Path) -> None:
    assert order_mismatches(tmp_path, StartOrder())


def test_a_run_started_in_the_order_the_list_asks_for_matches(tmp_path: Path) -> None:
    assert order_mismatches(tmp_path, StartOrder(LONGEST_FIRST, hashlib.sha256(b"x").hexdigest())) == []


def file_order_run(root: Path, finished: bool) -> Path:
    """A run of the ordered list's "r" recorded with every setting the list asks for, its session in file order."""
    repository = write_repository(root)
    (repository / "expected.tsv").write_text("x", encoding="utf-8")
    run = PlannedRun("r", "v0", 0, "/adapters/v0", "v0", config="evaluation.toml")
    value_adapter = tomllib.loads((FOLLOWUP / "base.toml").read_text(encoding="utf-8"))["initial"]["value_adapter"]
    checkpoint = ProbeCheckpoint("v0", 0, str(Path("/adapters/v0").absolute()), "p", value_adapter, "v", 0, 0, 0)
    digest = planned_run_config_sha256(run, repository)
    start = ProbeRunStart("r", False, checkpoint, "search.toml", digest, 112, 7200.0, 16, "probe.jsonl", "probe")
    directory = root / "probe_r"
    directory.mkdir()
    (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
    start_session(directory, checkpoint, directory / "results.jsonl", SessionServing())
    if finished:
        environment = RunEnvironment("node", "lean", "vllm", "torch")
        record = ProbeRunRecord(start, environment, 2000, 700, 4, 0.002, (), 0.01, True)
        (directory / "run.json").write_text(to_json(record), encoding="utf-8")
    return directory


def test_a_finished_run_in_another_order_does_not_stop_the_list(tmp_path: Path) -> None:
    directory = file_order_run(tmp_path, finished=True)
    run = PlannedRun("r", "v0", 0, "/adapters/v0", "v0", config="evaluation.toml")
    assert recorded_mismatches(run, directory, tmp_path) == []


def test_an_unfinished_run_in_another_order_still_refuses_to_resume(tmp_path: Path) -> None:
    directory = file_order_run(tmp_path, finished=False)
    run = PlannedRun("r", "v0", 0, "/adapters/v0", "v0", config="evaluation.toml")
    assert [line.split(" 'file'")[0] for line in recorded_mismatches(run, directory, tmp_path)] == [
        "r: its record has start order"
    ]


def test_an_expected_seconds_file_of_another_probe_set_is_reported(tmp_path: Path) -> None:
    repository = write_repository(tmp_path)
    (tmp_path / "probe.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "expected.tsv").write_text(expected_search_seconds_text(RUNS), encoding="utf-8")
    run = PlannedRun("r", "v0", 0, str(tmp_path), "v0", config="evaluation.toml")
    assert [line.split(" was made")[0] for line in missing_files(run, repository, tmp_path)] == [
        f"r: {tmp_path / 'expected.tsv'}"
    ]


def test_a_missing_expected_seconds_file_is_reported(tmp_path: Path) -> None:
    repository = write_repository(tmp_path)
    (tmp_path / "probe.jsonl").write_text("", encoding="utf-8")
    run = PlannedRun("r", "v0", 0, str(tmp_path), "v0", config="evaluation.toml")
    assert missing_files(run, repository, tmp_path) == [f"r: no expected search seconds at {tmp_path / 'expected.tsv'}"]
