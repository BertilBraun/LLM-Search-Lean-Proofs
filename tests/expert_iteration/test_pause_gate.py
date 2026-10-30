import asyncio
import contextlib
from collections.abc import Sequence

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_search import GatedExpander, GatedValueEstimator, PauseGate
from lean_search.lean import LeanRepl, ProofState
from lean_search.search import CandidateBatch, CandidateBatches, Node, SearchContext, SearchTree, ValueEstimates


class OneStepEstimator:
    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        return ValueEstimates(tuple(1.0 for _ in nodes))


class OneBatchExpander:
    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(())


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_pausing_waits_for_the_requests_in_flight() -> None:
    gate = PauseGate()
    await gate.enter()
    pause = asyncio.create_task(gate.pause())
    await settle()
    finished_early = pause.done()
    gate.leave()
    await asyncio.wait_for(pause, 1.0)
    assert not finished_early


async def test_requests_wait_while_paused() -> None:
    gate = PauseGate()
    await gate.pause()
    estimate = asyncio.create_task(GatedValueEstimator(OneStepEstimator(), gate).estimate([]))
    await settle()
    finished_early = estimate.done()
    gate.resume()
    await asyncio.wait_for(estimate, 1.0)
    assert not finished_early


async def test_batches_carry_the_policy_version_served_when_the_request_entered() -> None:
    gate = PauseGate()
    gate.policy_version = 4
    state = ProofState("", "theorem t : True := by", (), ("⊢ True",), repl_proof_state=0, session=0)
    tree = SearchTree("t", state, 0.0)
    context = SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())
    batches = [batch async for batch in GatedExpander(OneBatchExpander(), gate).expand(tree.root, context)]
    assert [batch.policy_version for batch in batches] == [4]


async def test_paused_time_accumulates_over_pauses() -> None:
    gate = PauseGate()
    for _ in range(2):
        await gate.pause()
        await asyncio.sleep(0.02)
        gate.resume()
    assert gate.paused_seconds() >= 0.04


class TwoBatchExpander:
    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield CandidateBatch(())
        yield CandidateBatch(())


def root_context() -> SearchContext:
    state = ProofState("", "theorem t : True := by", (), ("⊢ True",), repl_proof_state=0, session=0)
    tree = SearchTree("t", state, 0.0)
    return SearchContext(Problem("t", Split.VALID, "", state.statement, "", ""), tree, LeanRepl())


async def test_a_later_request_of_an_expansion_waits_while_paused() -> None:
    gate = PauseGate()
    context = root_context()
    async with contextlib.aclosing(
        GatedExpander(TwoBatchExpander(), gate).expand(context.tree.root, context)
    ) as batches:
        await anext(batches)
        await gate.pause()
        second = asyncio.create_task(anext(batches))
        await settle()
        finished_early = second.done()
        gate.resume()
        await asyncio.wait_for(second, 1.0)
    assert not finished_early


async def test_a_later_batch_carries_the_version_served_when_its_request_entered() -> None:
    gate = PauseGate()
    gate.policy_version = 4
    context = root_context()
    async with contextlib.aclosing(
        GatedExpander(TwoBatchExpander(), gate).expand(context.tree.root, context)
    ) as batches:
        await anext(batches)
        await gate.pause()
        gate.policy_version = 5
        gate.resume()
        second = await anext(batches)
    assert second.policy_version == 5
