"""Sampling k completions per state from the served policy, executing their blocks in Lean, chunk by chunk."""

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import time
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

from lean_search.corpora.tracing import state_before
from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool, ProofState
from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.policy.client import PolicyClient, Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import (
    MINIMUM_GENERATED_TOKENS,
    PolicyTokenizer,
    load_tokenizer,
    served_max_model_length,
)
from lean_search.policy.prompts import render_prompt, stop_sequences
from lean_search.reasoning.records import (
    BlockExecution,
    RunDirectory,
    SampleRecord,
    StateRecord,
    StateSamples,
    chunks,
    read_records,
    write_records,
)
from lean_search.reasoning.reward import StepOutcome, classify_block, parse_failure_outcome
from lean_search.reasoning.states import GoalKey, ReasoningState
from lean_search.reasoning.thinking import parse_thinking_sample
from lean_search.search.search import DEFAULT_FORBIDDEN_STEPS
from lean_search.value.estimator import ValueModelEstimator

FORBIDDEN = FORBIDDEN_TOKENS | frozenset(DEFAULT_FORBIDDEN_STEPS)
MESSAGE_CHARACTERS = 300
logger = logging.getLogger(__name__)

type SampleState = Callable[[ReasoningState], Awaitable[StateSamples]]
type ExecuteStates = Callable[[Sequence[StateSamples]], Awaitable[list[StateRecord]]]
type RemainingSteps = Callable[[Sequence[str]], Awaitable[float]]


@dataclass(frozen=True)
class ExecutionConfig:
    pool_size: int = 8
    tactic_timeout_seconds: float = 10.0
    # None runs every tactic with LeanReplConfig's default, as the search does.
    tactic_heartbeats: int | None = None
    # States whose header is not the preloaded one run in batches on a restarted process.
    foreign_header_batch_size: int = 16


@dataclass(frozen=True)
class PipelineConfig:
    chunk_states: int = 256
    requests_in_flight: int = 128


class ReasoningSampler:
    def __init__(
        self,
        config: PolicyConfig,
        tokenizer: PolicyTokenizer,
        clients: Sequence[PolicyClient],
        max_model_length: int,
        requests_in_flight: int,
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self.max_model_length = max_model_length
        self._clients = itertools.cycle(clients)
        self._semaphore = asyncio.Semaphore(requests_in_flight)

    async def sample(self, state: ReasoningState) -> StateSamples:
        prompt = render_prompt(
            self.tokenizer,
            state.goals,
            few_shot=self.config.few_shot,
            thinking=self.config.thinking,
            thinking_instruction=self.config.thinking_instruction,
        )
        prompt_tokens = len(self.tokenizer.encode(prompt, add_special_tokens=False))
        max_tokens = min(self.config.max_tokens, self.max_model_length - prompt_tokens)
        if max_tokens < MINIMUM_GENERATED_TOKENS:
            return StateSamples(
                state,
                self.config.thinking,
                self.config.thinking_instruction,
                prompt_tokens,
                0,
                max_tokens,
                0.0,
                (),
            )
        async with self._semaphore:
            started = time.monotonic()
            generation = await next(self._clients).generate(
                prompt,
                sample_count=self.config.sample_count,
                max_tokens=max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                stop=stop_sequences(self.config.thinking),
                adapter=self.config.adapter,
            )
            seconds = time.monotonic() - started
        samples = tuple(
            sample_record(index, sample, self.config.thinking, self.tokenizer)
            for index, sample in enumerate(generation.samples)
        )
        return StateSamples(
            state,
            self.config.thinking,
            self.config.thinking_instruction,
            generation.prompt_token_count,
            generation.cached_prompt_token_count,
            max_tokens,
            seconds,
            samples,
        )


def sample_record(index: int, sample: Sample, thinking: bool, tokenizer: PolicyTokenizer) -> SampleRecord:
    parsed = parse_thinking_sample(sample, thinking=thinking, forbidden_tokens=FORBIDDEN)
    reasoning_tokens = len(tokenizer.encode(parsed.reasoning, add_special_tokens=False)) if parsed.reasoning else 0
    return SampleRecord(
        index=index,
        text=sample.text,
        finish_reason=sample.finish_reason,
        generated_tokens=sample.token_count,
        cumulative_logprob=sample.cumulative_logprob,
        reasoning=parsed.reasoning,
        reasoning_tokens=reasoning_tokens,
        tactic_block=parsed.tactic_block,
        parse_failure=None if parsed.parse_failure is None else parse_failure_outcome(parsed.parse_failure),
        recovered_format=parsed.recovered_format,
    )


@contextlib.asynccontextmanager
async def open_sampler(config: PolicyConfig, requests_in_flight: int) -> AsyncIterator[ReasoningSampler]:
    tokenizer = load_tokenizer(config.tokenizer)
    max_model_length = min([await served_max_model_length(url, config.model) for url in config.server_urls])
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(url, config.model, timeout_seconds=config.request_timeout_seconds)
            )
            for url in config.server_urls
        ]
        yield ReasoningSampler(config, tokenizer, clients, max_model_length, requests_in_flight)


