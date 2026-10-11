"""Phase 1 model probe: how useful are each model's sampled Lean steps on held-out proof states?

    python experiments/phase1_probe.py states                                   # fix the state set, once
    python experiments/phase1_probe.py sample --label qwen3.5-2b --model Qwen/Qwen3.5-2B --serve
    python experiments/phase1_probe.py execute --label qwen3.5-2b
    python experiments/phase1_probe.py summarize

States: traced validation-split states (never trained on; the reference step is known) and the miniF2F-valid
initial states (no reference; allowed here because nothing trains on them). `sample` asks the policy for k samples
per state in the search's prompt format (few-shot, non-thinking by default) with all requests queued, which also
measures samples/s; `--serve` starts and stops a vLLM server on one GPU. A LoRA adapter (`--adapter-path`) or a
merged checkpoint (`--model <path>`) probes a fine-tuned policy; `--states` reuses another run's state set.
`execute` applies every distinct parsed block to its state with the search's limits and writes the metrics.
Outputs in $LEAN_SEARCH_RUNS/<run>/: states.jsonl, models/<label>/{samples.jsonl,sampling.json,outcomes.jsonl,
metrics.json} and summary/{summary.md,summary.json}.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import json
import os
import statistics
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.records import DataSplit, TracedStep, read_traced_steps
from lean_search.corpora.tracing import stable_fraction, state_before
from lean_search.data import Split, load_minif2f
from lean_search.lean import (
    FORBIDDEN_TOKENS,
    LeanError,
    LeanRepl,
    LeanReplConfig,
    LeanReplPool,
    LeanTimeout,
    ProofState,
    ReplFailure,
)
from lean_search.policy import PolicyClient, Sample
from lean_search.policy.expander import PolicyTokenizer, load_tokenizer, served_max_model_length
from lean_search.policy.prompts import ParseFailure, parse_sample, parse_samples, render_prompt, stop_sequences
from lean_search.search.records import from_json_object, to_json
from lean_search.search.search import DEFAULT_FORBIDDEN_STEPS
from lean_search.search.summary import category, markdown_table

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
TRACED_DIRECTORY = DATA_DIRECTORY / "traced"
DEFAULT_RUN_NAME = "phase1_probe"
TRACED_STATE_COUNT = 1000
STATES_PER_PROOF = 3
# Keeps the few-shot prompt plus the output inside Qwen2.5-Math's 4096-token context.
MAX_GOAL_CHARACTERS = 3000
SAMPLE_COUNT = 8
TEMPERATURE = 1.0
MAX_TOKENS = 256
REQUESTS_IN_FLIGHT = 128
TACTIC_TIMEOUT_SECONDS = 10.0
FOREIGN_HEADER_BATCH_SIZE = 16
FAILURE_MESSAGE_CHARACTERS = 300
FORBIDDEN = FORBIDDEN_TOKENS | frozenset(DEFAULT_FORBIDDEN_STEPS)
PARSE_FAILURES = (ParseFailure.TRUNCATED, ParseFailure.NO_BLOCK, ParseFailure.EMPTY)


class StateKind(StrEnum):
    TRACED = "traced"
    MINIF2F = "minif2f"


class StateGroup(StrEnum):
    ALL = "all"
    TRACED = "traced"
    MINIF2F = "minif2f"

    def contains(self, kind: StateKind) -> bool:
        return self == StateGroup.ALL or self.value == kind.value


@dataclass(frozen=True)
class ProbeState:
    identifier: str
    kind: StateKind
    source: str
    header: str
    formal_statement: str
    goals: tuple[str, ...]
    traced_step: TracedStep | None


@dataclass(frozen=True)
class StateSamples:
    identifier: str
    prompt_tokens: int
    cached_prompt_tokens: int
    seconds: float
    samples: tuple[Sample, ...]


@dataclass(frozen=True)
class SamplingRun:
    label: str
    model: str
    tokenizer: str
    adapter_path: str | None
    sample_count: int
    temperature: float
    max_tokens: int
    few_shot: bool
    thinking: bool
    max_model_length: int
    states: int
    prompts_too_long: int
    wall_seconds: float
    samples: int
    generated_tokens: int
    prompt_tokens: int
    cached_prompt_tokens: int
    samples_per_second: float
    generated_tokens_per_second: float
    started_at: str
    git_revision: str


class ExecutionStatus(StrEnum):
    APPLIED = "applied"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True)
class BlockOutcome:
    tactic_block: str
    status: ExecutionStatus
    applied_tactics: int
    total_tactics: int
    goals_changed: bool
    proved: bool
    lean_seconds: float
    message: str


@dataclass(frozen=True)
class StateOutcome:
    identifier: str
    start_failure: str
    blocks: tuple[BlockOutcome, ...]


@dataclass(frozen=True)
class SampleResult:
    parse_failure: ParseFailure | None
    outcome: BlockOutcome | None
    log_probability: float
    generated_tokens: int
    exact_match: bool


@dataclass(frozen=True)
class StateResults:
    state: ProbeState
    results: tuple[SampleResult, ...]
    usable: bool
    lean_seconds: float


@dataclass(frozen=True)
class GroupMetrics:
    label: str
    group: str
    states: int
    unusable_states: int
    samples: int
    parse_failure_rate: float
    forbidden_rate: float
    valid_rate: float
    fully_valid_rate: float
    progress_rate: float
    close_rate: float
    exact_match_rate: float | None
    any_valid_rate: float
    any_progress_rate: float
    any_close_rate: float
    distinct_candidates_per_state: float
    mean_generated_tokens: float
    median_progress_log_probability: float | None
    median_invalid_log_probability: float | None
    lean_seconds_per_state: float


@dataclass(frozen=True)
class ModelMetrics:
    sampling: SamplingRun
    groups: tuple[GroupMetrics, ...]
    sources: tuple[GroupMetrics, ...]


@dataclass(frozen=True)
class RunPaths:
    directory: Path

    @property
    def states(self) -> Path:
        return self.directory / "states.jsonl"

    def model_directory(self, label: str) -> Path:
        return self.directory / "models" / label

    def samples(self, label: str) -> Path:
        return self.model_directory(label) / "samples.jsonl"

    def sampling(self, label: str) -> Path:
        return self.model_directory(label) / "sampling.json"

    def outcomes(self, label: str) -> Path:
        return self.model_directory(label) / "outcomes.jsonl"

    def metrics(self, label: str) -> Path:
        return self.model_directory(label) / "metrics.json"

    @property
    def summary(self) -> Path:
        return self.directory / "summary"


def write_records(path: Path, records: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(to_json(record) + "\n")
    temporary.replace(path)


def read_records[T](path: Path, record_type: type[T]) -> list[T]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(record_type, json.loads(line)) for line in lines if line.strip()]


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def normalized_whitespace(text: str) -> str:
    return " ".join(text.split())


def validation_steps(traced_directory: Path) -> list[TracedStep]:
    paths = sorted(traced_directory.glob("shards/*/*.steps.jsonl"))
    return [step for path in paths for step in read_traced_steps(path) if step.split == DataSplit.VALIDATION]


def step_key(step: TracedStep) -> str:
    return f"{step.proof_identifier}#{step.step_index}"


def select_traced_states(steps: Sequence[TracedStep], count: int) -> list[ProbeState]:
    by_proof: dict[str, list[TracedStep]] = defaultdict(list)
    for step in steps:
        if len("\n\n".join(step.goals_before)) <= MAX_GOAL_CHARACTERS:
            by_proof[step.proof_identifier].append(step)
    chosen: list[TracedStep] = []
    for proof_steps in by_proof.values():
        chosen += sorted(proof_steps, key=lambda step: stable_fraction(step_key(step), "probe"))[:STATES_PER_PROOF]
    chosen.sort(key=lambda step: stable_fraction(step_key(step), "probe order"))
    return [
        ProbeState(
            identifier=f"traced:{step_key(step)}",
            kind=StateKind.TRACED,
            source=step.source,
            header=step.header,
            formal_statement=step.formal_statement,
            goals=step.goals_before,
            traced_step=step,
        )
        for step in chosen[:count]
    ]


async def minif2f_initial_states(pool_size: int) -> list[ProbeState]:
    problems = load_minif2f(Split.VALID)
    async with LeanReplPool(pool_size) as pool:
        await pool.start(sorted({problem.header for problem in problems}))

        async def initial_state(problem_index: int) -> ProbeState | None:
            problem = problems[problem_index]
            async with pool.acquire() as repl:
                start = await repl.start_proof(problem.formal_statement, problem.header)
            match start.outcome:
                case ProofState() as root:
                    return ProbeState(
                        identifier=f"minif2f:{problem.name}",
                        kind=StateKind.MINIF2F,
                        source=category(problem.name),
                        header=problem.header,
                        formal_statement=problem.formal_statement,
                        goals=root.goals,
                        traced_step=None,
                    )
                case failure:
                    print(f"{problem.name} did not start: {failure}", flush=True)
                    return None

        started = await asyncio.gather(*(initial_state(index) for index in range(len(problems))))
    return [state for state in started if state is not None]


def command_states(arguments: argparse.Namespace, paths: RunPaths) -> None:
    if paths.states.exists():
        raise ValueError(f"{paths.states} exists; the state set is fixed once chosen.")
    steps = validation_steps(arguments.traced_directory)
    traced = select_traced_states(steps, arguments.traced_states)
    minif2f = asyncio.run(minif2f_initial_states(arguments.pool_size))
    write_records(paths.states, [*traced, *minif2f])
    proofs = len({state.identifier.split("#")[0] for state in traced})
    print(
        f"{len(steps)} validation steps; chose {len(traced)} traced states from {proofs} proofs and "
        f"{len(minif2f)} miniF2F-valid initial states into {paths.states}"
    )


@contextlib.contextmanager
def served_model(arguments: argparse.Namespace, served_name: str) -> Iterator[None]:
    if not arguments.serve:
        yield
        return
    environment = dict(os.environ)
    if arguments.max_model_len is not None:
        environment["MAX_MODEL_LEN"] = str(arguments.max_model_len)
    deployment = REPOSITORY_DIRECTORY / "deployment"
    command = [
        str(deployment / "serve_model.sh"),
        served_name,
        arguments.model,
        str(arguments.gpu),
        str(arguments.port),
    ]
    subprocess.run(command, check=True, env=environment)
    try:
        yield
    finally:
        subprocess.run([str(deployment / "stop_model.sh"), served_name], check=True)


@dataclass(frozen=True)
class SampledStates:
    results: tuple[StateSamples, ...]
    max_model_length: int
    prompts_too_long: int
    wall_seconds: float


async def sample_states(
    arguments: argparse.Namespace, states: Sequence[ProbeState], served_name: str, tokenizer: PolicyTokenizer
) -> SampledStates:
    max_model_length = await served_max_model_length(arguments.server_url, served_name)
    semaphore = asyncio.Semaphore(REQUESTS_IN_FLIGHT)
    async with PolicyClient(arguments.server_url, served_name) as client:
        adapter: str | None = None
        if arguments.adapter_path is not None:
            adapter = f"{served_name}-adapter"
            await client.load_adapter(adapter, arguments.adapter_path)

        async def sample_state(state: ProbeState) -> StateSamples:
            prompt = render_prompt(
                tokenizer, state.goals, few_shot=not arguments.zero_shot, thinking=arguments.thinking
            )
            prompt_tokens = len(tokenizer.encode(prompt, add_special_tokens=False))
            max_tokens = min(arguments.max_tokens, max_model_length - prompt_tokens)
            if max_tokens <= 0:
                return StateSamples(state.identifier, prompt_tokens, 0, 0.0, ())
            async with semaphore:
                started = time.monotonic()
                generation = await client.generate(
                    prompt,
                    sample_count=arguments.sample_count,
                    max_tokens=max_tokens,
                    temperature=arguments.temperature,
                    stop=stop_sequences(arguments.thinking),
                    adapter=adapter,
                )
                seconds = time.monotonic() - started
            return StateSamples(
                state.identifier,
                generation.prompt_token_count,
                generation.cached_prompt_token_count,
                seconds,
                tuple(generation.samples),
            )

        started = time.monotonic()
        results = await asyncio.gather(*(sample_state(state) for state in states))
        wall_seconds = time.monotonic() - started
    prompts_too_long = sum(not result.samples for result in results)
    return SampledStates(tuple(results), max_model_length, prompts_too_long, wall_seconds)


def command_sample(arguments: argparse.Namespace, paths: RunPaths) -> None:
    states = read_records(arguments.states or paths.states, ProbeState)
    if arguments.limit is not None:
        states = states[: arguments.limit]
    served_name = arguments.served_name or f"probe-{arguments.label}"
    tokenizer_name = arguments.tokenizer or arguments.model
    tokenizer = load_tokenizer(tokenizer_name)
    started_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    with served_model(arguments, served_name):
        sampled = asyncio.run(sample_states(arguments, states, served_name, tokenizer))
    write_records(paths.samples(arguments.label), sampled.results)
    samples = sum(len(result.samples) for result in sampled.results)
    generated_tokens = sum(sample.token_count for result in sampled.results for sample in result.samples)
    run = SamplingRun(
        label=arguments.label,
        model=arguments.model,
        tokenizer=tokenizer_name,
        adapter_path=arguments.adapter_path,
        sample_count=arguments.sample_count,
        temperature=arguments.temperature,
        max_tokens=arguments.max_tokens,
        few_shot=not arguments.zero_shot,
        thinking=arguments.thinking,
        max_model_length=sampled.max_model_length,
        states=len(states),
        prompts_too_long=sampled.prompts_too_long,
        wall_seconds=sampled.wall_seconds,
        samples=samples,
        generated_tokens=generated_tokens,
        prompt_tokens=sum(result.prompt_tokens for result in sampled.results),
        cached_prompt_tokens=sum(result.cached_prompt_tokens for result in sampled.results),
        samples_per_second=samples / sampled.wall_seconds,
        generated_tokens_per_second=generated_tokens / sampled.wall_seconds,
        started_at=started_at,
        git_revision=git_revision(),
    )
    paths.sampling(arguments.label).write_text(to_json(run), encoding="utf-8")
    print(
        f"{arguments.label}: {samples} samples for {len(states)} states in {sampled.wall_seconds:.0f} s "
        f"({run.samples_per_second:.1f} samples/s, {run.generated_tokens_per_second:.0f} tokens/s)",
        flush=True,
    )


def distinct_blocks(samples: Sequence[Sample], thinking: bool) -> list[str]:
    return [
        candidate.tactic_block
        for candidate in parse_samples(samples, thinking=thinking, forbidden_tokens=FORBIDDEN).candidates
    ]


def execution_status(failure: LeanError | LeanTimeout | ReplFailure | None, applied_tactics: int) -> ExecutionStatus:
    match failure:
        case None:
            return ExecutionStatus.APPLIED
        case ReplFailure():
            return ExecutionStatus.INFRASTRUCTURE
        case _ if applied_tactics:
            return ExecutionStatus.PARTIAL
        case LeanTimeout():
            return ExecutionStatus.TIMEOUT
        case LeanError():
            return ExecutionStatus.ERROR


async def execute_block(repl: LeanRepl, state: ProofState, block: str) -> BlockOutcome:
    result = await repl.apply_block(state, block, None, TACTIC_TIMEOUT_SECONDS)
    applied_tactics = len(result.applied_tactics)
    return BlockOutcome(
        tactic_block=block,
        status=execution_status(result.failure, applied_tactics),
        applied_tactics=applied_tactics,
        total_tactics=result.total_tactics,
        goals_changed=applied_tactics > 0 and result.state.goal_key != state.goal_key,
        proved=applied_tactics > 0 and result.state.is_proved,
        lean_seconds=result.elapsed_seconds,
        message="" if result.failure is None else result.failure.message[:FAILURE_MESSAGE_CHARACTERS],
    )


async def execute_state(repl: LeanRepl, state: ProbeState, blocks: Sequence[str]) -> StateOutcome:
    match state.kind:
        case StateKind.TRACED:
            assert state.traced_step is not None
            # A state of another session: the REPL replays the traced steps once and checks the goals.
            proof_state = state_before(state.traced_step)
        case StateKind.MINIF2F:
            start = await repl.start_proof(state.formal_statement, state.header)
            match start.outcome:
                case ProofState() as root:
                    proof_state = root
                case failure:
                    return StateOutcome(state.identifier, str(failure)[:FAILURE_MESSAGE_CHARACTERS], ())
    outcomes = [await execute_block(repl, proof_state, block) for block in blocks]
    return StateOutcome(state.identifier, "", tuple(outcomes))


@dataclass(frozen=True)
class ExecutionBatch:
    header: str
    states: tuple[ProbeState, ...]


def execution_batches(states: Sequence[ProbeState], preloaded_header: str) -> list[ExecutionBatch]:
    by_header: dict[str, list[ProbeState]] = defaultdict(list)
    for state in states:
        by_header[state.header].append(state)
    batches = []
    for header, members in by_header.items():
        size = 1 if header == preloaded_header else FOREIGN_HEADER_BATCH_SIZE
        batches += [
            ExecutionBatch(header, tuple(members[start : start + size])) for start in range(0, len(members), size)
        ]
    # Large foreign-header batches first, so that none of them finishes last.
    return sorted(batches, key=lambda batch: -len(batch.states))


async def execute_all(
    states: Sequence[ProbeState], blocks_by_state: dict[str, list[str]], pool_size: int
) -> list[StateOutcome]:
    header_counts: dict[str, int] = defaultdict(int)
    for state in states:
        header_counts[state.header] += 1
    preloaded_header = max(header_counts, key=lambda header: header_counts[header])
    outcomes: list[StateOutcome] = []
    async with LeanReplPool(pool_size, LeanReplConfig(tactic_timeout_seconds=TACTIC_TIMEOUT_SECONDS)) as pool:
        await pool.start([preloaded_header])
        started = time.monotonic()

        async def run_batch(batch: ExecutionBatch) -> None:
            async with pool.acquire() as repl:
                foreign = batch.header != preloaded_header
                if foreign:
                    # A second header re-imports Mathlib onto the heap, so a process holds one header at a time.
                    await repl.restart()
                for state in batch.states:
                    outcomes.append(await execute_state(repl, state, blocks_by_state[state.identifier]))
                if foreign:
                    await repl.restart()
                    await repl.load_header(preloaded_header)
            if len(outcomes) // 100 != (len(outcomes) - len(batch.states)) // 100:
                print(f"{len(outcomes)}/{len(states)} states in {time.monotonic() - started:.0f} s", flush=True)

        await asyncio.gather(*(run_batch(batch) for batch in execution_batches(states, preloaded_header)))
    return outcomes


def command_execute(arguments: argparse.Namespace, paths: RunPaths) -> None:
    states = {state.identifier: state for state in read_records(arguments.states or paths.states, ProbeState)}
    sampled = read_records(paths.samples(arguments.label), StateSamples)
    sampling = from_json_object(SamplingRun, json.loads(paths.sampling(arguments.label).read_text(encoding="utf-8")))
    blocks_by_state = {result.identifier: distinct_blocks(result.samples, sampling.thinking) for result in sampled}
    started = time.monotonic()
    outcomes = asyncio.run(
        execute_all([states[result.identifier] for result in sampled], blocks_by_state, arguments.pool_size)
    )
    write_records(paths.outcomes(arguments.label), outcomes)
    lean_seconds = sum(block.lean_seconds for outcome in outcomes for block in outcome.blocks)
    print(
        f"{arguments.label}: executed {sum(len(blocks) for blocks in blocks_by_state.values())} blocks on "
        f"{len(outcomes)} states in {time.monotonic() - started:.0f} s ({lean_seconds:.0f} Lean s)",
        flush=True,
    )
    metrics = model_metrics(list(states.values()), sampled, sampling, outcomes)
    paths.metrics(arguments.label).write_text(to_json(metrics), encoding="utf-8")


def sample_results(state: ProbeState, samples: StateSamples, outcome: StateOutcome, thinking: bool) -> StateResults:
    by_block = {block.tactic_block: block for block in outcome.blocks}
    reference = None if state.traced_step is None else normalized_whitespace(state.traced_step.step)
    results = []
    for sample in samples.samples:
        match parse_sample(sample, thinking=thinking, forbidden_tokens=FORBIDDEN):
            case ParseFailure() as failure:
                results.append(SampleResult(failure, None, sample.cumulative_logprob, sample.token_count, False))
            case str() as block:
                exact_match = reference is not None and normalized_whitespace(block) == reference
                outcome_of_block = by_block.get(block)
                results.append(
                    SampleResult(None, outcome_of_block, sample.cumulative_logprob, sample.token_count, exact_match)
                )
    infrastructure = any(block.status == ExecutionStatus.INFRASTRUCTURE for block in outcome.blocks)
    usable = not outcome.start_failure and not infrastructure and bool(results)
    lean_seconds = sum(block.lean_seconds for block in outcome.blocks)
    return StateResults(state, tuple(results), usable, lean_seconds)


def rate(count: float, total: int) -> float:
    return count / total if total else 0.0


def is_valid(outcome: BlockOutcome) -> bool:
    return outcome.applied_tactics > 0


def is_fully_valid(outcome: BlockOutcome) -> bool:
    return outcome.status == ExecutionStatus.APPLIED


def is_progress(outcome: BlockOutcome) -> bool:
    return outcome.goals_changed


def is_closing(outcome: BlockOutcome) -> bool:
    return outcome.proved


def satisfies(result: SampleResult, predicate: Callable[[BlockOutcome], bool]) -> bool:
    return result.outcome is not None and predicate(result.outcome)


def median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def group_metrics(label: str, group: str, state_results: Sequence[StateResults]) -> GroupMetrics:
    usable = [entry for entry in state_results if entry.usable]
    samples = [result for entry in usable for result in entry.results]

    def sample_rate(predicate: Callable[[BlockOutcome], bool]) -> float:
        return rate(sum(satisfies(result, predicate) for result in samples), len(samples))

    def any_rate(predicate: Callable[[BlockOutcome], bool]) -> float:
        return rate(sum(any(satisfies(result, predicate) for result in entry.results) for entry in usable), len(usable))

    has_reference = all(entry.state.kind == StateKind.TRACED for entry in state_results)
    distinct = sum(len({result.outcome for result in entry.results if result.outcome}) for entry in usable)
    return GroupMetrics(
        label=label,
        group=group,
        states=len(state_results),
        unusable_states=len(state_results) - len(usable),
        samples=len(samples),
        parse_failure_rate=rate(sum(result.parse_failure in PARSE_FAILURES for result in samples), len(samples)),
        forbidden_rate=rate(sum(result.parse_failure == ParseFailure.FORBIDDEN for result in samples), len(samples)),
        valid_rate=sample_rate(is_valid),
        fully_valid_rate=sample_rate(is_fully_valid),
        progress_rate=sample_rate(is_progress),
        close_rate=sample_rate(is_closing),
        exact_match_rate=rate(sum(result.exact_match for result in samples), len(samples)) if has_reference else None,
        any_valid_rate=any_rate(is_valid),
        any_progress_rate=any_rate(is_progress),
        any_close_rate=any_rate(is_closing),
        distinct_candidates_per_state=rate(distinct, len(usable)),
        mean_generated_tokens=rate(sum(result.generated_tokens for result in samples), len(samples)),
        median_progress_log_probability=median_or_none(
            [result.log_probability for result in samples if satisfies(result, is_progress)]
        ),
        median_invalid_log_probability=median_or_none(
            [result.log_probability for result in samples if satisfies(result, lambda outcome: not is_valid(outcome))]
        ),
        lean_seconds_per_state=rate(sum(entry.lean_seconds for entry in state_results), len(state_results)),
    )


def model_metrics(
    states: Sequence[ProbeState],
    sampled: Sequence[StateSamples],
    sampling: SamplingRun,
    outcomes: Sequence[StateOutcome],
) -> ModelMetrics:
    states_by_identifier = {state.identifier: state for state in states}
    samples_by_identifier = {entry.identifier: entry for entry in sampled}
    state_results = [
        sample_results(
            states_by_identifier[outcome.identifier],
            samples_by_identifier[outcome.identifier],
            outcome,
            sampling.thinking,
        )
        for outcome in outcomes
    ]
    groups = tuple(
        group_metrics(sampling.label, group, [entry for entry in state_results if group.contains(entry.state.kind)])
        for group in StateGroup
    )
    by_source: dict[str, list[StateResults]] = defaultdict(list)
    for entry in state_results:
        by_source[f"{entry.state.kind}/{entry.state.source}"].append(entry)
    sources = tuple(group_metrics(sampling.label, source, by_source[source]) for source in sorted(by_source))
    return ModelMetrics(sampling, groups, sources)


def percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.1%}"


def decimal(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


def group_of(model: ModelMetrics, group: StateGroup) -> GroupMetrics:
    return next(entry for entry in model.groups if entry.group == group)


def metrics_table(metrics: Sequence[ModelMetrics], group: StateGroup) -> str:
    headers = [
        "model",
        "states",
        "parse fail",
        "forbidden",
        "valid",
        "fully valid",
        "progress",
        "close",
        "exact match",
        "any valid",
        "any progress",
        "any close",
        "distinct / state",
        "tokens / sample",
        "median progress log p",
    ]
    rows = []
    for model in metrics:
        entry = group_of(model, group)
        rows.append(
            (
                model.sampling.label,
                entry.states - entry.unusable_states,
                percent(entry.parse_failure_rate),
                percent(entry.forbidden_rate),
                percent(entry.valid_rate),
                percent(entry.fully_valid_rate),
                percent(entry.progress_rate),
                percent(entry.close_rate),
                percent(entry.exact_match_rate),
                percent(entry.any_valid_rate),
                percent(entry.any_progress_rate),
                percent(entry.any_close_rate),
                decimal(entry.distinct_candidates_per_state),
                f"{entry.mean_generated_tokens:.0f}",
                decimal(entry.median_progress_log_probability),
            )
        )
    return markdown_table(headers, rows)


def throughput_table(metrics: Sequence[ModelMetrics]) -> str:
    headers = [
        "model",
        "checkpoint",
        "samples",
        "sampling s",
        "samples/s",
        "generated tokens/s",
        "prompt tokens / state",
        "prompt cache hits",
        "prompts too long",
        "Lean s / state",
    ]
    rows = [
        (
            model.sampling.label,
            model.sampling.model + ("" if model.sampling.adapter_path is None else f" + {model.sampling.adapter_path}"),
            model.sampling.samples,
            f"{model.sampling.wall_seconds:.0f}",
            f"{model.sampling.samples_per_second:.1f}",
            f"{model.sampling.generated_tokens_per_second:.0f}",
            f"{rate(model.sampling.prompt_tokens, model.sampling.states):.0f}",
            percent(rate(model.sampling.cached_prompt_tokens, model.sampling.prompt_tokens)),
            model.sampling.prompts_too_long,
            decimal(group_of(model, StateGroup.ALL).lean_seconds_per_state),
        )
        for model in metrics
    ]
    return markdown_table(headers, rows)


def sources_table(metrics: Sequence[ModelMetrics]) -> str:
    rows = []
    for source in sorted({entry.group for model in metrics for entry in model.sources}):
        row = [source]
        for model in metrics:
            entry = next(entry for entry in model.sources if entry.group == source)
            row.append(
                f"{percent(entry.valid_rate)} / {percent(entry.progress_rate)} / {percent(entry.any_close_rate)} "
                f"({entry.states - entry.unusable_states})"
            )
        rows.append(row)
    return markdown_table(["source", *(model.sampling.label for model in metrics)], rows)


def render_summary(metrics: Sequence[ModelMetrics], states: Sequence[ProbeState]) -> str:
    traced = sum(state.kind == StateKind.TRACED for state in states)
    sampling = metrics[0].sampling
    sections = [
        "# Phase 1 model probe",
        f"{traced} traced validation-split states (at most {STATES_PER_PROOF} per proof, goals of at most "
        f"{MAX_GOAL_CHARACTERS} characters, never trained on) and {len(states) - traced} miniF2F-valid initial "
        f"states. Per state k={sampling.sample_count} samples at temperature {sampling.temperature} in the search's "
        f"prompt format (few-shot: {sampling.few_shot}, thinking: {sampling.thinking}, at most {sampling.max_tokens} "
        f"tokens, stop at the closing fence), all requests queued at once ({REQUESTS_IN_FLIGHT} in flight) on one "
        f"RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` "
        f"(default heartbeats, {TACTIC_TIMEOUT_SECONDS:.0f} s wall clock).",
        "Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least "
        "one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = "
        "no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least "
        "one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. "
        "Median progress log p: summed log-probability of the samples that made progress.",
        "## All states",
        metrics_table(metrics, StateGroup.ALL),
        "## Traced validation states",
        metrics_table(metrics, StateGroup.TRACED),
        "## miniF2F-valid initial states",
        metrics_table(metrics, StateGroup.MINIF2F),
        "## Throughput and Lean cost",
        "Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).",
        throughput_table(metrics),
        "## Valid / progress / any-close by source (usable states)",
        sources_table(metrics),
    ]
    return "\n\n".join(sections) + "\n"


def command_summarize(arguments: argparse.Namespace, paths: RunPaths) -> None:
    states = read_records(arguments.states or paths.states, ProbeState)
    labels = arguments.labels or sorted(path.parent.name for path in paths.directory.glob("models/*/metrics.json"))
    metrics = [
        from_json_object(ModelMetrics, json.loads(paths.metrics(label).read_text(encoding="utf-8"))) for label in labels
    ]
    paths.summary.mkdir(parents=True, exist_ok=True)
    (paths.summary / "summary.json").write_text(
        json.dumps([dataclasses.asdict(model) for model in metrics], indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (paths.summary / "summary.md").write_text(render_summary(metrics, states), encoding="utf-8")
    print(f"Summary of {len(metrics)} models in {paths.summary}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--states", type=Path, help="state set of another run (default: <run>/states.jsonl)")
    commands = parser.add_subparsers(dest="command", required=True)

    states = commands.add_parser("states", help="choose the fixed state set")
    states.add_argument("--traced-directory", type=Path, default=TRACED_DIRECTORY)
    states.add_argument("--traced-states", type=int, default=TRACED_STATE_COUNT)
    states.add_argument("--pool-size", type=int, default=16)

    sample = commands.add_parser("sample", help="sample k candidates per state from one model")
    sample.add_argument("--label", required=True)
    sample.add_argument("--model", required=True, help="Hugging Face repository or merged checkpoint path")
    sample.add_argument("--tokenizer", help="chat template source (default: --model)")
    sample.add_argument("--served-name", help="model name on an already running server (default: probe-<label>)")
    sample.add_argument("--adapter-path", help="LoRA adapter to load at runtime and sample through")
    sample.add_argument("--server-url", default="http://127.0.0.1:8100/v1")
    sample.add_argument("--serve", action="store_true", help="start and stop a vLLM server for --model")
    sample.add_argument("--gpu", type=int, default=0)
    sample.add_argument("--port", type=int, default=8100)
    sample.add_argument("--max-model-len", type=int, help="MAX_MODEL_LEN for serve_model.sh (Qwen2.5-Math: 4096)")
    sample.add_argument("--sample-count", type=int, default=SAMPLE_COUNT)
    sample.add_argument("--temperature", type=float, default=TEMPERATURE)
    sample.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    sample.add_argument("--zero-shot", action="store_true")
    sample.add_argument("--thinking", action="store_true")
    sample.add_argument("--limit", type=int, help="only the first N states (smoke tests)")

    execute = commands.add_parser("execute", help="run the sampled blocks in Lean and compute the metrics")
    execute.add_argument("--label", required=True)
    execute.add_argument("--pool-size", type=int, default=20)

    summarize = commands.add_parser("summarize", help="tabulate all models of the run")
    summarize.add_argument("--labels", nargs="*")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    paths = RunPaths(RUNS_DIRECTORY / arguments.run_name)
    paths.directory.mkdir(parents=True, exist_ok=True)
    match arguments.command:
        case "states":
            command_states(arguments, paths)
        case "sample":
            command_sample(arguments, paths)
        case "execute":
            command_execute(arguments, paths)
        case "summarize":
            command_summarize(arguments, paths)


if __name__ == "__main__":
    main()
