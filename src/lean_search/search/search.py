"""Best-first search over full Lean proof states for one theorem, and many theorems concurrently over a pool."""

import asyncio
import contextlib
import copy
import dataclasses
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple

from lean_search.data import Problem
from lean_search.lean import LeanError, LeanRepl, LeanReplPool, LeanTimeout, ProofState, ReplFailure
from lean_search.lean.text import join_tactics
from lean_search.search.expanders import Candidate, CandidateBatch, Expander, SearchContext
from lean_search.search.frontier import Frontier
from lean_search.search.priority import PriorityFunction, Scores
from lean_search.search.tree import (
    Edge,
    EdgeOutcome,
    Failure,
    FailureKind,
    Node,
    NodeStatus,
    SearchTree,
    StepSource,
)

# Library-search tactics build a lemma index on first use (~22 s, ~1.7 GiB per process).
DEFAULT_FORBIDDEN_STEPS = (
    "exact?",
    "apply?",
    "rw?",
    "simp?",
    "simp_all?",
    "dsimp?",
    "aesop?",
    "hint",
    "rw_search",
    "library_search",
)
POLICY_STEP_KEY = "<policy>"


@dataclass(frozen=True)
class SearchConfig:
    max_expansions: int = 256
    max_wall_seconds: float = 300.0
    max_depth: int = 16
    max_generated_tokens: int | None = None
    tactic_heartbeats: int | None = None
    tactic_timeout_seconds: float = 10.0
    forbidden_steps: tuple[str, ...] = DEFAULT_FORBIDDEN_STEPS
    # Score each child (the value request) as soon as it exists, while the expansion's other candidates run.
    score_children_early: bool = False


class StopReason(StrEnum):
    PROVED = "proved"
    FRONTIER_EXHAUSTED = "frontier_exhausted"
    EXPANSION_BUDGET = "expansion_budget"
    WALL_CLOCK_BUDGET = "wall_clock_budget"
    TOKEN_BUDGET = "token_budget"
    START_FAILED = "start_failed"


@dataclass
class Accounting:
    expansions: int = 0
    nodes: int = 0
    edges: int = 0
    lean_seconds: float = 0.0
    wall_seconds: float = 0.0
    prompt_tokens: int = 0
    generated_tokens: int = 0
    value_prompt_tokens: int = 0
    duplicates: int = 0
    errors: int = 0
    timeouts: int = 0
    repl_failures: int = 0
    rejected: int = 0
    verification_seconds: float = 0.0


@dataclass
class StepStatistics:
    step: str
    attempts: int = 0
    lean_seconds: float = 0.0
    children: int = 0
    duplicates: int = 0
    errors: int = 0
    heartbeat_timeouts: int = 0
    wall_clock_timeouts: int = 0
    repl_failures: int = 0
    rejected: int = 0
    repeated: int = 0
    proofs: int = 0


@dataclass(frozen=True)
class SearchResult:
    problem_name: str
    proved: bool
    stop_reason: StopReason
    proof: str | None
    proof_steps: tuple[str, ...]
    proof_sources: tuple[StepSource, ...]
    accounting: Accounting
    solved_at: Accounting | None
    verification_failures: int
    max_depth_reached: int
    plain_verified: bool | None = None
    step_statistics: tuple[StepStatistics, ...] = ()
    start_failure: str | None = None


@dataclass(frozen=True)
class CompletedSearch:
    result: SearchResult
    tree: SearchTree | None


class ForbiddenSteps:
    def __init__(self, tokens: Sequence[str]) -> None:
        alternatives = "|".join(sorted(map(re.escape, tokens), key=len, reverse=True))
        self._pattern = re.compile(rf"(?<![\w'.])({alternatives})(?![\w'])") if tokens else None

    def find(self, text: str) -> list[str]:
        return [] if self._pattern is None else sorted(set(self._pattern.findall(text)))


async def search_theorem(
    problem: Problem,
    repl: LeanRepl,
    expander: Expander,
    priority_function: PriorityFunction,
    config: SearchConfig,
) -> CompletedSearch:
    return await _TheoremSearch(problem, repl, expander, priority_function, config).run()


async def search_problems(
    problems: Sequence[Problem],
    pool: LeanReplPool,
    expander: Expander,
    priority_function: PriorityFunction,
    config: SearchConfig,
    concurrency: int,
    on_completed: Callable[[CompletedSearch], Awaitable[None]],
) -> list[SearchResult]:
    """Each search holds one REPL for its duration, because proof states live inside a process."""
    semaphore = asyncio.Semaphore(concurrency)

    async def search_one(problem: Problem) -> SearchResult:
        async with semaphore:
            async with pool.acquire() as repl:
                completed = await search_theorem(problem, repl, expander, priority_function, config)
            await on_completed(completed)
        return completed.result

    searches = [asyncio.create_task(search_one(problem)) for problem in problems]
    try:
        return list(await asyncio.gather(*searches))
    finally:
        # After a failure the other searches must stop before the caller closes the pool under them.
        for search in searches:
            search.cancel()
        await asyncio.gather(*searches, return_exceptions=True)


