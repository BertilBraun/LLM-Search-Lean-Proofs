"""The search service: many concurrent searches over pool statements, paused in place for training phases.

Each of `concurrency` workers takes the scheduler's next job and runs a LoopSearch with the served policy and value
model (opened once; the adapters keep their names across versions). A search escalates stage by stage on its own tree
and REPL while its open frontier stays close to a proof; every stage writes a record to the open shard, the last one
with the tree (and, in thinking mode, the reasoning behind each step). A training phase pauses every policy and value
request at the gate: searches keep their trees and REPL proof states, nothing in flight is lost, and they continue
after the phase with the new weights, their open frontiers re-scored when that fits in the time limit. The service's
state is rebuilt from the shards on start; searches cut off by a crash start again at the stage they had reached.
"""

import asyncio
import contextlib
import dataclasses
import time
import traceback
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import dataclass

import httpx

from lean_search.corpora.records import StatementRecord, read_statement_records
from lean_search.expert_iteration.loop_config import LoopConfig, SearchStage
from lean_search.expert_iteration.loop_search import (
    GatedExpander,
    GatedValueEstimator,
    LoopSearch,
    PauseGate,
    StageResult,
)
from lean_search.expert_iteration.pool import pool_problem
from lean_search.expert_iteration.pool_search import PRELOADED_HEADER_SHARE, common_headers
from lean_search.expert_iteration.scheduler import Job, Scheduler, SchedulerCounts, StageOutcome, decide
from lean_search.expert_iteration.serving import LoopPaths, read_current, write_json_atomically
from lean_search.expert_iteration.shards import (
    AttemptRecord,
    Decision,
    ShardWriter,
    all_attempts,
    now,
    recover_open_shards,
)
from lean_search.expert_iteration.thinking import StepReasoning
from lean_search.expert_iteration.thinking_expander import ReasoningExpander, ReasoningLog
from lean_search.expert_iteration.trainer import PhaseStage, PhaseTrainer, read_phase_state
from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool
from lean_search.policy.expander import open_policy_expander
from lean_search.search import (
    Expander,
    PriorityFunction,
    RunConfig,
    SearchConfig,
    SearchResult,
    StopReason,
    TreeRecord,
    build_expander,
    build_priority_function,
    tree_record,
)
from lean_search.value.estimator import open_value_estimator

IDLE_SECONDS = 30.0
FAILURE_PAUSE_SECONDS = 5.0


@dataclass(frozen=True)
class ServiceHeartbeat:
    written_at: str
    version: int
    paused: bool
    live_searches: int
    # Searches in flight per stage.
    live_by_stage: tuple[int, ...]
    session_attempts: int
    session_proofs: int
    session_harvested_proofs: int
    session_failures: int
    scheduler: SchedulerCounts


@dataclass(frozen=True)
class Models:
    expander: Expander
    priority_function: PriorityFunction


@dataclass
class StageStart:
    version: int
    started_at: str


def served_run_config(template: RunConfig, config: LoopConfig) -> RunConfig:
    """The template with the served adapters on every server; a template without a value model keeps none."""
    serving = config.serving
    urls = tuple(server.url for server in serving.servers)
    policy = dataclasses.replace(
        template.policy, model=serving.served_model, adapter=serving.policy_adapter_name, server_urls=urls
    )
    value = (
        dataclasses.replace(
            template.value, model=serving.served_model, adapter=serving.value_adapter_name, server_urls=urls
        )
        if template.value.model
        else template.value
    )
    return dataclasses.replace(template, policy=policy, value=value)


def rescoring_fits(states: int, rate: float | None, max_seconds: float) -> bool:
    """Whether re-scoring `states` open states at the last measured rate (states/s) stays within the limit."""
    return rate is None or states <= rate * max_seconds


def stage_search_config(template: SearchConfig, stage: SearchStage) -> SearchConfig:
    return dataclasses.replace(template, max_expansions=stage.max_expansions, max_wall_seconds=stage.max_wall_seconds)


def stage_outcome(result: StageResult) -> StageOutcome:
    return StageOutcome(result.proved, False, result.frontier_exhausted, result.best_frontier_value, result.max_depth)


