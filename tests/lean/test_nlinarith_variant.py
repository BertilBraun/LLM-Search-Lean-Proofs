"""The bounded nlinarith switch: which texts run as the variant, the base environment, what is recorded and what
verification checks. The process tests use the fake REPL; the last ones need Lean (they run on the node)."""

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from fake_repl_project import HEADER, STATEMENT, FakeReplProject, fake_repl_project, needs_linux

from lean_search.data import Problem, Split
from lean_search.lean import LeanError, LeanRepl, LeanReplConfig, ProofState
from lean_search.lean.memory import SearchMemory
from lean_search.lean.nlinarith import VARIANT_DEFINITIONS, NlinarithVariant, variant_tactic
from lean_search.lean.repl import BASE_ENVIRONMENT_DEFINITIONS, PROJECT_DIRECTORY, REPL_BINARY
from lean_search.lean.text import executed_proof, theorem_with_proof
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.phase_metrics import PlainChecks, plain_checks
from lean_search.rl.probe_evaluation import run_config_sha256
from lean_search.rl.search_models import evaluation_run_config, run_config_text
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    DepthPlusGoals,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_theorem,
)
from lean_search.search.config import parse_run_config, search_repl_config
from lean_search.search.records import to_json, tree_record
from lean_search.search.search import HarvestConfig
from lean_search.search.summary import plain_check_label

DEGREE = NlinarithVariant.DEGREE
HEARTBEATS = 200_000


@pytest.mark.parametrize(
    ("written", "executed"),
    [
        ("nlinarith", "lean_search_nlinarith degree"),
        (
            "nlinarith [sq_nonneg (a - b), mul_pos ha hb]",
            "lean_search_nlinarith degree [sq_nonneg (a - b), mul_pos ha hb]",
        ),
        (
            "nlinarith [sq_nonneg (a - b),\n  sq_nonneg (a + b)]",
            "lean_search_nlinarith degree [sq_nonneg (a - b),\n  sq_nonneg (a + b)]",
        ),
        ("constructor <;> nlinarith [h]", "constructor <;> lean_search_nlinarith degree [h]"),
        ("have h : 0 < x := by nlinarith [hx]", "have h : 0 < x := by lean_search_nlinarith degree [hx]"),
        ("first | linarith | nlinarith", "first | linarith | lean_search_nlinarith degree"),
    ],
    ids=["bare", "hints", "multi-line hints", "after <;>", "inside a term", "inside first"],
)
def test_a_plain_nlinarith_runs_as_the_variant(written: str, executed: str) -> None:
    assert variant_tactic(written, DEGREE) == executed


@pytest.mark.parametrize(
    "written",
    [
        "nlinarith (config := { splitNe := true }) [h]",
        "nlinarith (config := .default)",
        "nlinarith only [h, h']",
        "nlinarith! [h]",
        "linarith [h]",
        "exact Linarith.nlinarithExtras",
        "nlinarith_helper h",
    ],
    ids=["config with hints", "config", "only", "bang", "linarith", "a name containing it", "another name"],
)
def test_other_texts_run_as_written(written: str) -> None:
    assert variant_tactic(written, DEGREE) == written


def test_a_search_config_turns_the_variant_on() -> None:
    config = parse_run_config('[search]\nnlinarith_variant = "degree"')
    assert search_repl_config(config).nlinarith_variant == DEGREE


def test_an_unknown_variant_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_run_config('[search]\nnlinarith_variant = "quadratic"')


def test_a_config_without_the_variant_does_not_write_it() -> None:
    assert "nlinarith_variant" not in run_config_text(parse_run_config(""))


def test_the_variant_changes_the_digest() -> None:
    on = parse_run_config('[search]\nnlinarith_variant = "degree"')
    assert run_config_sha256(on) != run_config_sha256(parse_run_config(""))


