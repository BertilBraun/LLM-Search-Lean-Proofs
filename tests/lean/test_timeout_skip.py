from pathlib import Path

import pytest
from fake_repl_project import HEADER, STATEMENT, fake_repl_project, needs_linux

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl, LeanTimeout, ProofState
from lean_search.lean.memory import SearchMemory
from lean_search.rl.phase_metrics import FailureTier, failure_tier
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    DepthPlusGoals,
    Failure,
    FailureKind,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_theorem,
)
from lean_search.search.graph_labels import EdgeKind, failure_edge_kind
from lean_search.search.search import TimeoutSkipConfig

ROOT = ProofState(HEADER, STATEMENT, (), ("⊢ True",), repl_proof_state=1, session=7)
OTHER = ProofState(HEADER, STATEMENT, ("step",), ("⊢ True",), repl_proof_state=2, session=7, tactic_heartbeats=(5,))
WALL_CLOCK = LeanTimeout("The tactic exceeded the wall-clock limit.", wall_clock=True)


def memory_after(timeouts: int, max_wall_clock_timeouts: int | None = 2) -> SearchMemory:
    memory = SearchMemory(cache_results=False, max_wall_clock_timeouts=max_wall_clock_timeouts)
    for _ in range(timeouts):
        memory.record(ROOT, "nlinarith", 5, WALL_CLOCK, 60.0)
    return memory


def test_a_text_still_runs_after_fewer_wall_clock_stops_than_the_limit() -> None:
    assert memory_after(1).skipped("nlinarith") is None


def test_a_text_is_skipped_at_any_state_after_the_limit() -> None:
    skipped = memory_after(2).skipped("nlinarith")
    assert skipped is not None and (skipped.wall_clock, skipped.skipped) == (True, True)


def test_other_texts_still_run() -> None:
    assert memory_after(2).skipped("nlinarith [sq_nonneg x]") is None


def test_without_a_limit_nothing_is_skipped() -> None:
    assert memory_after(5, max_wall_clock_timeouts=None).skipped("nlinarith") is None


def test_a_skip_does_not_count_as_another_wall_clock_stop() -> None:
    memory = memory_after(2, max_wall_clock_timeouts=3)
    skipped = LeanTimeout("Not run", wall_clock=True, skipped=True)
    memory.record(OTHER, "nlinarith", 5, skipped, 0.0)
    assert memory.skipped("nlinarith") is None


def test_a_skipped_tactic_is_a_failure_of_its_own_kind() -> None:
    assert Failure.from_lean(LeanTimeout("Not run", wall_clock=True, skipped=True)).kind == FailureKind.SKIPPED_TIMEOUT


def test_a_skipped_tactic_is_labelled_like_a_wall_clock_timeout() -> None:
    assert failure_edge_kind(FailureKind.SKIPPED_TIMEOUT) == EdgeKind.WALL_CLOCK_TIMEOUT


def test_a_skipped_tactic_is_a_negative_label_not_an_infrastructure_failure() -> None:
    assert Failure(FailureKind.SKIPPED_TIMEOUT, "Not run").is_negative_label


def test_a_skipped_tactic_counts_as_a_timeout_in_the_phase_metrics() -> None:
    assert failure_tier(Failure(FailureKind.SKIPPED_TIMEOUT, "Not run")) == FailureTier.TIMEOUT


PROBLEM = Problem("t", Split.VALID, HEADER, STATEMENT, "", "")


class Blocks:
    def __init__(self, *texts: str) -> None:
        self.texts = texts

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(tuple(Candidate(text, StepSource.POLICY, log_probability=-1.0) for text in self.texts))


async def searched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool) -> tuple[CompletedSearch, int]:
    """Three blocks ending in `hang`; the third is skipped after two wall-clock stops when the rule is on."""
    project = fake_repl_project(tmp_path, monkeypatch, timeout_seconds=0.5)
    config = SearchConfig(
        max_expansions=1,
        check_identifiers=False,
        name_inaccessible_hypotheses=False,
        tactic_timeout_seconds=0.5,
        timeout_skip=TimeoutSkipConfig(enabled=enabled),
    )
    async with LeanRepl(project.config) as repl:
        completed = await search_theorem(
            PROBLEM, repl, Blocks("hang", "step\nhang", "other\nhang"), DepthPlusGoals(), config
        )
    return completed, project.requests("tactic").count("hang")


@needs_linux
async def test_the_search_skips_a_text_after_two_wall_clock_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, hangs = await searched(tmp_path, monkeypatch, enabled=True)
    assert hangs == 2


@needs_linux
async def test_a_skipped_edge_keeps_its_valid_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    completed, _ = await searched(tmp_path, monkeypatch, enabled=True)
    assert completed.tree is not None
    edge = completed.tree.edges[2]
    assert edge.failure is not None
    assert (edge.applied_tactics, edge.failure.kind) == (1, FailureKind.SKIPPED_TIMEOUT)


@needs_linux
async def test_the_search_counts_skips_apart_from_timeouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    completed, _ = await searched(tmp_path, monkeypatch, enabled=True)
    accounting = completed.result.accounting
    assert (accounting.timeouts, accounting.skipped_timeouts) == (2, 1)


@needs_linux
async def test_without_the_rule_every_hang_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, hangs = await searched(tmp_path, monkeypatch, enabled=False)
    assert hangs == 3