def distinct_blocks(sampled: StateSamples) -> list[str]:
    return list(dict.fromkeys(sample.tactic_block for sample in sampled.samples if sample.tactic_block is not None))


@dataclass(frozen=True)
class LeanTask:
    """Blocks to run on one proof state, classified against the states of a reference proof."""

    proof_state: ProofState
    reference_goal_keys: tuple[GoalKey, ...]
    blocks: tuple[str, ...]


@dataclass(frozen=True)
class LeanTaskResult:
    # Why the proof state could not be rebuilt (or Lean failed around it); the blocks then have no executions.
    start_failure: str
    executions: tuple[BlockExecution, ...]


def state_task(sampled: StateSamples) -> LeanTask:
    # Session 0 is never live, so the first block replays the reference proof's earlier steps once.
    return LeanTask(
        state_before(sampled.state.step), sampled.state.reference_goal_keys, tuple(distinct_blocks(sampled))
    )


async def execute_block(
    repl: LeanRepl, state: ProofState, reference_goal_keys: Sequence[GoalKey], block: str, config: ExecutionConfig
) -> BlockExecution:
    result = await repl.apply_block(state, block, config.tactic_heartbeats, config.tactic_timeout_seconds)
    classification = classify_block(
        result.failure,
        len(result.applied_tactics),
        result.total_tactics,
        state.goal_key,
        result.state.goal_key,
        reference_goal_keys,
    )
    return BlockExecution(
        tactic_block=block,
        outcome=classification.outcome,
        reference_steps_advanced=classification.reference_steps_advanced,
        applied_tactics=len(result.applied_tactics),
        total_tactics=result.total_tactics,
        goals_after=result.state.goals,
        lean_seconds=result.elapsed_seconds,
        message="" if result.failure is None else result.failure.message[:MESSAGE_CHARACTERS],
    )


async def execute_task(repl: LeanRepl, task: LeanTask, config: ExecutionConfig) -> LeanTaskResult:
    executions: list[BlockExecution] = []
    for block in task.blocks:
        execution = await execute_block(repl, task.proof_state, task.reference_goal_keys, block, config)
        if execution.outcome == StepOutcome.INFRASTRUCTURE:
            return LeanTaskResult(execution.message, ())
        executions.append(execution)
    return LeanTaskResult("", tuple(executions))


def preloaded_header(states: Sequence[ReasoningState]) -> str:
    return Counter(state.step.header for state in states).most_common(1)[0][0]


def execution_batches(tasks: Sequence[LeanTask], header: str, foreign_batch_size: int) -> list[list[int]]:
    """Positions of the tasks, one per batch for the preloaded header and grouped by header otherwise."""
    by_header: dict[str, list[int]] = defaultdict(list)
    for position, task in enumerate(tasks):
        by_header[task.proof_state.header].append(position)
    batches = []
    for batch_header, positions in by_header.items():
        size = 1 if batch_header == header else foreign_batch_size
        batches += [positions[start : start + size] for start in range(0, len(positions), size)]
    # Large foreign-header batches first, so that none of them finishes last.
    return sorted(batches, key=lambda batch: -len(batch))