def stage_attempt(
    job: Job, start: StageStart, result: StageResult, search: LoopSearch, decision: Decision, max_expansions: int
) -> AttemptRecord:
    return AttemptRecord(
        problem_name=job.name,
        source=job.statement.source,
        stage=result.stage,
        model_version=start.version,
        max_expansions=max_expansions,
        started_at=start.started_at,
        finished_at=now(),
        proved=result.proved,
        stop_reason=result.stop_reason,
        proof_steps=0,
        expansions=result.expansions,
        total_expansions=search.accounting.expansions,
        nodes=search.accounting.nodes,
        wall_seconds=result.wall_seconds,
        lean_seconds=result.lean_seconds,
        prompt_tokens=result.prompt_tokens,
        generated_tokens=result.generated_tokens,
        value_prompt_tokens=result.value_prompt_tokens,
        root_value=search.tree.root.value_estimate,
        best_frontier_value=result.best_frontier_value,
        frontier_exhausted=result.frontier_exhausted,
        max_depth=result.max_depth,
        harvested_proofs=result.harvested_proofs,
        harvest_expansions=result.harvest_expansions,
        decision=decision,
        tree_file=None,
    )


def load_failure_attempt(job: Job, start: StageStart, result: SearchResult, max_expansions: int) -> AttemptRecord:
    accounting = result.accounting
    return AttemptRecord(
        problem_name=job.name,
        source=job.statement.source,
        stage=job.stage,
        model_version=start.version,
        max_expansions=max_expansions,
        started_at=start.started_at,
        finished_at=now(),
        proved=False,
        stop_reason=result.stop_reason,
        proof_steps=0,
        expansions=0,
        total_expansions=0,
        nodes=0,
        wall_seconds=accounting.wall_seconds,
        lean_seconds=accounting.lean_seconds,
        prompt_tokens=0,
        generated_tokens=0,
        value_prompt_tokens=0,
        root_value=None,
        best_frontier_value=None,
        frontier_exhausted=False,
        max_depth=0,
        harvested_proofs=0,
        harvest_expansions=0,
        decision=Decision.RETIRED_LOAD_FAILURE,
        tree_file=None,
    )


