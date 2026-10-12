"""The search service: many concurrent searches over pool statements, paused in place for training phases.

Each of `concurrency` workers takes the scheduler's next job and runs a LoopSearch with the served policy and value
model (opened once; the adapters keep their names across versions). Attempts and trees go to the open shard. A
training phase pauses every policy and value request at the gate: searches keep their trees and REPL proof states,
nothing in flight is lost, and they continue after the phase with the new weights. The service's state is rebuilt
from the shards on start; searches cut off by a crash simply start again.
"""

import asyncio
import contextlib
import dataclasses
import time
import traceback
from collections.abc import Callable, Coroutine
from dataclasses import dataclass

import httpx

from lean_search.corpora.records import StatementRecord, read_statement_records
from lean_search.expert_iteration.loop_config import LoopConfig, PassBudget, SchedulerConfig
from lean_search.expert_iteration.loop_search import GatedExpander, GatedValueEstimator, LoopSearch, PauseGate
from lean_search.expert_iteration.pool import pool_problem
from lean_search.expert_iteration.pool_search import PRELOADED_HEADER_SHARE, common_headers
from lean_search.expert_iteration.preferences import dead_node_ids
from lean_search.expert_iteration.scheduler import AttemptOutcome, Job, Scheduler, SchedulerCounts, decide
from lean_search.expert_iteration.serving import LoopPaths, read_current, write_json_atomically
from lean_search.expert_iteration.shards import AttemptRecord, ShardWriter, all_attempts, now, recover_open_shards
from lean_search.expert_iteration.trainer import PhaseStage, PhaseTrainer, read_phase_state
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.policy.expander import open_policy_expander
from lean_search.search import (
    CompletedSearch,
    Expander,
    NodeStatus,
    PriorityFunction,
    RunConfig,
    SearchConfig,
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
    session_attempts: int
    session_proofs: int
    session_harvested_proofs: int
    session_failures: int
    scheduler: SchedulerCounts


@dataclass(frozen=True)
class Models:
    expander: Expander
    priority_function: PriorityFunction


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


def pass_search_config(template: SearchConfig, budget: PassBudget) -> SearchConfig:
    return dataclasses.replace(template, max_expansions=budget.max_expansions, max_wall_seconds=budget.max_wall_seconds)


def best_frontier_value(tree: TreeRecord) -> float | None:
    """The smallest h among the states still open when the search stopped."""
    estimates = [
        node.value_estimate
        for node in tree.nodes
        if node.status == NodeStatus.OPEN and node.goals and node.value_estimate is not None
    ]
    return min(estimates, default=None)


def attempt_record(
    job: Job, version: int, started_at: str, completed: CompletedSearch, search: LoopSearch, config: SchedulerConfig
) -> tuple[AttemptRecord, TreeRecord | None]:
    result = completed.result
    tree = None if completed.tree is None else tree_record(completed.tree, job.statement.formal_statement, result)
    outcome = AttemptOutcome(
        proved=result.proved,
        start_failed=result.stop_reason == StopReason.START_FAILED,
        best_frontier_value=None if tree is None else best_frontier_value(tree),
        root_dead=tree is not None and 0 in dead_node_ids(tree),
        max_depth=result.max_depth_reached,
    )
    attempt = AttemptRecord(
        problem_name=job.name,
        source=job.statement.source,
        pass_index=job.pass_index,
        model_version=version,
        max_expansions=job.budget.max_expansions,
        started_at=started_at,
        finished_at=now(),
        proved=result.proved,
        stop_reason=result.stop_reason,
        proof_steps=len(result.proof_steps),
        expansions=result.accounting.expansions,
        nodes=result.accounting.nodes,
        wall_seconds=search.wall_seconds(),
        lean_seconds=result.accounting.lean_seconds,
        generated_tokens=result.accounting.generated_tokens,
        root_value=None if tree is None else tree.nodes[0].value_estimate,
        best_frontier_value=outcome.best_frontier_value,
        root_dead=outcome.root_dead,
        max_depth=outcome.max_depth,
        harvested_proofs=len(search.harvested),
        harvest_expansions=search.harvest_expansions,
        decision=decide(outcome, job.pass_index, config),
        tree_file=None,
    )
    return attempt, tree


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
        self.writer = ShardWriter(paths.shards, config.search.shard_attempts, config.search.shard_minutes * 60)
        self.gate = PauseGate()
        self.write_lock = asyncio.Lock()
        self.live: set[LoopSearch] = set()
        self.version = 0
        self.session_attempts = 0
        self.session_proofs = 0
        self.session_harvested_proofs = 0
        self.session_failures = 0
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
            policy = GatedExpander(opened, self.gate)
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
            version = self.version
            started_at = now()
            try:
                async with pool.acquire() as repl:
                    search = LoopSearch(
                        pool_problem(job.statement),
                        repl,
                        models.expander,
                        models.priority_function,
                        pass_search_config(self.template.search, job.budget),
                        self.config.search.harvest,
                        self.gate,
                    )
                    self.live.add(search)
                    try:
                        completed = await search.run()
                    finally:
                        self.live.discard(search)
            except httpx.HTTPError as error:
                # A server failed: the statement waits for the same pass again.
                self.scheduler.release(job)
                self.session_failures += 1
                self.log(f"{job.name} pass {job.pass_index}: {type(error).__name__}: {error}; requeued")
                await asyncio.sleep(FAILURE_PAUSE_SECONDS)
                continue
            await self.record(job, version, started_at, completed, search)

    async def record(
        self, job: Job, version: int, started_at: str, completed: CompletedSearch, search: LoopSearch
    ) -> None:
        attempt, tree = attempt_record(job, version, started_at, completed, search, self.config.search.scheduler)
        async with self.write_lock:
            attempt = await asyncio.to_thread(self.writer.write, attempt, tree)
        self.scheduler.record(attempt)
        self.session_attempts += 1
        self.session_proofs += attempt.proved
        self.session_harvested_proofs += attempt.harvested_proofs
        self.log(
            f"{attempt.problem_name} pass {attempt.pass_index} v{version}: {attempt.stop_reason} "
            f"expansions={attempt.expansions} harvested={attempt.harvested_proofs} h={attempt.root_value} -> "
            f"{attempt.decision} | {self.session_proofs}/{self.session_attempts} this session"
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
            started = time.monotonic()
            searches = list(self.live)
            await asyncio.gather(*(search.rescore() for search in searches))
            self.log(f"Re-scored the frontiers of {len(searches)} searches in {time.monotonic() - started:.0f} s")

    def write_heartbeat(self) -> None:
        write_json_atomically(
            self.paths.heartbeat,
            ServiceHeartbeat(
                written_at=now(),
                version=self.version,
                paused=not self.gate.opened.is_set(),
                live_searches=len(self.live),
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
