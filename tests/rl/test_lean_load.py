import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.rl.fixed_sets import HeldOutStatement, write_fixed_set
from lean_search.rl.lean_load import LeanLoad, lean_loads
from lean_search.search import Accounting, SearchResult, StopReason
from lean_search.search.records import to_json
from lean_search.search.search import POLICY_STEP_KEY, StepStatistics

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]


def result(
    name: str, policy_timeouts: int = 0, automation_timeouts: int = 0, repl_failures: int = 0, attempts: int = 10
) -> SearchResult:
    statistics = (
        StepStatistics(
            POLICY_STEP_KEY, attempts=attempts, lean_seconds=2.0 * attempts, wall_clock_timeouts=policy_timeouts
        ),
        StepStatistics("nlinarith", attempts=3, lean_seconds=90.0, wall_clock_timeouts=automation_timeouts),
    )
    accounting = Accounting(repl_failures=repl_failures)
    return SearchResult(
        name, False, StopReason.EXPANSION_BUDGET, None, (), (), accounting, None, 0, 1, None, statistics
    )


RESULTS = [
    result("s.short", policy_timeouts=1),
    result("s.long_a", policy_timeouts=2, automation_timeouts=1, repl_failures=1),
    result("s.long_b", attempts=30),
]
STRATA = {"s.short": "0-499", "s.long_a": "4500+", "s.long_b": "4500+"}


def test_the_total_counts_every_tactic_wall_clock_timeout() -> None:
    assert lean_loads(RESULTS, STRATA)[0].wall_clock_timeouts == 4


def test_a_stratum_counts_its_own_statements_only() -> None:
    assert lean_loads(RESULTS, STRATA)[2] == LeanLoad("4500+", 2, 3, 1, 1, 40, 80.0, 2.0)


def test_the_strata_follow_the_total_low_band_first() -> None:
    assert [load.stratum for load in lean_loads(RESULTS, STRATA)] == ["all", "0-499", "4500+"]


def test_a_stratum_without_policy_attempts_has_no_lean_seconds_per_attempt() -> None:
    assert lean_loads([result("s.short", attempts=0)], STRATA)[1].lean_seconds_per_policy_attempt is None


def statement(name: str, stratum: str) -> HeldOutStatement:
    return HeldOutStatement(StatementRecord("s", name, "", f"theorem {name} : True", "", ""), 1.0, stratum)


@pytest.fixture
def run_in_progress(tmp_path: Path) -> Path:
    """A probe run directory with two results and no run.json, its probe set under a data directory."""
    write_fixed_set(tmp_path / "data" / "probe.jsonl", [statement("short", "0-499"), statement("long_a", "4500+")])
    directory = tmp_path / "runs" / "probe_evaluations" / "probe_anchor"
    directory.mkdir(parents=True)
    (directory / "checkpoint.json").write_text(json.dumps({"probe_set": "probe.jsonl"}), encoding="utf-8")
    lines = [to_json(item) + "\n" for item in RESULTS[:2]]
    (directory / "results.jsonl").write_text("".join(lines), encoding="utf-8")
    return tmp_path


def test_the_load_of_a_run_in_progress_is_read_from_its_results(run_in_progress: Path) -> None:
    settings = {"LEAN_SEARCH_DATA": str(run_in_progress / "data"), "LEAN_SEARCH_RUNS": str(run_in_progress / "runs")}
    output = subprocess.run(  # noqa: S603
        [sys.executable, str(REPOSITORY_DIRECTORY / "experiments" / "probe_compare.py"), "load", "anchor"],
        env=os.environ | settings,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "| 4500+ | 3 (1) / 1 / 2.00 |" in output