def test_an_evaluation_runs_plain_nlinarith() -> None:
    on = parse_run_config('[search]\nnlinarith_variant = "degree"')
    assert evaluation_run_config(on, EvaluationTarget(16, 3600.0, 56)).search.nlinarith_variant is None


def variant_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: NlinarithVariant | None
) -> FakeReplProject:
    project = fake_repl_project(tmp_path, monkeypatch)
    return dataclasses.replace(project, config=dataclasses.replace(project.config, nlinarith_variant=variant))


async def proved(project: FakeReplProject, block: str, memory: SearchMemory | None = None) -> ProofState:
    async with LeanRepl(project.config) as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        result = await repl.apply_block(start.outcome, block, HEARTBEATS, memory=memory)
        if memory is not None:
            await repl.apply_block(start.outcome, block, HEARTBEATS, memory=memory)
        await repl.verify_state(result.state)
    return result.state


@needs_linux
async def test_the_variant_adds_its_definitions_to_the_base_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    await proved(project, "nlinarith [h]\ndone")
    assert BASE_ENVIRONMENT_DEFINITIONS + VARIANT_DEFINITIONS in project.requests("cmd")


@needs_linux
async def test_without_the_variant_the_base_environment_is_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = variant_project(tmp_path, monkeypatch, None)
    await proved(project, "nlinarith [h]\ndone")
    assert [command for command in project.requests("cmd") if "leanSearchDegree" in command] == []


@needs_linux
async def test_lean_runs_the_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    await proved(project, "nlinarith [h]\ndone")
    assert "lean_search_nlinarith degree [h]" in project.requests("tactic")


@needs_linux
async def test_the_state_records_the_written_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = await proved(variant_project(tmp_path, monkeypatch, DEGREE), "nlinarith [h]\ndone")
    assert state.tactics == ("nlinarith [h]", "done")


@needs_linux
async def test_verification_checks_the_executed_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    await proved(project, "nlinarith [h]\ndone")
    executed = executed_proof(("lean_search_nlinarith degree [h]", "done"), (HEARTBEATS, HEARTBEATS))
    assert theorem_with_proof(STATEMENT, executed) in project.requests("cmd")


@needs_linux
async def test_verification_also_checks_the_written_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    await proved(project, "nlinarith [h]\ndone")
    assert theorem_with_proof(STATEMENT, "nlinarith [h]\ndone") in project.requests("cmd")


@needs_linux
async def test_the_cache_answers_a_repeated_written_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    await proved(project, "nlinarith [h]", SearchMemory(cache_results=True))
    assert project.requests("tactic").count("lean_search_nlinarith degree [h]") == 1


@needs_linux
async def test_the_policy_cannot_write_the_variant_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    project = dataclasses.replace(
        project, config=dataclasses.replace(project.config, forbidden_tokens=LeanReplConfig().forbidden_tokens)
    )
    async with LeanRepl(project.config) as repl:
        start = await repl.start_proof(STATEMENT, HEADER)
        assert isinstance(start.outcome, ProofState)
        result = await repl.apply_block(start.outcome, "lean_search_nlinarith degree [h]")
    assert isinstance(result.failure, LeanError) and result.failure.message.startswith("Forbidden tokens")


class Blocks:
    def __init__(self, *texts: str) -> None:
        self.texts = texts

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(tuple(Candidate(text, StepSource.POLICY, log_probability=-1.0) for text in self.texts))


PROBLEM = Problem("t", Split.VALID, HEADER, STATEMENT, "", "")


def search_config(variant: NlinarithVariant | None) -> SearchConfig:
    return SearchConfig(
        max_expansions=1, check_identifiers=False, name_inaccessible_hypotheses=False, nlinarith_variant=variant
    )


