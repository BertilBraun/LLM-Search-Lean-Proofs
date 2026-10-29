import dataclasses
from pathlib import Path

import pytest
from loop_fakes import solved_tree

from lean_search.data import Problem, Split
from lean_search.data_rewrite.naming import NameChange, NameSource
from lean_search.data_rewrite.statement_renaming import StatementRenaming
from lean_search.monitoring.families import BandOutcome
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary, StratumOutcome, fixed_targets_record
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.renaming import RenamedStatement, StatementRenamings, read_renamings, write_renamings
from lean_search.rl.search_models import evaluation_run_config, run_config_text
from lean_search.rl.tree_store import TreeStore
from lean_search.search import Accounting, RunConfig, SearchResult, StopReason, tree_record
from lean_search.search.config import parse_run_config

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
TEMPLATE = REPOSITORY_DIRECTORY / "experiments/configs/grpo/search/visible_student_v2.toml"
PROBLEM = Problem("test.t0", Split.VALID, "", "theorem t0 (x : ℕ) (h₀ : x = 1) : x = 1 := by", "", "")
RENAMED = "theorem t0 (x : ℕ) (hx_eq_one : x = 1) : x = 1 := by"


def template() -> RunConfig:
    return parse_run_config(TEMPLATE.read_text(encoding="utf-8"))


def test_a_run_config_reads_back_from_its_text() -> None:
    assert parse_run_config(run_config_text(template())) == template()


@pytest.mark.parametrize("part", ["harvest", "exploration"])
def test_evaluations_search_without_harvesting_or_exploration(part: str) -> None:
    config = evaluation_run_config(template(), EvaluationTarget(16, 600.0, 8))
    assert not getattr(config.search, part).enabled


def test_evaluations_search_at_their_budget() -> None:
    assert evaluation_run_config(template(), EvaluationTarget(16, 600.0, 8)).search.max_expansions == 16


def test_probe_record_by_stratum() -> None:
    summary = EvaluationSummary(
        EvaluationKind.PROBE,
        "probe_v0001",
        1,
        0,
        6,
        3,
        (StratumOutcome("easy", 3, 2), StratumOutcome("hard", 3, 1)),
        16,
        40,
        1000,
        10.0,
        60.0,
        "",
        "",
    )
    assert fixed_targets_record(summary).probe_by_difficulty == {"easy": BandOutcome(3, 2), "hard": BandOutcome(3, 1)}


def test_held_out_states_record_per_sample_success() -> None:
    summary = EvaluationSummary(
        EvaluationKind.HELD_OUT_STATES, "states_v0001", 1, 0, 512, 1024, (), 1, 512, 0, 0.0, 0.0, "", "", samples=4096
    )
    assert fixed_targets_record(summary).held_out_success == 0.25


def test_tree_store_reads_back_its_index(tmp_path: Path) -> None:
    result = SearchResult(PROBLEM.name, True, StopReason.PROVED, None, (), (), Accounting(proofs=1), None, 0, 1)
    record = tree_record(solved_tree(PROBLEM), PROBLEM.formal_statement, result)
    store = TreeStore(tmp_path)
    store.add(record, 2, 1, 1.5)
    assert TreeStore(tmp_path).phase_entries(2) == store.entries


def renamings() -> StatementRenamings:
    change = NameChange("h₀", "hx_eq_one", NameSource.RULES)
    return StatementRenamings({PROBLEM.name: StatementRenaming(PROBLEM.formal_statement, RENAMED, (change,))})


def test_a_renamed_problem_searches_the_renamed_statement() -> None:
    renamed, _ = renamings().renamed(PROBLEM)
    assert renamed.formal_statement == RENAMED


def test_a_problem_without_a_renaming_is_counted() -> None:
    source = renamings()
    source.renamed(dataclasses.replace(PROBLEM, name="test.other"))
    assert source.missing == 1


def test_renamings_read_back(tmp_path: Path) -> None:
    items = [RenamedStatement(name, renaming) for name, renaming in renamings().by_name.items()]
    write_renamings(tmp_path / "renamings.jsonl", items)
    assert read_renamings([tmp_path / "renamings.jsonl"]).by_name == renamings().by_name
