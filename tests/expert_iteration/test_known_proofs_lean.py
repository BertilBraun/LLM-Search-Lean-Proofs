import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.corpora.records import ProofRecord
from lean_search.expert_iteration.known_proofs import (
    KnownProofStatement,
    VerifiedStatement,
    known_proof,
    proof_statement,
    verify_statement,
)
from lean_search.lean import LeanRepl, LeanReplConfig
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
AUTOMATION = ("norm_num",)

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


def candidate(statement: str, *proofs: str) -> KnownProofStatement:
    records = [
        ProofRecord("goedel_sft_v2", f"p{index}", "t@1", HEADER, statement, text, "")
        for index, text in enumerate(proofs)
    ]
    return KnownProofStatement(proof_statement(records[0]), "key", ("goedel_sft_v2",), tuple(map(known_proof, records)))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig(command_timeout_seconds=60.0)) as started:
        yield started


async def verified(repl: LeanRepl, statement: KnownProofStatement) -> VerifiedStatement:
    return await verify_statement(repl, statement, AUTOMATION, 5.0)


async def test_a_later_proof_certifies_when_the_first_fails(repl: LeanRepl) -> None:
    statement = candidate("theorem t (x : ℕ) : x + 0 = x := by", "exact lean_search_no_such_lemma", "simp")
    result = await verified(repl, statement)
    assert (result.verified, result.proof_tactics, len(result.failures)) == (True, 1, 1)


async def test_the_root_goals_are_recorded(repl: LeanRepl) -> None:
    result = await verified(repl, candidate("theorem t (x : ℕ) : x + 0 = x := by", "simp"))
    assert result.root_goals == ("x : ℕ\n⊢ x + 0 = x",)


async def test_automation_closing_the_root_is_recorded(repl: LeanRepl) -> None:
    result = await verified(repl, candidate("theorem two : (2 : ℕ) + 2 = 4 := by", "norm_num"))
    assert (result.verified, result.automation_solved) == (True, True)


async def test_a_statement_without_a_compiling_proof_stays_out(repl: LeanRepl) -> None:
    result = await verified(repl, candidate("theorem f : (1 : ℕ) = 2 := by", "simp"))
    assert (result.verified, result.load_failed) == (False, False)


async def test_a_statement_that_does_not_load_is_marked(repl: LeanRepl) -> None:
    result = await verified(repl, candidate('theorem broken : (1 : ℕ) = "a" := by', "simp"))
    assert (result.verified, result.load_failed) == (False, True)
