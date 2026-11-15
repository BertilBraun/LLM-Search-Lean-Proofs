from collections.abc import Sequence
from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem, Split
from lean_search.rl.evaluation import EvaluationProblem, SubmissionOrder, in_submission_order, pending_problems
from lean_search.rl.fixed_sets import HeldOutStatement, write_fixed_set
from lean_search.rl.fixed_targets import first_problems_by_stratum, probe_problems
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    SessionServing,
    read_sessions,
    start_session,
)
from lean_search.rl.study_configs import resolved_toml
from lean_search.search import Accounting, SearchResult, StopReason
from lean_search.search.records import from_json_object

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"


def problem(name: str, difficulty: float, stratum: str = "") -> EvaluationProblem:
    return EvaluationProblem(Problem(name, Split.VALID, "", "", "", ""), stratum, difficulty)


# Probe v2's file order: band after band, the shortest proofs first.
FILE_ORDER = [
    problem("s.short_a", 3.1, "0-499"),
    problem("s.short_b", 4.2, "0-499"),
    problem("s.middle_a", 12.0, "1000-1499"),
    problem("s.middle_b", 12.0, "1000-1499"),
    problem("s.long_a", 51.0, "4500+"),
    problem("s.long_b", 47.5, "4500+"),
]


def names(problems: Sequence[EvaluationProblem]) -> list[str]:
    return [item.problem.name for item in problems]


def test_the_longest_proofs_start_first() -> None:
    ordered = in_submission_order(FILE_ORDER, SubmissionOrder.LONGEST_PROOF_FIRST)
    assert names(ordered) == ["s.long_a", "s.long_b", "s.middle_a", "s.middle_b", "s.short_b", "s.short_a"]


def test_equally_long_proofs_start_in_file_order() -> None:
    tied = [problem("s.c", 12.0), problem("s.a", 12.0), problem("s.b", 12.0)]
    assert names(in_submission_order(tied, SubmissionOrder.LONGEST_PROOF_FIRST)) == ["s.c", "s.a", "s.b"]


def test_file_order_leaves_the_set_as_it_is() -> None:
    assert in_submission_order(FILE_ORDER, SubmissionOrder.FILE) == FILE_ORDER


def test_an_evaluation_config_without_the_setting_keeps_file_order() -> None:
    config = from_json_object(ProbeEvaluationConfig, {"loop_config": "loop.toml", "search_config": "search.toml"})
    assert config.submission_order == SubmissionOrder.FILE


@pytest.mark.parametrize(
    "path",
    [
        "probe_evaluation.toml",
        "gate_evaluation.toml",
        "step1/calibration_evaluation.toml",
        "step1/value_free_block_mean.toml",
        "step1/value_free_block_sum.toml",
        "step1/value_free_completion.toml",
    ],
)
def test_every_study_evaluation_starts_the_longest_proofs_first(path: str) -> None:
    config = from_json_object(ProbeEvaluationConfig, resolved_toml(FOLLOWUP / path, REPOSITORY))
    assert config.submission_order == SubmissionOrder.LONGEST_PROOF_FIRST


def test_order_changes_neither_which_statements_run_nor_how_many() -> None:
    ordered = in_submission_order(FILE_ORDER, SubmissionOrder.LONGEST_PROOF_FIRST)
    assert sorted(names(ordered)) == sorted(names(FILE_ORDER))


def finished(name: str) -> SearchResult:
    return SearchResult(name, False, StopReason.EXPANSION_BUDGET, None, (), (), Accounting(), None, 0, 1)


def test_a_resumed_run_starts_what_is_left_in_its_order() -> None:
    ordered = in_submission_order(FILE_ORDER, SubmissionOrder.LONGEST_PROOF_FIRST)
    done = [finished("s.long_a"), finished("s.short_a"), finished("s.middle_b")]
    assert [item.name for item in pending_problems(ordered, done)] == ["s.long_b", "s.middle_a", "s.short_b"]


def test_a_pilot_takes_the_statements_file_order_takes() -> None:
    pilot = first_problems_by_stratum(FILE_ORDER, 3)
    ordered = in_submission_order(pilot, SubmissionOrder.LONGEST_PROOF_FIRST)
    assert names(ordered) == ["s.long_a", "s.middle_a", "s.short_a"]


def statement(name: str, difficulty: float, stratum: str) -> HeldOutStatement:
    record = StatementRecord("pool", name, "", f"theorem {name} : True", "", "")
    return HeldOutStatement(record, difficulty, stratum)


def test_the_probe_set_carries_each_statements_recorded_difficulty(tmp_path: Path) -> None:
    path = tmp_path / "probe.jsonl"
    write_fixed_set(path, [statement("a", 3.5, "0-499"), statement("b", 47.0, "4500+")])
    assert [item.difficulty for item in probe_problems(path)] == [3.5, 47.0]


def test_a_session_records_the_order_its_searches_started_in(tmp_path: Path) -> None:
    checkpoint = ProbeCheckpoint("v0", 0, "/policy", "p" * 64, "/v0", "v" * 64, 0, 0, 0)
    start_session(
        tmp_path, checkpoint, tmp_path / "results.jsonl", SessionServing(), SubmissionOrder.LONGEST_PROOF_FIRST
    )
    assert read_sessions(tmp_path)[0].submission_order == SubmissionOrder.LONGEST_PROOF_FIRST


def test_a_session_from_before_the_setting_reads_as_file_order(tmp_path: Path) -> None:
    line = '{"session": "s", "results_before": 0, "policy_digest": "p", "value_digest": "v"}\n'
    (tmp_path / "sessions.jsonl").write_text(line, encoding="utf-8")
    assert read_sessions(tmp_path)[0].submission_order == SubmissionOrder.FILE
