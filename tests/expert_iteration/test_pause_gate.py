import asyncio
from collections.abc import Sequence

from lean_search.expert_iteration.loop_search import GatedValueEstimator, PauseGate
from lean_search.search import Node, ValueEstimates


class OneStepEstimator:
    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        return ValueEstimates(tuple(1.0 for _ in nodes))


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


async def test_paused_time_accumulates_over_pauses() -> None:
    gate = PauseGate()
    for _ in range(2):
        await gate.pause()
        await asyncio.sleep(0.02)
        gate.resume()
    assert gate.paused_seconds() >= 0.04