class LeanExecutor:
    def __init__(self, pool: LeanReplPool, header: str, config: ExecutionConfig) -> None:
        self.pool = pool
        self.header = header
        self.config = config

    async def run(self, tasks: Sequence[LeanTask]) -> list[LeanTaskResult]:
        results: dict[int, LeanTaskResult] = {}

        async def run_batch(positions: Sequence[int]) -> None:
            async with self.pool.acquire() as repl:
                foreign = tasks[positions[0]].proof_state.header != self.header
                if foreign:
                    # A second header re-imports Mathlib onto the heap, so a process holds one header at a time.
                    await repl.restart()
                for position in positions:
                    try:
                        results[position] = await execute_task(repl, tasks[position], self.config)
                    except Exception as error:
                        # The wrapper asserts on environments it cannot build (some headers): not the sample's fault.
                        logger.exception("Executing a task on %s failed", tasks[position].proof_state.statement[:80])
                        results[position] = LeanTaskResult(repr(error)[:MESSAGE_CHARACTERS], ())
                if foreign:
                    await repl.restart()
                    await repl.load_header(self.header)

        batches = execution_batches(tasks, self.header, self.config.foreign_header_batch_size)
        await asyncio.gather(*(run_batch(batch) for batch in batches))
        return [results[position] for position in range(len(tasks))]

    async def execute(self, sampled_states: Sequence[StateSamples]) -> list[StateRecord]:
        results = await self.run([state_task(sampled) for sampled in sampled_states])
        return [
            StateRecord(sampled, result.start_failure, result.executions)
            for sampled, result in zip(sampled_states, results, strict=True)
        ]


@contextlib.asynccontextmanager
async def open_executor(header: str, config: ExecutionConfig) -> AsyncIterator[LeanExecutor]:
    repl_config = LeanReplConfig(tactic_timeout_seconds=config.tactic_timeout_seconds)
    async with LeanReplPool(config.pool_size, repl_config) as pool:
        await pool.start([header])
        yield LeanExecutor(pool, header, config)


def value_remaining_steps(estimator: ValueModelEstimator) -> RemainingSteps:
    async def remaining_steps(goals: Sequence[str]) -> float:
        score = await estimator.score(goals)
        return estimator.config.readout.remaining_steps(score.probabilities)

    return remaining_steps


async def with_value_drops(record: StateRecord, remaining_steps: RemainingSteps) -> StateRecord:
    """Sets h(before) - h(after) on the executions whose goals changed without closing (the weaker success level)."""
    targets = [
        execution
        for execution in record.executions
        if execution.outcome in (StepOutcome.PROGRESS, StepOutcome.REFERENCE)
    ]
    if not targets:
        return record
    before = await remaining_steps(record.sampled.state.goals)
    after = await asyncio.gather(*(remaining_steps(execution.goals_after) for execution in targets))
    drops = {execution.tactic_block: before - value for execution, value in zip(targets, after, strict=True)}
    executions = tuple(
        dataclasses.replace(execution, value_drop=drops.get(execution.tactic_block)) for execution in record.executions
    )
    return dataclasses.replace(record, executions=executions)


@dataclass(frozen=True)
class SampledChunk:
    chunk: int
    sampled: list[StateSamples]
    # None when the samples were read back from an interrupted run.
    sampling_seconds: float | None


@dataclass(frozen=True)
class ChunkProgress:
    chunk: int
    chunks: int
    states: int
    samples: int
    generated_tokens: int
    sampling_seconds: float | None
    execution_seconds: float


async def run_chunks(
    directory: RunDirectory,
    states: Sequence[ReasoningState],
    chunk_states: int,
    sample_state: SampleState,
    execute_states: ExecuteStates,
    on_chunk: Callable[[ChunkProgress], None],
) -> None:
    """Samples and executes every chunk without records yet; sampling runs one chunk ahead of execution."""
    planned = chunks(states, chunk_states)
    done = set(directory.completed_chunks())
    sampled_chunks: asyncio.Queue[SampledChunk | None] = asyncio.Queue(maxsize=1)

    async def produce() -> None:
        for chunk in (chunk for chunk in range(len(planned)) if chunk not in done):
            path = directory.chunk_samples(chunk)
            if path.exists():
                await sampled_chunks.put(SampledChunk(chunk, read_records(path, StateSamples), None))
                continue
            started = time.monotonic()
            sampled = list(await asyncio.gather(*(sample_state(state) for state in planned[chunk])))
            write_records(path, sampled)
            await sampled_chunks.put(SampledChunk(chunk, sampled, time.monotonic() - started))
        await sampled_chunks.put(None)

    async def consume() -> None:
        while (item := await sampled_chunks.get()) is not None:
            started = time.monotonic()
            records = await execute_states(item.sampled)
            write_records(directory.chunk_records(item.chunk), records)
            samples = [sample for entry in item.sampled for sample in entry.samples]
            on_chunk(
                ChunkProgress(
                    chunk=item.chunk,
                    chunks=len(planned),
                    states=len(item.sampled),
                    samples=len(samples),
                    generated_tokens=sum(sample.generated_tokens for sample in samples),
                    sampling_seconds=item.sampling_seconds,
                    execution_seconds=time.monotonic() - started,
                )
            )

    await asyncio.gather(produce(), consume())
