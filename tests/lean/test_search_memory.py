"""The search's use of its tactic memory, over fake REPL processes."""

from pathlib import Path

import pytest
from fake_repl_project import HEADER, STATEMENT, fake_repl_project, needs_linux

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    DepthPlusGoals,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_theorem,
)

PROBLEM = Problem("t", Split.VALID, HEADER, STATEMENT, "", "")
pytestmark = needs_linux


class Blocks:
    def __init__(self, *texts: str) -> None:
        self.texts = texts

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(tuple(Candidate(text, StepSource.POLICY, log_probability=-1.0) for text in self.texts))


async def searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: SearchConfig, *texts: str
) -> tuple[CompletedSearch, list[str]]:
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=0.5)
    async with LeanRepl(project.config) as repl:
        completed = await search_theorem(PROBLEM, repl, Blocks(*texts), DepthPlusGoals(), config)
    return completed, project.requests("tactic")


def search_config(**changes: object) -> SearchConfig:
    return SearchConfig(max_expansions=1, check_identifiers=False, name_inaccessible_hypotheses=False, **changes)


async def test_the_search_counts_the_tactics_its_cache_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed, _ = await searched(tmp_path, monkeypatch, search_config(result_cache=True), "step\nfail", "step\ndone")
    assert completed.result.accounting.cached_tactics == 1


async def test_an_edge_records_the_tactics_the_cache_answered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    completed, _ = await searched(tmp_path, monkeypatch, search_config(result_cache=True), "step\nfail", "step\ndone")
    assert completed.tree is not None
    assert [edge.cached_tactics for edge in completed.tree.edges] == [0, 1]


async def test_a_proof_through_a_cached_tactic_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    completed, _ = await searched(tmp_path, monkeypatch, search_config(result_cache=True), "step\nfail", "step\ndone")
    assert completed.result.proof == "step\ndone"


async def test_without_the_cache_every_tactic_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, requests = await searched(tmp_path, monkeypatch, search_config(), "step\nfail", "step\ndone")
    assert requests.count("step") == 2
