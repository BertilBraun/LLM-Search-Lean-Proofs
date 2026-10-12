"""The loop's search: the A* best-first search with harvesting after a proof, pausing in place and re-scoring.

LoopSearch extends the search core's theorem search (lean_search.search.search._TheoremSearch, whose loop it reuses)
with what the loop needs; it belongs in the core once its owner adds it there:

- stages: the budget escalates in stages on the same tree (32, 128, 512 expansions in total by default), each
  stage entered only while the open frontier stays close to a proof;
- harvesting: after the first verified proof, frontier states the value model puts within `max_remaining_steps` of
  done are expanded for up to `max_expansions` more expansions, so near-proofs become further proofs;
- pausing: every policy and value request passes a PauseGate, so a training phase stops all requests while the
  searches keep their trees and their REPL proof states; the wall-clock budget does not count paused time;
- re-scoring: every state remembers the value-model version that scored it; when the best frontier state is stale,
  the best stale states (up to `lazy_rescore_states`) are re-scored in one request before the pop (or the whole
  frontier at once after a phase, the older option).
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from lean_search.data import Problem
from lean_search.expert_iteration.loop_config import HarvestConfig
from lean_search.lean import LeanRepl
from lean_search.search import (
    Accounting,
    CandidateBatches,
    CompletedSearch,
    Expander,
    Frontier,
    Node,
    PriorityFunction,
    Scores,
    SearchConfig,
    SearchContext,
    StopReason,
    ValueEstimates,
    ValueEstimator,
)
from lean_search.search.search import _Expansion, _TheoremSearch


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


@dataclass(frozen=True)
class StageResult:
    """How a stage of a search ended; costs are the stage's own."""

    stage: int
    stop_reason: StopReason
    proved: bool
    # Expansions of the stage without harvesting.
    expansions: int
    harvest_expansions: int
    harvested_proofs: int
    wall_seconds: float
    lean_seconds: float
    prompt_tokens: int
    generated_tokens: int
    value_prompt_tokens: int
    best_frontier_value: float | None
    max_depth: int

    @property
    def frontier_exhausted(self) -> bool:
        return self.stop_reason == StopReason.FRONTIER_EXHAUSTED


async def never_continue(result: StageResult) -> bool:
    return False


class ValueClock:
    """The version of the value model the servers serve, shared by every search."""

    def __init__(self, version: int = 0) -> None:
        self.version = version


@dataclass(frozen=True)
class SearchControls:
    gate: PauseGate
    value_clock: ValueClock
    # Stale states re-scored together at a pop; 0 never re-scores lazily.
    lazy_rescore_states: int = 0