class SearchService:
    def __init__(
        self,
        config: LoopConfig,
        template: RunConfig,
        paths: LoopPaths,
        trainer: PhaseTrainer | None,
        log: Callable[[str], None],
    ) -> None:
        self.config = config
        self.template = served_run_config(template, config)
        self.paths = paths
        self.trainer = trainer
        self.log = log
        self.scheduler = Scheduler(config.search.scheduler)
        self.stage_configs = [
            stage_search_config(self.template.search, stage) for stage in self.scheduler.config.stages
        ]
        self.writer = ShardWriter(paths.shards, config.search.shard_attempts, config.search.shard_minutes * 60)
        self.gate = PauseGate()
        self.reasoning_log = ReasoningLog()
        self.write_lock = asyncio.Lock()
        self.live: set[LoopSearch] = set()
        self.version = 0
        self.session_attempts = 0
        self.session_proofs = 0
        self.session_harvested_proofs = 0
        self.session_failures = 0
        # Open states re-scored per second at the last re-scoring; None before the first.
        self.rescore_rate: float | None = None
        self.failure: Exception | None = None

    def load_state(self) -> list[StatementRecord]:
        for summary in recover_open_shards(self.paths.shards):
            self.log(f"Closed shard {summary.name} left open: {summary.attempts} attempts")
        statements = list(read_statement_records(self.paths.data_root / self.config.search.candidates))
        self.scheduler.add_statements(statements)
        replayed = self.scheduler.replay(all_attempts(self.paths.shards))
        self.version = read_current(self.paths).version
        self.log(f"{len(statements):,} statements, {replayed:,} attempts replayed: {self.scheduler.counts()}")
        return statements

    async def run(self, stop: asyncio.Event) -> None:
        statements = self.load_state()
        state = read_phase_state(self.paths)
        if self.trainer is not None and state is not None and state.stage != PhaseStage.DONE:
            # A phase a crash interrupted: the servers may be down, so it finishes before any search starts.
            self.log(f"Finishing phase {state.phase} from {state.stage}")
            await self.trainer.run_phase(state, None)
            self.version = read_current(self.paths).version
        headers = common_headers([pool_problem(statement) for statement in statements], PRELOADED_HEADER_SHARE)
        concurrency = self.config.search.concurrency
        async with contextlib.AsyncExitStack() as stack:
            models = await self.open_models(stack)
            pool = await stack.enter_async_context(
                LeanReplPool(concurrency, LeanReplConfig(), self.template.lean.restart_fraction)
            )
            await pool.start(headers)
            self.log(f"Pool of {concurrency} REPLs ready")
            coroutines = [self.work(pool, models, stop) for _ in range(concurrency)]
            coroutines.append(self.heartbeats(stop))
            if self.trainer is not None:
                coroutines.append(self.trainer.watch(self, stop))
            tasks = [asyncio.create_task(self.stopping_on_failure(coroutine, stop)) for coroutine in coroutines]
            try:
                await stop.wait()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.writer.close()
                self.write_heartbeat()
                self.log(f"Stopped after {self.session_attempts:,} attempts, {self.session_proofs:,} proofs")
        if self.failure is not None:
            raise RuntimeError("The search service stopped on a failure; a restart resumes it") from self.failure

    async def stopping_on_failure(self, coroutine: Coroutine[None, None, None], stop: asyncio.Event) -> None:
        """An unexpected error stops the whole service: a restart resumes the searches and an interrupted phase."""
        try:
            await coroutine
        except Exception as error:
            self.log(f"Stopping on {type(error).__name__}: {error}\n{traceback.format_exc()}")
            self.failure = error
            stop.set()

    async def open_models(self, stack: contextlib.AsyncExitStack) -> Models:
        config = self.template
        policy = None
        if config.expander.kind.uses_policy:
            opened = await stack.enter_async_context(open_policy_expander(config.policy, config.search.forbidden_steps))
            inner: Expander = ReasoningExpander(opened, self.reasoning_log) if config.policy.thinking else opened
            policy = GatedExpander(inner, self.gate)
        value_estimator = None
        if config.value.model:
            opened_value = await stack.enter_async_context(open_value_estimator(config.value))
            value_estimator = GatedValueEstimator(opened_value, self.gate)
        return Models(build_expander(config, policy), build_priority_function(config.priority, value_estimator))

    async def work(self, pool: LeanReplPool, models: Models, stop: asyncio.Event) -> None:
        while not stop.is_set():
            job = self.scheduler.next_job()
            if job is None:
                await asyncio.sleep(IDLE_SECONDS)
                continue
            try:
                async with pool.acquire() as repl:
                    await self.search(job, repl, models)
            except httpx.HTTPError as error:
                # A server failed: the statement starts again at the stage it had reached.
                self.scheduler.release(job)
                self.session_failures += 1
                self.log(f"{job.name} stage {job.stage}: {type(error).__name__}: {error}; requeued")
                await asyncio.sleep(FAILURE_PAUSE_SECONDS)
            finally:
                self.reasoning_log.take(job.name)

    async def search(self, job: Job, repl: LeanRepl, models: Models) -> None:
        stages = self.scheduler.config.stages
        start = StageStart(self.version, now())

        async def continue_search(result: StageResult) -> bool:
            nonlocal start
            decision = decide(stage_outcome(result), result.stage, self.scheduler.config)
            if decision != Decision.ESCALATED:
                return False
            max_expansions = stages[result.stage].max_expansions
            await self.record(stage_attempt(job, start, result, search, decision, max_expansions), None, [])
            start = StageStart(self.version, now())
            return True

        search = LoopSearch(
            pool_problem(job.statement),
            repl,
            models.expander,
            models.priority_function,
            self.stage_configs,
            job.stage,
            self.config.search.harvest,
            self.gate,
            continue_search,
        )
        self.live.add(search)
        try:
            completed = await search.run()
        finally:
            self.live.discard(search)
        if completed.result.stop_reason == StopReason.START_FAILED:
            attempt = load_failure_attempt(job, start, completed.result, stages[job.stage].max_expansions)
            await self.record(attempt, None, [])
            return
        assert completed.tree is not None, job.name
        last = search.stage_results[-1]
        decision = decide(stage_outcome(last), last.stage, self.scheduler.config)
        attempt = dataclasses.replace(
            stage_attempt(job, start, last, search, decision, stages[last.stage].max_expansions),
            proof_steps=len(completed.result.proof_steps),
        )
        tree = tree_record(completed.tree, job.statement.formal_statement, completed.result)
        await self.record(attempt, tree, self.reasoning_log.take(job.name))

    async def record(self, attempt: AttemptRecord, tree: TreeRecord | None, reasoning: list[StepReasoning]) -> None:
        async with self.write_lock:
            attempt = await asyncio.to_thread(self.writer.write, attempt, tree, reasoning)
        self.scheduler.record(attempt)
        self.session_attempts += 1
        self.session_proofs += attempt.proved
        self.session_harvested_proofs += attempt.harvested_proofs
        self.log(
            f"{attempt.problem_name} stage {attempt.stage} v{attempt.model_version}: {attempt.stop_reason} "
            f"expansions={attempt.expansions}/{attempt.total_expansions} tokens={attempt.generated_tokens} "
            f"harvested={attempt.harvested_proofs} h*={attempt.best_frontier_value} -> {attempt.decision} | "
            f"{self.session_proofs}/{self.session_attempts} this session"
        )

    async def pause(self) -> None:
        """No request leaves until resume; searches keep their trees, REPL states and place in the queue."""
        await self.gate.pause()
        async with self.write_lock:
            self.writer.close()
        self.write_heartbeat()
        self.log(f"Paused with {len(self.live)} searches in flight")

    async def resume(self, rescore: bool) -> None:
        self.version = read_current(self.paths).version
        self.gate.resume()
        self.log(f"Resumed on version {self.version} with {len(self.live)} searches")
        if rescore:
            await self.rescore(self.config.training.rescore_max_seconds)

    async def rescore(self, max_seconds: float) -> None:
        """Re-scores the open frontiers unless the last measured rate predicts more than `max_seconds`; stops there."""
        searches = list(self.live)
        states = sum(len(search.frontier) for search in searches)
        if not rescoring_fits(states, self.rescore_rate, max_seconds):
            assert self.rescore_rate is not None
            self.log(
                f"Re-scoring skipped: {states:,} open states would take about {states / self.rescore_rate:.0f} s "
                f"at {self.rescore_rate:.0f} states/s (limit {max_seconds:.0f} s)"
            )
            return
        started = time.monotonic()
        tasks = [asyncio.create_task(search.rescore()) for search in searches]
        done, pending = await asyncio.wait(tasks, timeout=max_seconds) if tasks else (set(), set())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        seconds = time.monotonic() - started
        failed = [task for task in done if task.exception() is not None]
        rescored = sum(task.result() for task in done if task.exception() is None)
        if rescored and seconds > 0:
            self.rescore_rate = rescored / seconds
        self.log(
            f"Re-scored {rescored:,} of {states:,} open states in {seconds:.0f} s ({len(pending)} searches cut off "
            f"at the {max_seconds:.0f} s limit, {len(failed)} failed)"
        )

    def write_heartbeat(self) -> None:
        stages = Counter(search.stage for search in self.live)
        write_json_atomically(
            self.paths.heartbeat,
            ServiceHeartbeat(
                written_at=now(),
                version=self.version,
                paused=not self.gate.opened.is_set(),
                live_searches=len(self.live),
                live_by_stage=tuple(stages[index] for index in range(len(self.scheduler.config.stages))),
                session_attempts=self.session_attempts,
                session_proofs=self.session_proofs,
                session_harvested_proofs=self.session_harvested_proofs,
                session_failures=self.session_failures,
                scheduler=self.scheduler.counts(),
            ),
        )

    async def heartbeats(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.write_heartbeat()
            await asyncio.sleep(self.config.search.heartbeat_seconds)
