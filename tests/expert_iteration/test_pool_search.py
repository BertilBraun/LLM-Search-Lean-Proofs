from pathlib import Path

from lean_search.data import Problem, Split
from lean_search.expert_iteration.pool_search import (
    Invocation,
    SourceSolveRate,
    common_headers,
    model_throughput,
    read_completed_results,
    source_solve_rates,
    statements_per_hour,
)
from lean_search.policy.expander import PolicyStatistics
from lean_search.search import Accounting, SearchResult, StopReason
from lean_search.search.records import to_json


def result(name: str, stop_reason: StopReason = StopReason.EXPANSION_BUDGET, proved: bool = False) -> SearchResult:
    return SearchResult(name, proved, stop_reason, None, (), (), Accounting(), None, 0, 0)


def test_a_line_cut_short_is_dropped_from_the_results(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text(to_json(result("a")) + "\n" + to_json(result("b"))[:40], encoding="utf-8")
    assert [completed.problem_name for completed in read_completed_results(path)] == ["a"]


def test_the_results_file_is_rewritten_without_the_cut_line(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text(to_json(result("a")) + "\n" + to_json(result("b"))[:40], encoding="utf-8")
    read_completed_results(path)
    assert path.read_text(encoding="utf-8") == to_json(result("a")) + "\n"


def test_samples_per_second_pool_the_invocations(tmp_path: Path) -> None:
    paths = []
    for index, requests in enumerate((3, 5)):
        path = tmp_path / f"policy_{index}.json"
        statistics = PolicyStatistics(requests=requests, samples=16 * requests, window_seconds=2.0 * requests)
        path.write_text(to_json(statistics), encoding="utf-8")
        paths.append(path)
    assert model_throughput(paths, []).samples_per_second == 8.0


def test_solve_rates_by_source_exclude_load_failures() -> None:
    results = [
        result("lean_workbook.1", StopReason.PROVED, proved=True),
        result("lean_workbook.2"),
        result("lean_workbook.3", StopReason.START_FAILED),
    ]
    assert source_solve_rates(results) == (SourceSolveRate("lean_workbook", 3, 1, 1, 0.5),)


def problem(name: str, header: str) -> Problem:
    return Problem(name, Split.VALID, header, "theorem t : True := by", "", "")


def test_only_common_headers_are_preloaded() -> None:
    problems = [problem(f"a{index}", "import Mathlib") for index in range(99)] + [problem("b", "import Mathlib\ndef f")]
    assert common_headers(problems, minimum_share=0.05) == ["import Mathlib"]


def test_statements_per_hour_count_only_finished_invocations() -> None:
    invocations = [Invocation(0, "", "", False, 100, 100, 1800.0), Invocation(1, "", "", False, 50, 50, 1800.0)]
    assert statements_per_hour(invocations) == 150.0