def node_scores(scores: Scores) -> list[tuple[float, float | None]]:
    value_estimates = scores.value_estimates or (None,) * len(scores.priorities)
    return list(zip(scores.priorities, value_estimates, strict=True))


def step_statistics(tree: SearchTree) -> tuple[StepStatistics, ...]:
    by_step: dict[str, StepStatistics] = {}
    for edge in tree.edges:
        key = edge.text if edge.source == StepSource.AUTOMATION else POLICY_STEP_KEY
        statistics = by_step.setdefault(key, StepStatistics(key))
        statistics.attempts += 1
        statistics.lean_seconds += edge.lean_seconds
        match edge.outcome:
            case EdgeOutcome.CHILD:
                statistics.children += 1
                assert edge.target_id is not None
                if tree.node(edge.target_id).is_proved:
                    statistics.proofs += 1
            case EdgeOutcome.DUPLICATE:
                statistics.duplicates += 1
            case EdgeOutcome.REJECTED:
                statistics.rejected += 1
            case EdgeOutcome.REPEATED:
                statistics.repeated += 1
            case EdgeOutcome.FAILED:
                pass
        match None if edge.failure is None else edge.failure.kind:
            case FailureKind.ERROR:
                statistics.errors += 1
            case FailureKind.HEARTBEAT_TIMEOUT:
                statistics.heartbeat_timeouts += 1
            case FailureKind.WALL_CLOCK_TIMEOUT:
                statistics.wall_clock_timeouts += 1
            case FailureKind.REPL_FAILURE:
                statistics.repl_failures += 1
            case FailureKind.FORBIDDEN | None:
                pass
    return tuple(by_step.values())


class _Execution(NamedTuple):
    applied_tactics: int
    total_tactics: int
    failure: Failure | None
    lean_seconds: float


@dataclass
class _Expansion:
    node: Node
    edge_id_by_text: dict[str, int] = field(default_factory=dict)
    proved: Node | None = None
    out_of_time: bool = False
    early_scores: dict[int, asyncio.Task[Scores]] = field(default_factory=dict)

    @property
    def stopped(self) -> bool:
        return self.proved is not None or self.out_of_time


