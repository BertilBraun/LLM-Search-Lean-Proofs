import dataclasses
import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from reasoning_records import HEADER, STATEMENT, sample_record

from lean_search.corpora.records import ProofRecord, TraceStatus
from lean_search.corpora.tracing import TracingLimits, state_before, trace_proof
from lean_search.lean import LeanRepl
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.reasoning.pipeline import ExecutionConfig, LeanExecutor, LeanTask, open_executor
from lean_search.reasoning.records import StateRecord, StateSamples
from lean_search.reasoning.reward import Classification, StepOutcome
from lean_search.reasoning.states import ReasoningState, proof_states

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]

PROOF = ProofRecord("test", "test/sum", "sum", HEADER, STATEMENT, "subst h₀\nsubst h₁\nnorm_num", "pinned")
FIRST_STATE_BLOCKS = {
    "subst h₀": Classification(StepOutcome.REFERENCE, 1),
    "subst h₀\nsubst h₁": Classification(StepOutcome.REFERENCE, 2),
    "omega": Classification(StepOutcome.CLOSED, 0),
    "subst h₁": Classification(StepOutcome.PROGRESS, 0),
    "skip": Classification(StepOutcome.NO_PROGRESS, 0),
    "omega\nskip": Classification(StepOutcome.CLOSED_EARLY, 0),
    "exact h₁": Classification(StepOutcome.ERROR, 0),
    "subst h₀\nexact h₁": Classification(StepOutcome.PARTIAL, 0),
}


def sampled(state: ReasoningState, blocks: list[str]) -> StateSamples:
    samples = [sample_record(index, block) for index, block in enumerate(blocks)]
    truncated = sample_record(len(blocks), None, 512, parse_failure=StepOutcome.TRUNCATED)
    return StateSamples(state, True, "", 100, 0, 512, 1.0, (*samples, truncated))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def states() -> list[ReasoningState]:
    async with LeanRepl() as repl:
        trace = await trace_proof(repl, PROOF, TracingLimits(200_000, 20.0), verify=False)
    assert trace.proof.status is TraceStatus.COMPLETE
    return proof_states(trace.steps)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def executor() -> AsyncIterator[LeanExecutor]:
    async with open_executor(HEADER, ExecutionConfig(pool_size=2)) as lean_executor:
        yield lean_executor


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def records(states: list[ReasoningState], executor: LeanExecutor) -> list[StateRecord]:
    broken_step = dataclasses.replace(states[1].step, proof_identifier="test/broken", previous_steps=("exact h₁",))
    unreplayable = dataclasses.replace(states[1], identifier="test/broken#1", step=broken_step)
    return await executor.execute(
        [
            sampled(states[0], list(FIRST_STATE_BLOCKS)),
            sampled(states[1], ["subst h₁"]),
            sampled(unreplayable, ["subst h₁"]),
        ]
    )


@pytest.mark.parametrize(("block", "expected"), FIRST_STATE_BLOCKS.items())
async def test_block_outcome_on_the_first_state(
    records: list[StateRecord], block: str, expected: Classification
) -> None:
    execution = next(execution for execution in records[0].executions if execution.tactic_block == block)
    assert Classification(execution.outcome, execution.reference_steps_advanced) == expected


async def test_unparsed_samples_are_not_executed(records: list[StateRecord]) -> None:
    assert len(records[0].executions) == len(FIRST_STATE_BLOCKS)


async def test_a_later_state_is_rebuilt_by_replaying_the_reference_steps(records: list[StateRecord]) -> None:
    assert [execution.outcome for execution in records[1].executions] == [StepOutcome.REFERENCE]


async def test_a_state_that_cannot_be_replayed_is_a_start_failure(records: list[StateRecord]) -> None:
    assert (bool(records[2].start_failure), records[2].executions) == (True, ())


async def test_records_keep_the_input_order(records: list[StateRecord], states: list[ReasoningState]) -> None:
    assert [record.sampled.state.identifier for record in records[:2]] == [states[0].identifier, states[1].identifier]


async def test_a_task_runs_its_blocks_on_its_proof_state(states: list[ReasoningState], executor: LeanExecutor) -> None:
    task = LeanTask(state_before(states[0].step), states[0].reference_goal_keys, ("omega", "exact h₁"))
    (result,) = await executor.run([task])
    assert [execution.outcome for execution in result.executions] == [StepOutcome.CLOSED, StepOutcome.ERROR]
