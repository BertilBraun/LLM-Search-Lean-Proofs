"""The loop's search: the A* best-first search with harvesting after a proof, pausing in place and re-scoring.

LoopSearch extends the search core's theorem search (lean_search.search.search._TheoremSearch, whose loop it reuses)
with three things the loop needs; they belong in the core once its owner adds them there:

- harvesting: after the first verified proof, frontier states the value model puts within `max_remaining_steps` of
  done are expanded for up to `max_expansions` more expansions, so near-proofs become further proofs;
- pausing: every policy and value request passes a PauseGate, so a training phase stops all requests while the
  searches keep their trees and their REPL proof states; the wall-clock budget does not count paused time;
- re-scoring: after a phase, the open frontier can be re-scored with the new value model.
"""

import asyncio
import contextlib
import time
from collections.abc import Sequence

from lean_search.data import Problem
from lean_search.expert_iteration.loop_config import HarvestConfig
from lean_search.lean import LeanRepl
from lean_search.search import (
    CandidateBatches,
    CompletedSearch,
    Expander,
    Frontier,
    Node,
    PriorityFunction,
    SearchConfig,
    SearchContext,
    StopReason,
    ValueEstimates,
    ValueEstimator,
)
from lean_search.search.search import _TheoremSearch


class PauseGate:
    """Requests enter while the gate is open; pausing closes it and waits until the requests in flight are done."""

    def __init__(self) -> None:
        self.opened = asyncio.Event()
        self.opened.set()
        self.idle = asyncio.Event()
        self.idle.set()
        self.in_flight = 0
        self.paused_total = 0.0
        self.paused_since: float | None = None

    async def enter(self) -> None:
        await self.opened.wait()
        self.in_flight += 1
        self.idle.clear()

    def leave(self) -> None:
        self.in_flight -= 1
        if self.in_flight == 0:
            self.idle.set()

    async def pause(self) -> None:
        self.opened.clear()
        self.paused_since = time.monotonic()
        await self.idle.wait()

    def resume(self) -> None:
        assert self.paused_since is not None
        self.paused_total += time.monotonic() - self.paused_since
        self.paused_since = None
        self.opened.set()

    def paused_seconds(self) -> float:
        ongoing = 0.0 if self.paused_since is None else time.monotonic() - self.paused_since
        return self.paused_total + ongoing


class GatedExpander:
    """The policy expander behind the gate: its request is in flight until the first batch arrives."""

    def __init__(self, inner: Expander, gate: PauseGate) -> None:
        self.inner = inner
        self.gate = gate

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        await self.gate.enter()
        released = False
        try:
            async with contextlib.aclosing(self.inner.expand(node, context)) as batches:
                async for batch in batches:
                    if not released:
                        self.gate.leave()
                        released = True
                    yield batch
        finally:
            if not released:
                self.gate.leave()


class GatedValueEstimator:
    def __init__(self, inner: ValueEstimator, gate: PauseGate) -> None:
        self.inner = inner
        self.gate = gate

    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        await self.gate.enter()
        try:
            return await self.inner.estimate(nodes)
        finally:
            self.gate.leave()


class LoopSearch(_TheoremSearch):
    def __init__(
        self,
        problem: Problem,
        repl: LeanRepl,
        expander: Expander,
        priority_function: PriorityFunction,
        config: SearchConfig,
        harvest: HarvestConfig,
        gate: PauseGate,
    ) -> None:
        super().__init__(problem, repl, expander, priority_function, config)
        self.harvest = harvest
        self.gate = gate
        self.paused_at_start = gate.paused_seconds()
        self.harvested: list[Node] = []
        self.harvest_expansions = 0

    def wall_seconds(self) -> float:
        return super().wall_seconds() - (self.gate.paused_seconds() - self.paused_at_start)

    async def run(self) -> CompletedSearch:
        self.paused_at_start = self.gate.paused_seconds()
        completed = await super().run()
        if completed.tree is not None:
            # After the core marked the first proof and settled the statuses: harvested proofs reach open leaves, so
            # settling left their paths alive.
            for proved in self.harvested:
                completed.tree.mark_proof_path(proved)
        return completed

    async def _search(self) -> tuple[StopReason, Node | None]:
        stop_reason, proved = await super()._search()
        if proved is not None and self.harvest.max_expansions:
            first_proof_cost = self.solved_at
            self.harvested = await self._harvest()
            self.solved_at = first_proof_cost
        return stop_reason, proved

    async def _harvest(self) -> list[Node]:
        proofs: list[Node] = []
        while self.frontier and self.harvest_expansions < self.harvest.max_expansions:
            node = self.tree.node(self.frontier.pop())
            if node.value_estimate is None or node.value_estimate > self.harvest.max_remaining_steps:
                continue
            expansion = await self._expand(node)
            self.harvest_expansions += 1
            if expansion.proved is not None:
                proofs.append(expansion.proved)
            if expansion.out_of_time:
                break
        return proofs

    async def rescore(self) -> None:
        """New priorities for the open frontier; nodes the search popped or pushed meanwhile keep what they have."""
        node_ids = self.frontier.node_ids()
        if not node_ids:
            return
        nodes = [self.tree.node(node_id) for node_id in node_ids]
        scores = await self.priority_function.score(nodes, self.tree)
        estimates = scores.value_estimates or (None,) * len(nodes)
        rescored = {
            node.node_id: (priority, estimate)
            for node, priority, estimate in zip(nodes, scores.priorities, estimates, strict=True)
        }
        frontier = Frontier()
        for node_id in self.frontier.node_ids():
            node = self.tree.node(node_id)
            if node_id in rescored:
                node.priority, node.value_estimate = rescored[node_id]
            assert node.priority is not None, node_id
            frontier.push(node_id, node.priority)
        self.frontier = frontier
