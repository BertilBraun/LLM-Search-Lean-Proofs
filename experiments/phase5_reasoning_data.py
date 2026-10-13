"""Phase 5 single-step reasoning data: prompt states, sampled thoughts and steps, Lean reward, rejection selection.

    python experiments/phase5_reasoning_data.py states --config experiments/configs/reasoning/phase5_sample_r1.toml \
        --run-name phase5_sample_r1                      # fix the prompt states, once
    python experiments/phase5_reasoning_data.py run --config ... --run-name phase5_sample_r1     # resumable
    python experiments/phase5_reasoning_data.py statistics --config ... --run-name phase5_sample_r1
    python experiments/phase5_reasoning_data.py select --config experiments/configs/reasoning/phase5_data_r1.toml \
        --name r1                                         # rejection-sampled SFT data

States: traced train-split steps (never validation, never miniF2F), at most `states_per_proof` per proof, sources
interleaved; states whose goals are prompts of the given SFT data sets are marked (statistics by SFT exposure).
`run` asks the served policy for k samples per state (the search's prompt and parsing, thinking on), executes every
distinct block on the rebuilt state in Lean and classifies it (`lean_search.reasoning.reward`), chunk by chunk: a
chunk's samples and records are written once complete, so an interrupted run resumes at its first chunk without
records (sampling runs one chunk ahead of Lean). The vLLM servers must already serve `policy.model` and the adapter
`policy.adapter`.
Outputs in $LEAN_SEARCH_RUNS/<run>/: config.toml, states.jsonl, chunks/<n>.{samples,records}.jsonl, chunks.jsonl
(progress) and summary/{statistics.json,README.md,config.toml}. `select` writes
$LEAN_SEARCH_DATA/reasoning/<name>/{train,validation}.jsonl and $LEAN_SEARCH_RUNS/phase5_data_<name>/summary/.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import json
import os
import subprocess
import time
import tomllib
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.corpora.records import read_traced_steps
from lean_search.corpora.tracing import stable_fraction
from lean_search.reasoning.compression import RewriteMode, open_rewriter, open_sufficiency_checker
from lean_search.reasoning.config import ReasoningRunConfig, load_reasoning_run_config
from lean_search.reasoning.dataset import (
    ReasoningDataConfig,
    ReasoningExample,
    ReasoningOrigin,
    interleaved,
    is_validation_proof,
    reasoning_example,
    replay_examples,
    select_samples,
    tokenize_reasoning_example,
    with_thinking_instruction,
    write_examples,
)
from lean_search.reasoning.pipeline import (
    ChunkProgress,
    open_executor,
    open_sampler,
    preloaded_header,
    run_chunks,
    value_remaining_steps,
    with_value_drops,
)
from lean_search.reasoning.records import RunDirectory, StateRecord, StateSamples, read_records, write_records
from lean_search.reasoning.shortening import (
    ShortenedReasoning,
    ShorteningConfig,
    ShorteningStatistics,
    short_reasoning_examples,
    shorten,
    shortening_statistics,
    shortening_targets,
)
from lean_search.reasoning.states import (
    ReasoningState,
    TracedSource,
    goals_digest,
    select_states,
    without_seen_states,
)
from lean_search.reasoning.statistics import RunStatistics, SampleGroup, run_statistics
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import markdown_table
from lean_search.training.sft_data import LengthStatistics, length_statistics, read_examples, shard_step_files
from lean_search.value.estimator import open_value_estimator

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))


@dataclass(frozen=True)
class Throughput:
    chunks: int
    sampled_chunks: int
    samples: int
    generated_tokens: int
    sampling_seconds: float
    execution_seconds: float
    samples_per_second: float
    generated_tokens_per_second: float
    lean_seconds_per_state: float


@dataclass(frozen=True)
class RunSummary:
    run_name: str
    git_revision: str
    config: ReasoningRunConfig
    statistics: RunStatistics
    throughput: Throughput


@dataclass(frozen=True)
class ExampleStatistics:
    examples: int
    prompt_tokens: LengthStatistics
    completion_tokens: LengthStatistics
    total_tokens: LengthStatistics


@dataclass(frozen=True)
class SourceCount:
    source: str
    examples: int


@dataclass(frozen=True)
class OriginCount:
    origin: ReasoningOrigin
    examples: int


@dataclass(frozen=True)
class DataSummary:
    name: str
    built: str
    git_revision: str
    config: ReasoningDataConfig
    states: int
    usable_states: int
    states_with_examples: int
    validation_states_with_examples: int
    train_reasoning: ExampleStatistics
    train_replay: ExampleStatistics
    validation_reasoning: ExampleStatistics
    validation_replay: ExampleStatistics
    train_reasoning_by_source: tuple[SourceCount, ...]
    train_reasoning_by_origin: tuple[OriginCount, ...]


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def run_directory(run_name: str) -> RunDirectory:
    return RunDirectory(RUNS_DIRECTORY / run_name)


def keep_config(arguments: argparse.Namespace, directory: RunDirectory) -> None:
    text = arguments.config.read_text(encoding="utf-8")
    kept = directory.path / "config.toml"
    if kept.exists() and kept.read_text(encoding="utf-8") != text:
        raise ValueError(f"{kept} differs from {arguments.config}; a run keeps one configuration.")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")


def command_states(arguments: argparse.Namespace, config: ReasoningRunConfig, directory: RunDirectory) -> None:
    if directory.states.exists():
        raise ValueError(f"{directory.states} exists; the state set is fixed once chosen.")
    keep_config(arguments, directory)
    seen_goals = frozenset(
        goals_digest(example.goals)
        for name in config.states.seen_sft_data
        for example in read_examples(DATA_DIRECTORY / "sft" / name / "train.jsonl")
    )
    if arguments.states_from:
        states = read_records(run_directory(arguments.states_from).states, ReasoningState)[arguments.states_skip :]
        copied = len(states)
        if config.states.unseen_only:
            states = without_seen_states(states, seen_goals)
        write_records(directory.states, states)
        print(
            f"{len(states)} of {copied} states of {arguments.states_from} (unseen only: "
            f"{config.states.unseen_only}) into {directory.states}"
        )
        return
    excluded = frozenset(
        state.identifier
        for run in config.states.excluded_runs
        for state in read_records(run_directory(run).states, ReasoningState)
    )
    match config.states.traced:
        case TracedSource.SNAPSHOT:
            step_files = [arguments.traced_directory / f"steps_{config.states.split}.jsonl"]
        case TracedSource.SHARDS:
            step_files = shard_step_files(arguments.traced_directory)
    steps = (step for path in step_files for step in read_traced_steps(path))
    states = select_states(steps, config.states, seen_goals, excluded)
    write_records(directory.states, states)
    by_source = Counter(state.source for state in states)
    seen = sum(state.seen_in_sft for state in states)
    print(f"{len(states)} states ({seen} seen in SFT data, {len(excluded)} excluded) into {directory.states}")
    for source, count in sorted(by_source.items()):
        print(f"  {source}: {count}")


async def unavailable_sampler(state: ReasoningState) -> StateSamples:
    raise RuntimeError(f"No policy server was opened, but {state.identifier} has no samples yet.")


def on_chunk_progress(directory: RunDirectory, progress: ChunkProgress) -> None:
    with (directory.path / "chunks.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(to_json(progress) + "\n")
    sampling = (
        "read back"
        if progress.sampling_seconds is None
        else f"sampled in {progress.sampling_seconds:.0f} s ({progress.samples / progress.sampling_seconds:.1f} "
        f"samples/s, {progress.generated_tokens / progress.sampling_seconds:.0f} tokens/s)"
    )
    print(
        f"chunk {progress.chunk + 1}/{progress.chunks}: {progress.states} states, {progress.samples} samples "
        f"{sampling}, executed in {progress.execution_seconds:.0f} s",
        flush=True,
    )


async def run_pipeline(config: ReasoningRunConfig, directory: RunDirectory, state_limit: int | None) -> None:
    states = read_records(directory.states, ReasoningState)[:state_limit]
    chunk_count = -(-len(states) // config.pipeline.chunk_states)
    done = set(directory.completed_chunks())
    needs_sampling = any(
        not directory.chunk_samples(chunk).exists() for chunk in range(chunk_count) if chunk not in done
    )
    async with contextlib.AsyncExitStack() as stack:
        sample_state = unavailable_sampler
        if needs_sampling:
            sampler = await stack.enter_async_context(open_sampler(config.policy, config.pipeline.requests_in_flight))
            sample_state = sampler.sample
        executor = await stack.enter_async_context(open_executor(preloaded_header(states), config.execution))
        remaining_steps = None
        if config.reward.value_progress:
            estimator = await stack.enter_async_context(open_value_estimator(config.value))
            remaining_steps = value_remaining_steps(estimator)

        async def execute(sampled: Sequence[StateSamples]) -> list[StateRecord]:
            records = await executor.execute(sampled)
            if remaining_steps is None:
                return records
            return list(await asyncio.gather(*(with_value_drops(record, remaining_steps) for record in records)))

        await run_chunks(
            directory,
            states,
            config.pipeline.chunk_states,
            sample_state,
            execute,
            lambda progress: on_chunk_progress(directory, progress),
        )


def command_run(arguments: argparse.Namespace, config: ReasoningRunConfig, directory: RunDirectory) -> None:
    keep_config(arguments, directory)
    if arguments.pool_size is not None:
        config = dataclasses.replace(
            config, execution=dataclasses.replace(config.execution, pool_size=arguments.pool_size)
        )
    started = time.monotonic()
    asyncio.run(run_pipeline(config, directory, arguments.state_limit))
    print(f"Run finished in {time.monotonic() - started:.0f} s", flush=True)
    command_statistics(arguments, config, directory)


def throughput(directory: RunDirectory, records: Sequence[StateRecord]) -> Throughput:
    progress_path = directory.path / "chunks.jsonl"
    progress = (
        [from_json_object(ChunkProgress, json.loads(line)) for line in progress_path.read_text("utf-8").splitlines()]
        if progress_path.exists()
        else []
    )
    sampled = [entry for entry in progress if entry.sampling_seconds is not None]
    samples = sum(entry.samples for entry in sampled)
    tokens = sum(entry.generated_tokens for entry in sampled)
    sampling_seconds = sum(entry.sampling_seconds or 0.0 for entry in sampled)
    lean_seconds = sum(execution.lean_seconds for record in records for execution in record.executions)
    return Throughput(
        chunks=len(directory.completed_chunks()),
        sampled_chunks=len(sampled),
        samples=samples,
        generated_tokens=tokens,
        sampling_seconds=sampling_seconds,
        execution_seconds=sum(entry.execution_seconds for entry in progress),
        samples_per_second=samples / sampling_seconds if sampling_seconds else 0.0,
        generated_tokens_per_second=tokens / sampling_seconds if sampling_seconds else 0.0,
        lean_seconds_per_state=lean_seconds / len(records) if records else 0.0,
    )


def percent(value: float) -> str:
    return f"{value:.1%}"


def group_rows(groups: Sequence[SampleGroup]) -> list[list[object]]:
    return [
        [
            group.label,
            group.states,
            group.samples,
            percent(group.success_rate),
            percent(group.any_success_rate),
            percent(group.fully_valid_rate),
            percent(group.closed_rate),
            percent(group.reference_rate),
            f"{group.mean_reasoning_tokens:.0f}",
            f"{group.mean_generated_tokens:.0f}",
        ]
        for group in groups
    ]


GROUP_HEADERS = [
    "group",
    "states",
    "samples",
    "success",
    "any success / state",
    "fully valid",
    "closed",
    "reference",
    "reasoning tokens",
    "generated tokens",
]


def render_run_summary(summary: RunSummary) -> str:
    config = summary.config
    statistics = summary.statistics
    policy = config.policy
    speed = summary.throughput
    reward = config.reward
    success_rule = (
        "the whole block applied and the goals are closed or equal the reference proof's next state"
        + (" or a later one" if reward.accept_later_reference_states else "")
        + (
            f", or the value model's h dropped by at least {reward.value_progress_margin:g}"
            if reward.value_progress
            else ""
        )
    )
    advanced = ", ".join(
        f"{steps} step(s): {count}" for steps, count in enumerate(statistics.reference_steps_advanced, 1)
    )
    selection = config.selection
    sections = [
        f"# Reasoning run `{summary.run_name}`",
        f"{statistics.states} traced train-split states, k={policy.sample_count} samples each from `{policy.model}`"
        f" (adapter `{policy.adapter}`), thinking {'on' if policy.thinking else 'off'}"
        + (f" with the system prompt addition “{policy.thinking_instruction}”" if policy.thinking_instruction else "")
        + ", temperature "
        f"{policy.temperature:g}, at most {policy.max_tokens} generated tokens (reasoning and block; truncation is a "
        f"failure). Every distinct block ran on its rebuilt state with `apply_block` "
        f"({config.execution.tactic_timeout_seconds:g} s wall clock). Success: {success_rule}. "
        f"{statistics.unusable_states} states whose replay failed are excluded. Git {summary.git_revision[:10]}.",
        "## Overview",
        markdown_table(GROUP_HEADERS, group_rows([statistics.overall])),
        f"Generated tokens per success: {statistics.generated_tokens_per_success:,.0f}; prompt tokens per state: "
        f"{statistics.mean_prompt_tokens:.0f}. Reference states reached: {advanced or 'none'}.",
        "## Outcomes",
        markdown_table(
            ["outcome", "samples", "share"],
            [[entry.outcome.value, entry.samples, percent(entry.share)] for entry in statistics.outcomes],
        ),
        "## Success against reasoning length",
        "Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.",
        markdown_table(GROUP_HEADERS, group_rows(statistics.by_reasoning_length)),
        "## By source",
        markdown_table(GROUP_HEADERS, group_rows(statistics.by_source)),
        "## By SFT exposure of the prompt state",
        markdown_table(GROUP_HEADERS, group_rows(statistics.by_sft_exposure)),
        "## Recovered answer format",
        "Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the "
        "non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders "
        "their training targets with the opening fence.",
        markdown_table(GROUP_HEADERS, group_rows([statistics.recovered_format])),
        "## Simulated generation caps",
        "The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, "
        "and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.",
        markdown_table(
            [
                "cap",
                "success",
                "any success / state",
                "tokens / sample",
                "tokens / success",
                "finished beyond cap",
                "their success",
            ],
            [
                [
                    entry.cap,
                    percent(entry.success_rate),
                    percent(entry.any_success_rate),
                    f"{entry.tokens_per_sample:.0f}",
                    f"{entry.tokens_per_success:,.0f}",
                    entry.finished_beyond_cap,
                    percent(entry.finished_beyond_cap_success_rate),
                ]
                for entry in statistics.caps
            ],
        ),
        "## Rejection selection",
        f"At most {selection.max_per_state} successes per state with at least {selection.min_reasoning_tokens} "
        f"reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: "
        f"{statistics.selection.examples:,} examples from {statistics.selection.states_with_examples:,} states, "
        f"reasoning tokens mean {statistics.selection.mean_reasoning_tokens:.0f}, median "
        f"{statistics.selection.median_reasoning_tokens:.0f}.",
        "## Throughput",
        markdown_table(
            ["quantity", "value"],
            [
                ["chunks (sampled in this run's log)", f"{speed.chunks} ({speed.sampled_chunks})"],
                ["samples / generated tokens", f"{speed.samples:,} / {speed.generated_tokens:,}"],
                ["sampling time", f"{speed.sampling_seconds / 60:.1f} min"],
                ["samples/s", f"{speed.samples_per_second:.1f}"],
                ["generated tokens/s", f"{speed.generated_tokens_per_second:,.0f}"],
                ["Lean execution time (overlaps sampling)", f"{speed.execution_seconds / 60:.1f} min"],
                ["Lean s / state", f"{speed.lean_seconds_per_state:.2f}"],
            ],
        ),
    ]
    return "\n\n".join(sections) + "\n"


def command_statistics(arguments: argparse.Namespace, config: ReasoningRunConfig, directory: RunDirectory) -> None:
    records = directory.read_all_records()
    statistics = run_statistics(records, config.reward, config.selection)
    summary = RunSummary(arguments.run_name, git_revision(), config, statistics, throughput(directory, records))
    directory.summary.mkdir(parents=True, exist_ok=True)
    (directory.summary / "statistics.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (directory.summary / "README.md").write_text(render_run_summary(summary), encoding="utf-8")
    (directory.summary / "config.toml").write_text(arguments.config.read_text(encoding="utf-8"), encoding="utf-8")
    overall = statistics.overall
    print(
        f"{len(records)} states, {overall.samples} samples: success {overall.success_rate:.1%}, any success "
        f"{overall.any_success_rate:.1%}, {statistics.selection.examples} selected examples; {directory.summary}",
        flush=True,
    )


def example_statistics(
    tokenizer: transformers.PreTrainedTokenizerBase, examples: Sequence[ReasoningExample]
) -> ExampleStatistics:
    tokenized = [tokenize_reasoning_example(tokenizer, example) for example in examples]
    return ExampleStatistics(
        examples=len(tokenized),
        prompt_tokens=length_statistics([example.prompt_token_count for example in tokenized]),
        completion_tokens=length_statistics([example.completion_token_count for example in tokenized]),
        total_tokens=length_statistics([example.token_count for example in tokenized]),
    )


def render_data_summary(summary: DataSummary) -> str:
    config = summary.config
    rows = [
        [name, entry.examples, entry.total_tokens.total, f"{entry.prompt_tokens.mean:.0f}"]
        + [f"{entry.completion_tokens.mean:.0f}", entry.completion_tokens.p90, entry.completion_tokens.maximum]
        for name, entry in (
            ("train reasoning", summary.train_reasoning),
            ("train replay (no thinking)", summary.train_replay),
            ("validation replay (first)", summary.validation_replay),
            ("validation reasoning", summary.validation_reasoning),
        )
    ]
    sections = [
        f"# Reasoning SFT data `{summary.name}`",
        f"Built {summary.built} (git {summary.git_revision[:10]}) from runs {', '.join(config.runs)}: "
        f"{summary.usable_states:,} usable of {summary.states:,} states, {summary.states_with_examples:,} with "
        f"selected examples. Per state at most {config.selection.max_per_state} successful samples with at least "
        f"{config.selection.min_reasoning_tokens} reasoning tokens, shortest reasoning first, distinct blocks before "
        f"repeated ones"
        + (
            f"; reasoning over {config.max_kept_reasoning_tokens} tokens only through a sufficient compression "
            f"(shortening `{config.shortening}`), states without a thinking success through rationalized steps"
            if config.max_kept_reasoning_tokens
            else ""
        )
        + f". Reasoning examples: the thinking prompt, completion = reasoning, `</think>`, block, end of "
        f"turn (loss on all of it). Replay: {config.replay_ratio:g} non-thinking examples of SFT data "
        f"`{config.replay_data}` per reasoning example. {config.validation_fraction:.0%} of the proofs are held out "
        f"({summary.validation_states_with_examples:,} states); validation lists the replay examples first, so the "
        "trainer's greedy-generation check measures the non-thinking mode.",
        markdown_table(
            ["part", "examples", "tokens", "prompt mean", "completion mean", "completion p90", "completion max"], rows
        ),
        markdown_table(
            ["source", "train reasoning examples"],
            [[entry.source, entry.examples] for entry in summary.train_reasoning_by_source],
        ),
        markdown_table(
            ["reasoning origin", "train reasoning examples"],
            [[entry.origin.value, entry.examples] for entry in summary.train_reasoning_by_origin],
        ),
    ]
    return "\n\n".join(sections) + "\n"


def origin_counts(examples: Sequence[ReasoningExample]) -> tuple[OriginCount, ...]:
    counts = Counter(example.origin for example in examples)
    return tuple(OriginCount(origin, counts[origin]) for origin in ReasoningOrigin if counts[origin])


def shortened_records(runs: Sequence[str], name: str) -> dict[str, list[ShortenedReasoning]]:
    by_state: dict[str, list[ShortenedReasoning]] = defaultdict(list)
    for run in runs:
        directory = run_directory(run)
        for chunk in directory.completed_chunks():
            path = directory.chunk_shortened(chunk, name)
            if path.exists():
                for entry in read_records(path, ShortenedReasoning):
                    by_state[entry.state_identifier].append(entry)
    return by_state


async def shorten_run(
    config: ReasoningRunConfig,
    shortening: ShorteningConfig,
    directory: RunDirectory,
    name: str,
    chunk_limit: int | None,
) -> None:
    others = {
        record.sampled.state.identifier: record
        for run in shortening.rationalize_runs
        for record in run_directory(run).read_all_records()
    }
    pending = [
        chunk
        for chunk in directory.completed_chunks()[:chunk_limit]
        if not directory.chunk_shortened(chunk, name).exists()
    ]
    states = read_records(directory.states, ReasoningState)
    async with contextlib.AsyncExitStack() as stack:
        executor = await stack.enter_async_context(open_executor(preloaded_header(states), config.execution))
        rewriter = await stack.enter_async_context(open_rewriter(shortening.rewrite))
        checker = await stack.enter_async_context(
            open_sufficiency_checker(
                config.policy,
                shortening.sufficiency,
                config.reward,
                executor,
                config.pipeline.requests_in_flight,
            )
        )
        for chunk in pending:
            records = read_records(directory.chunk_records(chunk), StateRecord)
            targets = shortening_targets(records, others, config.reward, config.selection, shortening)
            started = time.monotonic()
            shortened = await shorten(targets, rewriter, checker)
            write_records(directory.chunk_shortened(chunk, name), shortened)
            passing = sum(entry.shortest_sufficient() is not None for entry in shortened)
            print(
                f"chunk {chunk}: {len(targets)} targets, {passing} with a sufficient rewrite "
                f"({time.monotonic() - started:.0f} s)",
                flush=True,
            )


@dataclass(frozen=True)
class RewriteExample:
    mode: RewriteMode
    tactic_block: str
    original_reasoning: str
    rewrite: str
    sufficient: bool


@dataclass(frozen=True)
class ShorteningSummary:
    run_name: str
    name: str
    git_revision: str
    config: ShorteningConfig
    modes: tuple[ShorteningStatistics, ...]
    states: int
    states_with_examples: int
    examples_by_origin: tuple[OriginCount, ...]
    rewrite_examples: tuple[RewriteExample, ...]


EXAMPLE_CHARACTERS = 600


def rewrite_examples(entries: Sequence[ShortenedReasoning], count: int) -> tuple[RewriteExample, ...]:
    """A fixed spread of checked rewrites, half sufficient, for reading their quality."""
    checked = [
        RewriteExample(
            entry.mode, entry.tactic_block, entry.original_reasoning, checked.rewrite.text, checked.sufficient
        )
        for entry in sorted(entries, key=lambda entry: stable_fraction(entry.state_identifier, "rewrite examples"))
        for checked in entry.rewrites
        if checked.check is not None
    ]
    sufficient = [example for example in checked if example.sufficient][: count // 2]
    insufficient = [example for example in checked if not example.sufficient][: count - len(sufficient)]
    return (*sufficient, *insufficient)


def render_rewrite_example(example: RewriteExample) -> str:
    original = example.original_reasoning[:EXAMPLE_CHARACTERS] + (
        " …" if len(example.original_reasoning) > EXAMPLE_CHARACTERS else ""
    )
    lines = [
        f"### {example.mode.value}, {'sufficient' if example.sufficient else 'insufficient'}",
        f"Step: `{example.tactic_block}`",
    ]
    if original:
        lines.append(f"Original: {original}")
    lines.append(f"Rewrite: {example.rewrite}")
    return "\n\n".join(lines)


def render_shortening_summary(summary: ShorteningSummary) -> str:
    config = summary.config
    rewrite = config.rewrite
    rows = [
        [
            entry.mode.value,
            entry.targets,
            entry.rewrites,
            ", ".join(f"{count.defect.value} {count.rewrites}" for count in entry.defects) or "none",
            entry.checked_rewrites,
            entry.sufficient_rewrites,
            percent(entry.pass_rate),
            percent(entry.check_success_rate),
            f"{entry.mean_original_tokens:.0f}",
            f"{entry.mean_shortened_tokens:.0f}",
            f"{entry.median_compression_ratio:.2f}",
        ]
        for entry in summary.modes
    ]
    sections = [
        f"# Short reasoning of run `{summary.run_name}` (`{summary.name}`)",
        f"Successful samples with more than {config.max_kept_reasoning_tokens} reasoning tokens (among the first "
        f"{config.candidates_per_state} successes of a state in selection order) are rewritten by `{rewrite.model}` "
        f"(adapter `{rewrite.adapter}`, no thinking, {rewrite.candidates} candidates at temperature "
        f"{rewrite.temperature:g}, asked for at most {rewrite.target_tokens} tokens, accepted up to "
        f"{rewrite.max_accepted_tokens}). Each well-formed rewrite is prefilled as the policy's thoughts, the policy "
        f"samples {config.sufficiency.sample_count} steps at temperature {config.sufficiency.temperature:g}, and the "
        "rewrite is sufficient if one of them succeeds in Lean. Rationalized: successful steps of "
        f"{', '.join(config.rationalize_runs) or 'no run'} for states without a thinking success, given a reasoning "
        f"the same way. Git {summary.git_revision[:10]}.",
        markdown_table(
            [
                "mode",
                "targets",
                "rewrites",
                "defects",
                "checked",
                "sufficient",
                "targets passing",
                "check samples succeeding",
                "original tokens",
                "shortest sufficient tokens",
                "median ratio",
            ],
            rows,
        ),
        f"Examples the data selection would take: {summary.states_with_examples:,} of {summary.states:,} states; "
        + (", ".join(f"{entry.origin.value} {entry.examples:,}" for entry in summary.examples_by_origin) or "none")
        + ".",
        "## Example rewrites",
        *(render_rewrite_example(example) for example in summary.rewrite_examples),
    ]
    return "\n\n".join(sections) + "\n"


def command_shorten(arguments: argparse.Namespace, config: ReasoningRunConfig, directory: RunDirectory) -> None:
    shortening = config.shortening
    if arguments.pool_size is not None:
        config = dataclasses.replace(
            config, execution=dataclasses.replace(config.execution, pool_size=arguments.pool_size)
        )
    if arguments.shortening_config:
        text = arguments.shortening_config.read_text(encoding="utf-8")
        shortening = from_json_object(ShorteningConfig, tomllib.loads(text))
    started = time.monotonic()
    asyncio.run(shorten_run(config, shortening, directory, arguments.name, arguments.chunks))
    print(f"Shortening finished in {time.monotonic() - started:.0f} s", flush=True)
    shortened = shortened_records([arguments.run_name], arguments.name)
    entries = [entry for state_entries in shortened.values() for entry in state_entries]
    records = [record for record in directory.read_all_records() if record.usable]
    examples_by_state = [
        short_reasoning_examples(
            record,
            shortened.get(record.sampled.state.identifier, ()),
            config.reward,
            config.selection,
            shortening.max_kept_reasoning_tokens,
        )
        for record in records
        if record.sampled.state.identifier in shortened or not arguments.chunks
    ]
    summary = ShorteningSummary(
        run_name=arguments.run_name,
        name=arguments.name,
        git_revision=git_revision(),
        config=shortening,
        modes=tuple(shortening_statistics(entries, mode, shortening.sufficiency.sample_count) for mode in RewriteMode),
        states=len(records),
        states_with_examples=sum(bool(examples) for examples in examples_by_state),
        examples_by_origin=origin_counts([example for examples in examples_by_state for example in examples]),
        rewrite_examples=rewrite_examples(entries, 12),
    )
    directory.summary.mkdir(parents=True, exist_ok=True)
    (directory.summary / f"shortening_{arguments.name}.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_shortening_summary(summary)
    (directory.summary / f"shortening_{arguments.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


def command_select(arguments: argparse.Namespace) -> None:
    config = from_json_object(ReasoningDataConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    output = DATA_DIRECTORY / "reasoning" / arguments.name
    if output.exists():
        raise ValueError(f"{output} exists; data sets are built once.")
    records = [record for run in config.runs for record in run_directory(run).read_all_records()]
    usable = [record for record in records if record.usable]
    shortened_by_state = shortened_records(config.runs, config.shortening) if config.max_kept_reasoning_tokens else {}
    train_reasoning: list[ReasoningExample] = []
    validation_reasoning: list[ReasoningExample] = []
    validation_states = 0
    states_with_examples = 0
    for record in usable:
        state = record.sampled.state
        if config.max_kept_reasoning_tokens:
            examples = short_reasoning_examples(
                record,
                shortened_by_state.get(state.identifier, ()),
                config.reward,
                config.selection,
                config.max_kept_reasoning_tokens,
            )
        else:
            examples = [
                reasoning_example(record.sampled, sample)
                for sample in select_samples(record, config.reward, config.selection)
            ]
        examples = with_thinking_instruction(examples, config.thinking_instruction)
        states_with_examples += bool(examples)
        if is_validation_proof(state.step.proof_identifier, config.validation_fraction, config.seed):
            validation_reasoning += examples
            validation_states += bool(examples)
        else:
            train_reasoning += examples
    replay_directory = DATA_DIRECTORY / "sft" / config.replay_data
    train_replay = replay_examples(
        read_examples(replay_directory / "train.jsonl"), round(config.replay_ratio * len(train_reasoning)), config.seed
    )
    validation_replay = replay_examples(
        read_examples(replay_directory / "validation.jsonl"), config.validation_replay_examples, config.seed
    )
    write_examples(output / "train.jsonl", interleaved([*train_reasoning, *train_replay], config.seed))
    # The trainer's greedy-generation check reads the first validation examples: those measure the non-thinking mode.
    write_examples(output / "validation.jsonl", [*validation_replay, *validation_reasoning])
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.tokenizer)
    summary = DataSummary(
        name=arguments.name,
        built=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=git_revision(),
        config=config,
        states=len(records),
        usable_states=len(usable),
        states_with_examples=states_with_examples,
        validation_states_with_examples=validation_states,
        train_reasoning=example_statistics(tokenizer, train_reasoning),
        train_replay=example_statistics(tokenizer, train_replay),
        validation_reasoning=example_statistics(tokenizer, validation_reasoning),
        validation_replay=example_statistics(tokenizer, validation_replay),
        train_reasoning_by_source=tuple(
            SourceCount(source, count)
            for source, count in sorted(Counter(example.source for example in train_reasoning).items())
        ),
        train_reasoning_by_origin=origin_counts(train_reasoning),
    )
    summary_directory = run_directory(arguments.run_name or f"phase5_data_{arguments.name}").summary
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (summary_directory / "README.md").write_text(render_data_summary(summary), encoding="utf-8")
    (summary_directory / "config.toml").write_text(arguments.config.read_text(encoding="utf-8"), encoding="utf-8")
    print(render_data_summary(summary), flush=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    states = commands.add_parser("states", help="choose the fixed prompt states")
    states.add_argument("--config", type=Path, required=True)
    states.add_argument("--run-name", required=True)
    states.add_argument("--traced-directory", type=Path, default=DATA_DIRECTORY / "traced")
    states.add_argument("--states-from", help="reuse another run's states instead of choosing them from [states]")
    states.add_argument("--states-skip", type=int, default=0, help="with --states-from: drop the first N (a shard)")

    run = commands.add_parser("run", help="sample, execute and classify, chunk by chunk (resumable)")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--run-name", required=True)
    run.add_argument("--state-limit", type=int, help="only the first N states (pilots and smoke tests)")
    run.add_argument("--pool-size", type=int, help="overrides execution.pool_size")

    statistics = commands.add_parser("statistics", help="summarize the run's records")
    statistics.add_argument("--config", type=Path, required=True)
    statistics.add_argument("--run-name", required=True)

    shorten_command = commands.add_parser("shorten", help="compress long successful reasoning, check it (resumable)")
    shorten_command.add_argument("--config", type=Path, required=True)
    shorten_command.add_argument("--run-name", required=True)
    shorten_command.add_argument("--name", default="default", help="names this shortening's records and summary")
    shorten_command.add_argument(
        "--shortening-config", type=Path, help="a ShorteningConfig TOML instead of the run config's [shortening]"
    )
    shorten_command.add_argument("--chunks", type=int, help="only the first N chunks (a quality pilot)")
    shorten_command.add_argument("--pool-size", type=int, help="overrides execution.pool_size")

    select = commands.add_parser("select", help="build a rejection-sampled SFT data set (config: ReasoningDataConfig)")
    select.add_argument("--config", type=Path, required=True)
    select.add_argument("--name", required=True)
    select.add_argument("--run-name", help="where the summary goes (default: phase5_data_<name>)")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.command == "select":
        command_select(arguments)
        return
    config = load_reasoning_run_config(arguments.config)
    directory = run_directory(arguments.run_name)
    match arguments.command:
        case "states":
            command_states(arguments, config, directory)
        case "run":
            command_run(arguments, config, directory)
        case "statistics":
            command_statistics(arguments, config, directory)
        case "shorten":
            command_shorten(arguments, config, directory)


if __name__ == "__main__":
    main()