@needs_linux
async def test_the_tree_keeps_the_written_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = variant_project(tmp_path, monkeypatch, DEGREE)
    async with LeanRepl(project.config) as repl:
        completed = await search_theorem(
            PROBLEM, repl, Blocks("nlinarith [h]\ndone"), DepthPlusGoals(), search_config(DEGREE)
        )
    assert completed.tree is not None
    edge = completed.tree.edges[0]
    assert (edge.text, [piece.text for piece in edge.executed_tactics], completed.result.proof) == (
        "nlinarith [h]\ndone",
        ["nlinarith [h]", "done"],
        "nlinarith [h]\ndone",
    )


@needs_linux
async def test_a_search_on_a_pool_with_another_nlinarith_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = variant_project(tmp_path, monkeypatch, None)
    async with LeanRepl(project.config) as repl:
        with pytest.raises(AssertionError):
            await search_theorem(PROBLEM, repl, Blocks("nlinarith"), DepthPlusGoals(), search_config(DEGREE))


lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
needs_lean = pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)")
MATHLIB = "import Mathlib\n"
INEQUALITY = "theorem t (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : a * b ≤ (a + b) ^ 2 / 2 := by\n"


@needs_lean
async def test_a_variant_proof_verifies_with_its_definitions() -> None:
    async with LeanRepl(LeanReplConfig(nlinarith_variant=DEGREE)) as repl:
        start = await repl.start_proof(INEQUALITY, MATHLIB)
        assert isinstance(start.outcome, ProofState)
        result = await repl.apply_block(start.outcome, "nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]", 50_000)
        verification = await repl.verify_state(result.state)
    assert (result.state.is_proved, verification.verified, verification.plain_verified) == (True, True, True)


@needs_lean
async def test_the_variant_fails_where_its_products_are_missing() -> None:
    statement = "theorem t (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 0 < a * b := by\n"
    async with LeanRepl(LeanReplConfig(nlinarith_variant=NlinarithVariant.LINEAR)) as repl:
        start = await repl.start_proof(statement, MATHLIB)
        assert isinstance(start.outcome, ProofState)
        result = await repl.apply_block(start.outcome, "nlinarith", 50_000)
    assert isinstance(result.failure, LeanError)


def harvesting_config(variant: NlinarithVariant | None) -> SearchConfig:
    return dataclasses.replace(search_config(variant), harvest=HarvestConfig(enabled=True, max_expansions=0))


async def two_proofs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: NlinarithVariant | None) -> object:
    """A variant-only proof first, then a plain one the harvest finishes the expansion with."""
    project = variant_project(tmp_path, monkeypatch, variant)
    blocks = Blocks("nlinarith [h]\ndone", "step\ndone")
    async with LeanRepl(project.config) as repl:
        return await search_theorem(PROBLEM, repl, blocks, DepthPlusGoals(), harvesting_config(variant))


@needs_linux
async def test_every_verified_proof_records_the_plain_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    completed = await two_proofs(tmp_path, monkeypatch, DEGREE)
    proofs = [node for node in completed.tree.nodes if node.plain_verified is not None]
    assert [(node.step, node.plain_verified) for node in proofs] == [
        ("nlinarith [h]\ndone", False),
        ("step\ndone", True),
    ]


@needs_linux
async def test_the_trees_count_the_proofs_that_need_the_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = await two_proofs(tmp_path, monkeypatch, DEGREE)
    record = tree_record(completed.tree, STATEMENT, completed.result)
    assert plain_checks([record]) == PlainChecks(checked_proofs=2, failed_proofs=1, variant_only_trees=0)


@needs_linux
async def test_without_the_variant_no_node_records_a_plain_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = await two_proofs(tmp_path, monkeypatch, None)
    nodes = json.loads(to_json(tree_record(completed.tree, STATEMENT, completed.result)))["nodes"]
    assert [node for node in nodes if "plain_verified" in node] == []


def test_the_summary_names_the_variant_in_its_plain_check() -> None:
    assert "Mathlib's nlinarith where the search ran the degree variant" in plain_check_label("degree")


def test_the_summary_without_the_variant_reads_as_before() -> None:
    assert plain_check_label(None) == "Proofs that also verify without the per-step heartbeat wrappers"