class _TheoremSearch:
    def __init__(
        self,
        problem: Problem,
        repl: LeanRepl,
        expander: Expander,
        priority_function: PriorityFunction,
        config: SearchConfig,
    ) -> None:
        self.problem = problem
        self.repl = repl
        self.expander = expander
        self.priority_function = priority_function
        self.config = config
        self.forbidden_steps = ForbiddenSteps(config.forbidden_steps)
        self.frontier = Frontier()
        self.accounting = Accounting()
        self.solved_at: Accounting | None = None
        self.verification_failures = 0
        self.plain_verified: bool | None = None
        self.started = time.monotonic()

    def wall_seconds(self) -> float:
        return time.monotonic() - self.started

    def snapshot(self) -> Accounting:
        self.accounting.wall_seconds = self.wall_seconds()
        return copy.copy(self.accounting)

    async def run(self) -> CompletedSearch:
        self.started = time.monotonic()
        start = await self.repl.start_proof(self.problem.formal_statement, self.problem.header)
        self.accounting.lean_seconds += start.elapsed_seconds
        match start.outcome:
            case LeanError() | LeanTimeout() | ReplFailure() as failure:
                result = self._result(StopReason.START_FAILED, None, None)
                return CompletedSearch(dataclasses.replace(result, start_failure=failure.message), None)
            case ProofState() as root_state:
                tree = SearchTree(self.problem.name, root_state, start.elapsed_seconds)
        self.tree = tree
        self.context = SearchContext(self.problem, tree, self.repl)
        self.accounting.nodes = 1
        await self._enqueue([tree.root], {})
        stop_reason, proved = await self._search()
        if proved is not None:
            tree.mark_proof_path(proved)
        tree.settle_statuses()
        return CompletedSearch(self._result(stop_reason, proved, tree), tree)

    async def _search(self) -> tuple[StopReason, Node | None]:
        while True:
            if not self.frontier:
                return StopReason.FRONTIER_EXHAUSTED, None
            if self.accounting.expansions >= self.config.max_expansions:
                return StopReason.EXPANSION_BUDGET, None
            if self.wall_seconds() >= self.config.max_wall_seconds:
                return StopReason.WALL_CLOCK_BUDGET, None
            if (
                self.config.max_generated_tokens is not None
                and self.accounting.generated_tokens >= self.config.max_generated_tokens
            ):
                return StopReason.TOKEN_BUDGET, None
            expansion = await self._expand(self.tree.node(self.frontier.pop()))
            if expansion.proved is not None:
                return StopReason.PROVED, expansion.proved
            if expansion.out_of_time:
                return StopReason.WALL_CLOCK_BUDGET, None

    async def _expand(self, node: Node) -> _Expansion:
        expansion = _Expansion(node)
        node.expansion_index = self.accounting.expansions
        node.expanded_seconds = self.wall_seconds()
        self.accounting.expansions += 1
        before = copy.copy(self.accounting)
        try:
            await self._run_batches(expansion)
        except BaseException:
            for early_score in expansion.early_scores.values():
                early_score.cancel()
            raise
        node.expansion_wall_seconds = self.wall_seconds() - node.expanded_seconds
        node.expansion_lean_seconds = self.accounting.lean_seconds - before.lean_seconds
        node.expansion_prompt_tokens = self.accounting.prompt_tokens - before.prompt_tokens
        node.expansion_generated_tokens = self.accounting.generated_tokens - before.generated_tokens
        if expansion.out_of_time:
            return expansion
        node.status = NodeStatus.EXPANDED
        if expansion.proved is not None:
            return expansion
        await self._enqueue(
            [
                child
                for child in self.tree.children(node)
                if child.status == NodeStatus.OPEN and child.depth < self.config.max_depth
            ],
            expansion.early_scores,
        )
        return expansion

    async def _run_batches(self, expansion: _Expansion) -> None:
        async with contextlib.aclosing(self.expander.expand(expansion.node, self.context)) as batches:
            async for batch in batches:
                self._charge(expansion, batch)
                await self._run_batch(expansion, batch.candidates)
                if expansion.stopped:
                    break
        for batch in self.context.abandoned_batches:
            self._charge(expansion, batch)
        self.context.abandoned_batches.clear()
        if expansion.stopped:
            # Children scored before the expansion stopped are never enqueued, but their requests were sent.
            for scores in await asyncio.gather(*expansion.early_scores.values()):
                for ledger in self._ledgers(expansion):
                    ledger.value_prompt_tokens += scores.prompt_tokens

    def _charge(self, expansion: _Expansion, batch: CandidateBatch) -> None:
        for ledger in self._ledgers(expansion):
            ledger.prompt_tokens += batch.prompt_tokens
            ledger.generated_tokens += batch.generated_tokens

    def _ledgers(self, expansion: _Expansion) -> list[Accounting]:
        if expansion.proved is None:
            return [self.accounting]
        # Costs settled after the proving step were incurred before it, so the solve paid for them too.
        assert self.solved_at is not None
        return [self.accounting, self.solved_at]

    async def _run_batch(self, expansion: _Expansion, batch: Sequence[Candidate]) -> None:
        for candidate in batch:
            if self.wall_seconds() >= self.config.max_wall_seconds:
                expansion.out_of_time = True
                return
            child = await self._execute(expansion, candidate)
            if child is not None and child.is_proved and await self._verify(child):
                expansion.proved = child
                return

    async def _execute(self, expansion: _Expansion, candidate: Candidate) -> Node | None:
        node = expansion.node
        self.accounting.edges += 1
        normalized_text = candidate.text.strip()
        earlier_edge_id = expansion.edge_id_by_text.get(normalized_text)
        if earlier_edge_id is not None:
            self._record(node, candidate, EdgeOutcome.REPEATED, repeat_of=earlier_edge_id)
            return None
        child: Node | None = None
        forbidden = self.forbidden_steps.find(candidate.text)
        if forbidden:
            self.accounting.rejected += 1
            failure = Failure(FailureKind.FORBIDDEN, f"Forbidden steps: {', '.join(forbidden)}")
            edge = self._record(node, candidate, EdgeOutcome.REJECTED, failure=failure)
        else:
            edge, child = await self._apply(node, candidate)
        expansion.edge_id_by_text[normalized_text] = edge.edge_id
        if (
            self.config.score_children_early
            and child is not None
            and not child.is_proved
            and child.depth < self.config.max_depth
        ):
            expansion.early_scores[child.node_id] = asyncio.create_task(
                self.priority_function.score([child], self.tree)
            )
        return child

    async def _apply(self, node: Node, candidate: Candidate) -> tuple[Edge, Node | None]:
        heartbeats = candidate.heartbeats if candidate.heartbeats is not None else self.config.tactic_heartbeats
        timeout_seconds = (
            candidate.timeout_seconds if candidate.timeout_seconds is not None else self.config.tactic_timeout_seconds
        )
        result = await self.repl.apply_block(node.state, candidate.text, heartbeats, timeout_seconds)
        self.accounting.lean_seconds += result.elapsed_seconds
        failure = None if result.failure is None else Failure.from_lean(result.failure)
        match None if failure is None else failure.kind:
            case FailureKind.HEARTBEAT_TIMEOUT | FailureKind.WALL_CLOCK_TIMEOUT:
                self.accounting.timeouts += 1
            case FailureKind.REPL_FAILURE:
                self.accounting.repl_failures += 1
            case FailureKind.ERROR:
                self.accounting.errors += 1
            case FailureKind.FORBIDDEN | None:
                pass
        applied_tactics = len(result.applied_tactics)
        execution = _Execution(applied_tactics, result.total_tactics, failure, result.elapsed_seconds)
        if not applied_tactics:
            return self._record(node, candidate, EdgeOutcome.FAILED, execution=execution), None
        existing = None if result.state.is_proved else self.tree.node_with_goals(result.state.goal_key)
        if existing is not None:
            self.accounting.duplicates += 1
            edge = self._record(node, candidate, EdgeOutcome.DUPLICATE, existing.node_id, execution=execution)
            return edge, None
        edge = self._record(node, candidate, EdgeOutcome.CHILD, self.tree.next_node_id(), execution=execution)
        child = self.tree.add_child(
            node,
            edge.edge_id,
            join_tactics(result.state.tactics[len(node.state.tactics) :]),
            candidate.source,
            candidate.log_probability,
            result.state,
            self.wall_seconds(),
            result.elapsed_seconds,
        )
        self.accounting.nodes += 1
        return edge, child

    def _record(
        self,
        node: Node,
        candidate: Candidate,
        outcome: EdgeOutcome,
        target_id: int | None = None,
        *,
        execution: _Execution | None = None,
        failure: Failure | None = None,
        repeat_of: int | None = None,
    ) -> Edge:
        execution = execution or _Execution(0, 0, failure, 0.0)
        return self.tree.add_edge(
            node,
            text=candidate.text,
            source=candidate.source,
            log_probability=candidate.log_probability,
            prompt_tokens=candidate.prompt_tokens,
            generated_tokens=candidate.generated_tokens,
            outcome=outcome,
            target_id=target_id,
            applied_tactics=execution.applied_tactics,
            total_tactics=execution.total_tactics,
            failure=execution.failure,
            lean_seconds=execution.lean_seconds,
            repeat_of=repeat_of,
        )

    async def _verify(self, node: Node) -> bool:
        verification = await self.repl.verify_state(node.state)
        self.accounting.verification_seconds += verification.elapsed_seconds
        if verification.verified:
            self.solved_at = self.snapshot()
            self.plain_verified = verification.plain_verified
            return True
        self.verification_failures += 1
        node.verification_problems = verification.problems
        node.status = NodeStatus.FAILED
        return False

    async def _enqueue(self, nodes: list[Node], early_scores: Mapping[int, asyncio.Task[Scores]]) -> None:
        late_nodes = [node for node in nodes if node.node_id not in early_scores]
        late_scores = await self.priority_function.score(late_nodes, self.tree) if late_nodes else Scores(())
        early_results = dict(zip(early_scores, await asyncio.gather(*early_scores.values()), strict=True))
        self.accounting.value_prompt_tokens += late_scores.prompt_tokens + sum(
            scores.prompt_tokens for scores in early_results.values()
        )
        scored = dict(zip((node.node_id for node in late_nodes), node_scores(late_scores), strict=True))
        scored.update((node_id, node_scores(scores)[0]) for node_id, scores in early_results.items())
        for node in nodes:
            node.priority, node.value_estimate = scored[node.node_id]
            self.frontier.push(node.node_id, node.priority)

    def _result(self, stop_reason: StopReason, proved: Node | None, tree: SearchTree | None) -> SearchResult:
        accounting = self.snapshot()
        path = [] if tree is None or proved is None else tree.path(proved)[1:]
        return SearchResult(
            problem_name=self.problem.name,
            proved=proved is not None,
            stop_reason=stop_reason,
            proof=None if proved is None else proved.state.proof,
            proof_steps=tuple(node.step for node in path if node.step is not None),
            proof_sources=tuple(node.source for node in path if node.source is not None),
            accounting=accounting,
            solved_at=self.solved_at,
            verification_failures=self.verification_failures,
            max_depth_reached=0 if tree is None else max(node.depth for node in tree.nodes),
            plain_verified=self.plain_verified,
            step_statistics=() if tree is None else step_statistics(tree),
        )
