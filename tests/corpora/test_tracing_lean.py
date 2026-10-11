import asyncio
import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.corpora.records import ProofRecord, TracePath, TraceStatus
from lean_search.corpora.tracing import (
    ProofTrace,
    TracingLimits,
    TracingShard,
    state_before,
    trace_proof,
    trace_shards,
)
from lean_search.lean import LeanRepl, LeanReplConfig, ProofState
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
OTHER_HEADER = "import Mathlib\nopen Real"
SUM_STATEMENT = "theorem test_sum (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a + b = 5 := by"
CONJUNCTION_STATEMENT = "theorem test_and (a b : ℕ) (h₀ : a = 2) (h₁ : b = 3) : a = 2 ∧ b = 3 := by"
LIMITS = TracingLimits(heartbeats=200_000, timeout_seconds=20.0)

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


def proof_record(name: str, statement: str, tactic_proof: str, header: str = HEADER) -> ProofRecord:
    return ProofRecord("test", f"test/{name}", name, header, statement, tactic_proof, "pinned")


TWO_STEPS = proof_record("two_steps", SUM_STATEMENT, "subst h₀\nomega")
BROKEN = proof_record("broken", SUM_STATEMENT, "subst h₀\nexact h₁")
BULLETS = proof_record("bullets", CONJUNCTION_STATEMENT, "constructor\n· exact h₀\n· exact h₁")
# The first line ends in `=`, so splitting cuts the `have` in two and only the merged block parses.
SPLIT_TERM = proof_record("split_term", SUM_STATEMENT, "have h : a + b =\n5 := by omega\nexact h")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl() as lean_repl:
        yield lean_repl


async def trace(repl: LeanRepl, record: ProofRecord, verify: bool = False) -> ProofTrace:
    return await trace_proof(repl, record, LIMITS, verify)


async def test_two_step_proof_is_complete(repl: LeanRepl) -> None:
    assert (await trace(repl, TWO_STEPS)).proof.status is TraceStatus.COMPLETE


async def test_two_step_proof_counts_down_two_and_one_remaining_steps(repl: LeanRepl) -> None:
    assert [step.remaining_steps for step in (await trace(repl, TWO_STEPS)).steps] == [2, 1]


async def test_broken_proof_is_a_step_error_at_its_second_step(repl: LeanRepl) -> None:
    proof = (await trace(repl, BROKEN)).proof
    assert (proof.status, proof.failing_step_index) == (TraceStatus.STEP_ERROR, 1)


async def test_broken_proof_yields_no_training_steps(repl: LeanRepl) -> None:
    assert (await trace(repl, BROKEN)).steps == ()


async def test_bullets_are_single_steps(repl: LeanRepl) -> None:
    steps = (await trace(repl, BULLETS)).steps
    assert [step.step for step in steps] == ["constructor", "· exact h₀", "· exact h₁"]


async def test_unparseable_piece_falls_back_to_the_block_path(repl: LeanRepl) -> None:
    proof = (await trace(repl, SPLIT_TERM)).proof
    assert (proof.path, proof.status) == (TracePath.BLOCK, TraceStatus.COMPLETE)


async def test_block_path_records_the_merged_steps(repl: LeanRepl) -> None:
    steps = (await trace(repl, SPLIT_TERM)).steps
    assert [step.step for step in steps] == ["have h : a + b =\n5 := by omega", "exact h"]


async def test_state_before_a_step_is_rebuilt_by_replay(repl: LeanRepl) -> None:
    last_step = (await trace(repl, BULLETS)).steps[-1]
    result = await repl.apply_tactic(state_before(last_step), last_step.step)
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def test_complete_trace_verifies(repl: LeanRepl) -> None:
    assert (await trace(repl, BULLETS, verify=True)).proof.verified is True


async def test_shards_with_two_headers_trace_completely() -> None:
    records = (
        TWO_STEPS,
        BULLETS,
        proof_record("other_header", SUM_STATEMENT, "subst h₀ h₁\nrfl", OTHER_HEADER),
        proof_record(
            "other_header_bullets", CONJUNCTION_STATEMENT, "constructor\n· exact h₀\n· exact h₁", OTHER_HEADER
        ),
    )
    traced: list[ProofTrace] = []

    async def collect(shard: TracingShard, traces: list[ProofTrace]) -> None:
        traced.extend(traces)

    may_proceed = asyncio.Event()
    may_proceed.set()
    await trace_shards([TracingShard("test", "main_0000", records)], 2, LeanReplConfig(), LIMITS, collect, may_proceed)
    assert sorted(trace.proof.status for trace in traced) == [TraceStatus.COMPLETE] * 4
