import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem, Split
from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.pool import PrefilterOutcome, pool_problem, prefilter_outcome
from lean_search.expert_iteration.pool_search import PoolRunPaths, TreeSelection, read_completed_results, search_pool
from lean_search.expert_iteration.preferences import node_pairs
from lean_search.expert_iteration.proofs import found_proof, policy_sft_examples
from lean_search.expert_iteration.value_data import round_tree_examples
from lean_search.lean import LeanRepl, LeanReplConfig
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.search import (
    Candidate,
    CandidateBatches,
    DepthPlusGoals,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    TreeRecord,
    search_theorem,
    tree_record,
)
from lean_search.search.config import parse_run_config
from lean_search.value.labels import LabelKind, TreeLabelConfig

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
STATEMENTS = (
    StatementRecord("lean_workbook", "solved", HEADER, "theorem solved : (2 : ℕ) + 2 = 4 := by", "", ""),
    StatementRecord("lean_workbook", "false", HEADER, "theorem false_statement : (1 : ℕ) = 2 := by", "", ""),
    StatementRecord("lean_workbook", "broken", HEADER, 'theorem broken : (1 : ℕ) = "a" := by', "", ""),
)
PREFILTER_CONFIG = """
[lean]
pool_size = 2
concurrency = 2

[search]
max_expansions = 2
max_wall_seconds = 60.0

[automation]
tactics = ["norm_num", "simp"]
"""
UNKNOWN_LEMMA = "exact lean_search_no_such_lemma"

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


class FixedPolicy:
    """Proposes the same blocks at every node: one makes progress, one is an error, one closes the goal."""

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield [
            Candidate("intro n", StepSource.POLICY, log_probability=-0.5),
            Candidate(UNKNOWN_LEMMA, StepSource.POLICY, log_probability=-1.0),
            Candidate("simp", StepSource.POLICY, log_probability=-2.0),
        ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def prefilter_run(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[PoolRunPaths]:
    paths = PoolRunPaths(tmp_path_factory.mktemp("prefilter"))
    problems = [pool_problem(statement) for statement in STATEMENTS]
    await search_pool(problems, parse_run_config(PREFILTER_CONFIG), paths, TreeSelection.SOLVED, 0, print)
    yield paths


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def policy_tree() -> AsyncIterator[TreeRecord]:
    statement = "theorem add_zero_all : ∀ n : ℕ, n + 0 = n := by"
    problem = Problem("lean_workbook.add_zero_all", Split.VALID, HEADER, statement, "", "")
    async with LeanRepl(LeanReplConfig()) as repl:
        completed = await search_theorem(problem, repl, FixedPolicy(), DepthPlusGoals(), SearchConfig(max_expansions=4))
    assert completed.tree is not None
    yield tree_record(completed.tree, statement, completed.result)


async def test_the_prefilter_sorts_statements_by_outcome(prefilter_run: PoolRunPaths) -> None:
    outcomes = {
        result.problem_name: prefilter_outcome(result) for result in read_completed_results(prefilter_run.results)
    }
    assert outcomes == {
        "lean_workbook.solved": PrefilterOutcome.AUTOMATION_SOLVED,
        "lean_workbook.false": PrefilterOutcome.UNSOLVED,
        "lean_workbook.broken": PrefilterOutcome.LOAD_FAILED,
    }


async def test_the_prefilter_keeps_only_trees_of_solved_statements(prefilter_run: PoolRunPaths) -> None:
    assert [path.name for path in Path(prefilter_run.trees).glob("*.json.gz")] == ["lean_workbook.solved.json.gz"]


async def test_the_lean_error_sibling_is_rejected_against_the_proof_step(policy_tree: TreeRecord) -> None:
    proof = found_proof("round_0", policy_tree)
    assert proof is not None
    pairs = node_pairs(policy_tree, proof, PreferenceConfig())
    assert [(pair.chosen, pair.rejected, pair.rejection) for node in pairs for pair in node.pairs] == [
        ("simp", UNKNOWN_LEMMA, "error")
    ]


async def test_the_proof_step_becomes_an_sft_example(policy_tree: TreeRecord) -> None:
    proof = found_proof("round_0", policy_tree)
    assert proof is not None
    assert [(example.goals, example.tactic_block) for example in policy_sft_examples([proof], True)] == [
        (("⊢ ∀ (n : ℕ), n + 0 = n",), "simp")
    ]


async def test_the_open_child_gives_no_value_label(policy_tree: TreeRecord) -> None:
    labels = round_tree_examples(policy_tree, TreeLabelConfig())
    assert [(label.depth, label.kind, label.steps) for label in labels] == [(0, LabelKind.EXACT, 1)]
