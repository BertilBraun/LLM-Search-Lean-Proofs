import tomllib
from pathlib import Path

import pytest

from lean_search.rl.probe_run_list import read_run_list, run_refusals
from lean_search.rl.study_configs import resolved_toml

REPOSITORY = Path(__file__).resolve().parents[2]
FOLLOWUP = REPOSITORY / "experiments/configs/grpo/followup"
MINIF2F = FOLLOWUP / "minif2f"
EVALUATION = MINIF2F / "minif2f_evaluation.toml"
RUN_LISTS = sorted(MINIF2F.glob("runs_*.toml"))


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


STUDY_CONCURRENCY = toml(FOLLOWUP / "probe_evaluation.toml")["probe"]["concurrency"]


@pytest.mark.parametrize("path", RUN_LISTS, ids=lambda path: path.name)
def test_every_minif2f_run_list_passes_the_probe_runs_check(path: Path) -> None:
    runs = read_run_list(path).runs
    assert [refusal for run in runs for refusal in run_refusals(run, REPOSITORY, STUDY_CONCURRENCY)] == []


@pytest.mark.parametrize("path", RUN_LISTS, ids=lambda path: path.name)
def test_every_minif2f_run_searches_on_the_minif2f_evaluation(path: Path) -> None:
    assert {run.config for run in read_run_list(path).runs} == {EVALUATION.relative_to(REPOSITORY).as_posix()}


def test_the_minif2f_evaluation_differs_from_the_probe_only_in_set_output_budget_and_stop_share() -> None:
    probe = resolved_toml(FOLLOWUP / "probe_evaluation.toml", REPOSITORY)
    minif2f = resolved_toml(EVALUATION, REPOSITORY)
    expected = {
        **probe,
        "probe_set": "grpo/fixed_sets/minif2f_valid.jsonl",
        "output": "minif2f_evaluations",
        "max_wall_clock_stop_share": 0.05,
        "probe": {**probe["probe"], "max_expansions": 64, "max_wall_seconds": 3600.0},
    }
    assert minif2f == expected


def test_the_minif2f_evaluation_matches_the_loops_minif2f_budget() -> None:
    loop_target = toml(FOLLOWUP / "base.toml")["evaluation"]["minif2f"]
    assert resolved_toml(EVALUATION, REPOSITORY)["probe"]["max_expansions"] == loop_target["max_expansions"]