class LoopSearch(_TheoremSearch):
    """Stages raise the budget's totals on one tree; after an unproved stage, `continue_search` decides the next."""

    def __init__(
        self,
        problem: Problem,
        repl: LeanRepl,
        expander: Expander,
        priority_function: PriorityFunction,
        stages: Sequence[SearchConfig],
        first_stage: int,
        harvest: HarvestConfig,
        controls: SearchControls,
        continue_search: Callable[[StageResult], Awaitable[bool]] = never_continue,
    ) -> None:
        super().__init__(problem, repl, expander, priority_function, stages[first_stage])
        self.stages = stages
        self.first_stage = first_stage
        self.harvest = harvest
        self.gate = controls.gate
        self.value_clock = controls.value_clock
        self.lazy_rescore_states = controls.lazy_rescore_states
        self.continue_search = continue_search
        self.paused_at_start = self.gate.paused_seconds()
        # The value-model version that scored each enqueued state, and the version current when the running
        # expansion started (scores computed during it are at least that new).
        self.scored_versions: dict[int, int] = {}
        self.expansion_version = self.value_clock.version
        self.lazily_rescored = 0
        self.harvested: list[Node] = []
        self.harvest_expansions = 0
        self.stage_results: list[StageResult] = []
        self.stage = first_stage

    def wall_seconds(self) -> float:
        return super().wall_seconds() - (self.gate.paused_seconds() - self.paused_at_start)

    async def run(self) -> CompletedSearch:
        self.paused_at_start = self.gate.paused_seconds()
        self.expansion_version = self.value_clock.version
        completed = await super().run()
        if completed.tree is not None:
            # After the core marked the first proof and settled the statuses: harvested proofs reach open leaves, so
            # settling left their paths alive.
            for proved in self.harvested:
                completed.tree.mark_proof_path(proved)
        return completed

    async def _search(self) -> tuple[StopReason, Node | None]:
        stage = self.first_stage
        while True:
            self.stage = stage
            self.config = self.stages[stage]
            before = self.snapshot()
            stop_reason, proved = await super()._search()
            if proved is not None and self.harvest.max_expansions:
                first_proof_cost = self.solved_at
                self.harvested = await self._harvest()
                self.solved_at = first_proof_cost
            result = self._stage_result(stage, stop_reason, proved, before)
            self.stage_results.append(result)
            if proved is not None or stage + 1 >= len(self.stages) or not await self.continue_search(result):
                return stop_reason, proved
            stage += 1

    def _stage_result(
        self, stage: int, stop_reason: StopReason, proved: Node | None, before: Accounting
    ) -> StageResult:
        after = self.snapshot()
        estimates = [
            node.value_estimate
            for node in (self.tree.node(node_id) for node_id in self.frontier.node_ids())
            if node.value_estimate is not None
        ]
        return StageResult(
            stage=stage,
            stop_reason=stop_reason,
            proved=proved is not None,
            expansions=after.expansions - before.expansions - self.harvest_expansions,
            harvest_expansions=self.harvest_expansions,
            harvested_proofs=len(self.harvested),
            wall_seconds=after.wall_seconds - before.wall_seconds,
            lean_seconds=after.lean_seconds - before.lean_seconds,
            prompt_tokens=after.prompt_tokens - before.prompt_tokens,
            generated_tokens=after.generated_tokens - before.generated_tokens,
            value_prompt_tokens=after.value_prompt_tokens - before.value_prompt_tokens,
            best_frontier_value=min(estimates, default=None),
            max_depth=max(node.depth for node in self.tree.nodes),
        )

    async def _expand(self, node: Node) -> _Expansion:
        self.expansion_version = self.value_clock.version
        return await super()._expand(node)

    async def _enqueue(self, nodes: list[Node], early_scores: Mapping[int, asyncio.Task[Scores]]) -> None:
        await super()._enqueue(nodes, early_scores)
        for node in nodes:
            self.scored_versions[node.node_id] = self.expansion_version

    def _is_stale(self, node_id: int) -> bool:
        return self.scored_versions.get(node_id, self.value_clock.version) < self.value_clock.version

    async def _next_node(self) -> Node:
        """The best frontier node scored by the current value model, re-scoring the best stale ones as needed."""
        while self.lazy_rescore_states:
            node_id = self.frontier.pop()
            if not self._is_stale(node_id):
                return self.tree.node(node_id)
            stale, fresh = [node_id], []
            scanned = 1
            while len(stale) < self.lazy_rescore_states and self.frontier and scanned < 4 * self.lazy_rescore_states:
                other = self.frontier.pop()
                (stale if self._is_stale(other) else fresh).append(other)
                scanned += 1
            for fresh_id in fresh:
                self.frontier.push(fresh_id, self._priority(fresh_id))
            await self._rescore_nodes([self.tree.node(stale_id) for stale_id in stale])
        return await super()._next_node()

    def _priority(self, node_id: int) -> float:
        priority = self.tree.node(node_id).priority
        assert priority is not None, node_id
        return priority

    async def _rescore_nodes(self, nodes: list[Node]) -> None:
        version = self.value_clock.version
        scores = await self.priority_function.score(nodes, self.tree)
        self.accounting.value_prompt_tokens += scores.prompt_tokens
        estimates = scores.value_estimates or (None,) * len(nodes)
        for node, priority, estimate in zip(nodes, scores.priorities, estimates, strict=True):
            node.priority, node.value_estimate = priority, estimate
            self.scored_versions[node.node_id] = version
            self.frontier.push(node.node_id, priority)
        self.lazily_rescored += len(nodes)

    async def _harvest(self) -> list[Node]:
        proofs: list[Node] = []
        while self.frontier and self.harvest_expansions < self.harvest.max_expansions:
            node = await self._next_node()
            if node.value_estimate is None or node.value_estimate > self.harvest.max_remaining_steps:
                continue
            expansion = await self._expand(node)
            self.harvest_expansions += 1
            if expansion.proved is not None:
                proofs.append(expansion.proved)
            if expansion.out_of_time:
                break
        return proofs

    async def rescore(self) -> int:
        """New priorities for the open frontier; returns how many states were scored."""
        # Nodes the search pops or pushes while the scores are computed keep what they have.
        node_ids = self.frontier.node_ids()
        if not node_ids:
            return 0
        version = self.value_clock.version
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
                self.scored_versions[node_id] = version
            assert node.priority is not None, node_id
            frontier.push(node_id, node.priority)
        self.frontier = frontier
        return len(nodes)
