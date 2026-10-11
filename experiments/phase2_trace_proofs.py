"""Trace the selected public proofs step by step in the pinned Lean environment, resumable by shard."""

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import json
import logging
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.corpora.normalize import short_hash
from lean_search.corpora.pipeline import LengthDistribution, length_distribution
from lean_search.corpora.records import (
    DataSplit,
    Record,
    TracedProof,
    TracePath,
    TraceStatus,
    read_proof_records,
    read_traced_proofs,
    read_traced_steps,
    write_jsonl,
)
from lean_search.corpora.tracing import (
    EXCLUDED_SOURCES,
    TRACE_ORDER,
    ProofTrace,
    TracingLimits,
    TracingShard,
    plan_shards,
    statement_key,
    trace_shards,
)
from lean_search.lean import LeanReplConfig
from lean_search.search.summary import markdown_table

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
SELECTION = DATA_DIRECTORY / "normalized" / "proofs" / "selected_for_tracing.jsonl"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase2_tracing"
PARTS = ("pilot", "main")
SEARCH_PROCESS_PATTERN = "run_search.py"
SEARCH_POLL_SECONDS = 20.0
COMMAND_TIMEOUT_SECONDS = 120.0
SEARCH_STEP_SECONDS = 20.0
FAILURE_REASONS_PER_SOURCE = 8
DISAGREEMENTS_SHOWN = 20
REMAINING_STEP_BUCKETS = ((1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 15), (16, 31), (32, None))
GOAL_COUNT_BUCKETS = ((0, 0), (1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, None))
STEP_CHARACTER_BUCKETS = ((0, 10), (11, 20), (21, 50), (51, 100), (101, 200), (201, 500), (501, 1000), (1001, None))
_QUOTED = re.compile(r"'[^'\n]*'")
_NUMBER = re.compile(r"\d+")
_PARSE_POSITION = re.compile(r"^<input>:\d+:\d+:")
logger = logging.getLogger("phase2_trace_proofs")


@dataclass(frozen=True)
class OutputPaths:
    directory: Path

    @property
    def plan(self) -> Path:
        return self.directory / "plan.json"

    @property
    def invocations(self) -> Path:
        return self.directory / "invocations.jsonl"

    @property
    def shard_log(self) -> Path:
        return self.directory / "shard_log.jsonl"

    def steps(self, shard_key: str) -> Path:
        return self.directory / "shards" / f"{shard_key}.steps.jsonl"

    def proofs(self, shard_key: str) -> Path:
        return self.directory / "shards" / f"{shard_key}.proofs.jsonl"

    def is_done(self, shard_key: str) -> bool:
        return self.proofs(shard_key).exists()

    def merged_steps(self, split: DataSplit) -> Path:
        return self.directory / f"steps_{split}.jsonl"

    @property
    def merged_proofs(self) -> Path:
        return self.directory / "proofs.jsonl"


@dataclass(frozen=True)
class PlannedShard:
    key: str
    proofs: int
    identifier_digest: str


@dataclass(frozen=True)
class Invocation:
    invocation: str
    git_revision: str
    git_dirty: bool
    pool_size: int
    parts: list[str]
    sources: list[str]
    heartbeats: int
    timeout_seconds: float
    pending_shards: int
    pending_proofs: int


@dataclass(frozen=True)
class ShardLogEntry:
    invocation: str
    shard: str
    pool_size: int
    proofs: int
    complete_proofs: int
    training_steps: int
    tactic_calls: int
    lean_seconds: float
    seconds_since_start: float


@dataclass(frozen=True)
class SourceSummary:
    source: str
    planned_proofs: int
    attempted: int
    statuses: dict[str, int]
    completion_rate: float
    block_fallbacks: int
    block_fallbacks_completed: int
    trailing_steps_after_closure: int
    failures_checked_as_whole_proofs: int
    failures_compiling_as_whole_proofs: int
    complete_proofs_with_slow_steps: int
    training_steps: int
    mean_training_steps_per_complete_proof: float
    lean_seconds: float
    failure_reasons: dict[str, int]


@dataclass(frozen=True)
class SplitCounts:
    complete_proofs: int
    statements: int
    steps: int


@dataclass(frozen=True)
class VerificationDisagreement:
    proof_identifier: str
    problems: list[str]


@dataclass(frozen=True)
class VerificationSummary:
    sampled_complete_proofs: int
    verified: int
    plain_verified: int
    agreement_rate: float
    disagreements: list[VerificationDisagreement]


@dataclass(frozen=True)
class InvocationThroughput:
    invocation: str
    pool_size: int
    shards: int
    proofs: int
    training_steps: int
    tactic_calls: int
    wall_seconds: float
    proofs_per_second: float
    training_steps_per_second: float
    tactic_calls_per_second: float
    lean_seconds_per_process_second: float


@dataclass(frozen=True)
class TracingSummary:
    parts: list[str]
    heartbeats: list[int]
    shards_traced: int
    shards_planned: int
    proofs_planned: int
    sources: list[SourceSummary]
    total: SourceSummary
    splits: dict[str, SplitCounts]
    remaining_steps: dict[str, LengthDistribution]
    goals_before: LengthDistribution
    step_characters: LengthDistribution
    verification: VerificationSummary
    throughput: list[InvocationThroughput]


@dataclass
class SourceAccumulator:
    planned_proofs: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    failure_reasons: Counter[str] = field(default_factory=Counter)
    block_fallbacks: int = 0
    block_fallbacks_completed: int = 0
    trailing_steps_after_closure: int = 0
    failures_checked_as_whole_proofs: int = 0
    failures_compiling_as_whole_proofs: int = 0
    complete_proofs_with_slow_steps: int = 0
    training_steps: int = 0
    lean_seconds: float = 0.0

    def add(self, proof: TracedProof, training_steps: int) -> None:
        self.statuses[proof.status] += 1
        if proof.status is not TraceStatus.COMPLETE:
            self.failure_reasons[failure_reason(proof)] += 1
        self.block_fallbacks += proof.path is TracePath.BLOCK
        self.block_fallbacks_completed += proof.path is TracePath.BLOCK and proof.status is TraceStatus.COMPLETE
        self.trailing_steps_after_closure += (
            proof.status is TraceStatus.COMPLETE and len(proof.applied_steps) > training_steps
        )
        self.failures_checked_as_whole_proofs += proof.whole_proof_verified is not None
        self.failures_compiling_as_whole_proofs += proof.whole_proof_verified is True
        self.complete_proofs_with_slow_steps += proof.status is TraceStatus.COMPLETE and any(
            seconds > SEARCH_STEP_SECONDS for seconds in proof.step_seconds
        )
        self.training_steps += training_steps
        self.lean_seconds += proof.elapsed_seconds

    def merge(self, other: "SourceAccumulator") -> None:
        self.planned_proofs += other.planned_proofs
        self.statuses.update(other.statuses)
        self.failure_reasons.update(other.failure_reasons)
        self.block_fallbacks += other.block_fallbacks
        self.block_fallbacks_completed += other.block_fallbacks_completed
        self.trailing_steps_after_closure += other.trailing_steps_after_closure
        self.failures_checked_as_whole_proofs += other.failures_checked_as_whole_proofs
        self.failures_compiling_as_whole_proofs += other.failures_compiling_as_whole_proofs
        self.complete_proofs_with_slow_steps += other.complete_proofs_with_slow_steps
        self.training_steps += other.training_steps
        self.lean_seconds += other.lean_seconds

    def summary(self, source: str) -> SourceSummary:
        attempted = sum(self.statuses.values())
        complete = self.statuses[TraceStatus.COMPLETE]
        return SourceSummary(
            source=source,
            planned_proofs=self.planned_proofs,
            attempted=attempted,
            statuses={str(status): self.statuses[status] for status in TraceStatus},
            completion_rate=round(complete / attempted, 4) if attempted else 0.0,
            block_fallbacks=self.block_fallbacks,
            block_fallbacks_completed=self.block_fallbacks_completed,
            trailing_steps_after_closure=self.trailing_steps_after_closure,
            failures_checked_as_whole_proofs=self.failures_checked_as_whole_proofs,
            failures_compiling_as_whole_proofs=self.failures_compiling_as_whole_proofs,
            complete_proofs_with_slow_steps=self.complete_proofs_with_slow_steps,
            training_steps=self.training_steps,
            mean_training_steps_per_complete_proof=round(self.training_steps / complete, 2) if complete else 0.0,
            lean_seconds=round(self.lean_seconds, 1),
            failure_reasons=dict(self.failure_reasons.most_common(FAILURE_REASONS_PER_SOURCE)),
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", default="pilot,main", help=f"comma-separated subset of {', '.join(PARTS)}")
    parser.add_argument("--sources", help="comma-separated sources (default: all in tracing order)")
    parser.add_argument("--pool-size", type=int, default=16)
    parser.add_argument("--heartbeats", type=int, default=200_000)
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="wall-clock backstop per step")
    parser.add_argument("--pilot-size", type=int, default=2000, help="proofs per source in the pilot part")
    parser.add_argument("--shard-size", type=int, default=1000)
    parser.add_argument("--output-directory", type=Path, default=DATA_DIRECTORY / "traced")
    parser.add_argument("--summarize", action="store_true", help="summarize finished shards instead of tracing")
    parser.add_argument("--merge", action="store_true", help="with --summarize: write merged steps and proofs files")
    parser.add_argument("--summary-name", default="summary", help="file stem under the run's summary directory")
    return parser.parse_args()


def selected_names(text: str | None, allowed: tuple[str, ...]) -> list[str]:
    if text is None:
        return list(allowed)
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = sorted(set(names) - set(allowed))
    if unknown:
        raise ValueError(f"Unknown names {unknown}; choose from {allowed}")
    return names


def shard_part(shard_key: str) -> str:
    return shard_key.rsplit("/", 1)[1].split("_", 1)[0]


def planned_shard(shard: TracingShard) -> PlannedShard:
    digest = short_hash("\n".join(record.identifier for record in shard.records))
    return PlannedShard(shard.key, len(shard.records), digest)


def load_plan(paths: OutputPaths, pilot_size: int, shard_size: int) -> list[TracingShard]:
    shards = plan_shards(read_proof_records(SELECTION), pilot_size, shard_size)
    plan = [dataclasses.asdict(planned_shard(shard)) for shard in shards]
    if paths.plan.exists():
        if json.loads(paths.plan.read_text(encoding="utf-8")) != plan:
            raise ValueError(f"The shard plan differs from {paths.plan}; use the original sizes or a new directory.")
    else:
        paths.plan.parent.mkdir(parents=True, exist_ok=True)
        paths.plan.write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return shards


def git_state() -> tuple[str, bool]:
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
        ).stdout.strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


def append_json_line(path: Path, record: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def write_atomically(path: Path, records: Sequence[Record]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    write_jsonl(temporary, records)
    os.replace(temporary, path)


def write_shard(paths: OutputPaths, shard: TracingShard, traces: list[ProofTrace]) -> None:
    order = {record.identifier: index for index, record in enumerate(shard.records)}
    traces = sorted(traces, key=lambda trace: order[trace.proof.proof_identifier])
    assert [trace.proof.proof_identifier for trace in traces] == list(order), shard.key
    # The proofs file marks the shard as done, so it is written last.
    write_atomically(paths.steps(shard.key), [step for trace in traces for step in trace.steps])
    write_atomically(paths.proofs(shard.key), [trace.proof for trace in traces])


async def search_is_running() -> bool:
    process = await asyncio.create_subprocess_exec(
        "pgrep", "-f", SEARCH_PROCESS_PATTERN, stdout=asyncio.subprocess.DEVNULL
    )
    return await process.wait() == 0


async def watch_search_runs(may_proceed: asyncio.Event) -> None:
    was_running: bool | None = None
    while True:
        running = await search_is_running()
        if running != was_running:
            state = "paused" if running else "allowed"
            logger.info("Search run (%s) active: %s; new batches %s", SEARCH_PROCESS_PATTERN, running, state)
            was_running = running
        if running:
            may_proceed.clear()
        else:
            may_proceed.set()
        await asyncio.sleep(SEARCH_POLL_SECONDS)


async def run_tracing(
    shards: list[TracingShard], paths: OutputPaths, pool_size: int, limits: TracingLimits, invocation: str
) -> None:
    config = LeanReplConfig(
        tactic_heartbeats=limits.heartbeats,
        tactic_timeout_seconds=limits.timeout_seconds,
        command_timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )
    pending_proofs = sum(len(shard.records) for shard in shards)
    totals: Counter[str] = Counter()
    started = time.monotonic()

    async def on_shard_traced(shard: TracingShard, traces: list[ProofTrace]) -> None:
        await asyncio.to_thread(write_shard, paths, shard, traces)
        entry = ShardLogEntry(
            invocation=invocation,
            shard=shard.key,
            pool_size=pool_size,
            proofs=len(traces),
            complete_proofs=sum(trace.proof.status is TraceStatus.COMPLETE for trace in traces),
            training_steps=sum(len(trace.steps) for trace in traces),
            tactic_calls=sum(len(trace.proof.step_seconds) + 1 for trace in traces),
            lean_seconds=round(sum(trace.proof.elapsed_seconds for trace in traces), 2),
            seconds_since_start=round(time.monotonic() - started, 2),
        )
        append_json_line(paths.shard_log, entry)
        totals.update(proofs=entry.proofs, complete=entry.complete_proofs, steps=entry.training_steps)
        rate = totals["proofs"] / entry.seconds_since_start
        logger.info(
            "%s: %d/%d complete, %d steps | %d/%d proofs, %.0f%% complete, %.2f proofs/s, %.1f steps/s, ETA %.1f h",
            shard.key,
            entry.complete_proofs,
            entry.proofs,
            entry.training_steps,
            totals["proofs"],
            pending_proofs,
            100 * totals["complete"] / totals["proofs"],
            rate,
            totals["steps"] / entry.seconds_since_start,
            (pending_proofs - totals["proofs"]) / rate / 3600,
        )

    may_proceed = asyncio.Event()
    watcher = asyncio.create_task(watch_search_runs(may_proceed))
    try:
        for source in TRACE_ORDER:
            source_shards = [shard for shard in shards if shard.source == source]
            if source_shards:
                await may_proceed.wait()
                logger.info("Tracing %d shards of %s with %d processes", len(source_shards), source, pool_size)
                await trace_shards(source_shards, pool_size, config, limits, on_shard_traced, may_proceed)
    finally:
        watcher.cancel()


def message_category(message: str) -> str:
    first_line = message.strip().split("\n", 1)[0]
    if first_line.startswith("Forbidden tokens:"):
        return first_line
    first_line = _PARSE_POSITION.sub("parse error:", first_line)
    return _NUMBER.sub("N", _QUOTED.sub("'_'", first_line))[:90]


def failure_reason(proof: TracedProof) -> str:
    match proof.status:
        case TraceStatus.REPL_FAILURE:
            return f"repl_failure: {proof.repl_failure_kind}"
        case TraceStatus.TIMEOUT if "wall-clock" in proof.failure_message:
            return "timeout: wall clock"
        case TraceStatus.TIMEOUT:
            return "timeout: heartbeats"
        case _ if proof.whole_proof_verified:
            return f"{proof.status}, whole proof compiles: {message_category(proof.failure_message)}"
        case _ if proof.whole_proof_problems:
            return f"{proof.status}: {message_category(proof.whole_proof_problems[0])}"
        case TraceStatus.START_FAILURE | TraceStatus.STEP_ERROR:
            return f"{proof.status}: {message_category(proof.failure_message)}"
        case _:
            return str(proof.status)


def throughput(paths: OutputPaths, shard_keys: set[str]) -> list[InvocationThroughput]:
    if not paths.shard_log.exists():
        return []
    entries: dict[str, list[ShardLogEntry]] = defaultdict(list)
    with paths.shard_log.open(encoding="utf-8") as lines:
        for line in lines:
            entry = ShardLogEntry(**json.loads(line))
            if entry.shard in shard_keys:
                entries[entry.invocation].append(entry)
    results = []
    for invocation, invocation_entries in entries.items():
        wall_seconds = max(entry.seconds_since_start for entry in invocation_entries)
        pool_size = invocation_entries[0].pool_size
        proofs = sum(entry.proofs for entry in invocation_entries)
        steps = sum(entry.training_steps for entry in invocation_entries)
        tactic_calls = sum(entry.tactic_calls for entry in invocation_entries)
        lean_seconds = sum(entry.lean_seconds for entry in invocation_entries)
        results.append(
            InvocationThroughput(
                invocation=invocation,
                pool_size=pool_size,
                shards=len(invocation_entries),
                proofs=proofs,
                training_steps=steps,
                tactic_calls=tactic_calls,
                wall_seconds=round(wall_seconds, 1),
                proofs_per_second=round(proofs / wall_seconds, 3),
                training_steps_per_second=round(steps / wall_seconds, 2),
                tactic_calls_per_second=round(tactic_calls / wall_seconds, 2),
                lean_seconds_per_process_second=round(lean_seconds / wall_seconds / pool_size, 3),
            )
        )
    return results


def summarize(shards: list[TracingShard], paths: OutputPaths, merge: bool, parts: list[str]) -> TracingSummary:
    accumulators: dict[str, SourceAccumulator] = defaultdict(SourceAccumulator)
    for shard in shards:
        accumulators[shard.source].planned_proofs += len(shard.records)
    done = [shard for shard in shards if paths.is_done(shard.key)]
    split_proofs: Counter[str] = Counter()
    split_steps: Counter[str] = Counter()
    split_statements: dict[str, set[str]] = defaultdict(set)
    remaining_steps: dict[str, list[int]] = defaultdict(list)
    goals_before: list[int] = []
    step_characters: list[int] = []
    heartbeats: set[int] = set()
    sampled = verified = plain_verified = 0
    disagreements: list[VerificationDisagreement] = []
    with contextlib.ExitStack() as stack:
        merged_steps = {
            split: stack.enter_context(paths.merged_steps(split).open("w", encoding="utf-8"))
            for split in (DataSplit if merge else ())
        }
        merged_proofs = stack.enter_context(paths.merged_proofs.open("w", encoding="utf-8")) if merge else None
        for shard in done:
            training_steps: Counter[str] = Counter()
            for step in read_traced_steps(paths.steps(shard.key)):
                training_steps[step.proof_identifier] += 1
                split_steps[step.split] += 1
                remaining_steps[step.split].append(step.remaining_steps)
                goals_before.append(len(step.goals_before))
                step_characters.append(len(step.step))
                if merge:
                    merged_steps[step.split].write(json.dumps(dataclasses.asdict(step), ensure_ascii=False) + "\n")
            for proof in read_traced_proofs(paths.proofs(shard.key)):
                accumulators[proof.source].add(proof, training_steps[proof.proof_identifier])
                heartbeats.add(proof.heartbeats)
                if proof.status is TraceStatus.COMPLETE:
                    split_proofs[proof.split] += 1
                    split_statements[proof.split].add(statement_key(proof.formal_statement))
                if proof.verified is not None:
                    sampled += 1
                    verified += proof.verified
                    plain_verified += bool(proof.plain_verified)
                    if not proof.verified and len(disagreements) < DISAGREEMENTS_SHOWN:
                        disagreements.append(
                            VerificationDisagreement(proof.proof_identifier, list(proof.verification_problems[:3]))
                        )
                if merged_proofs is not None:
                    merged_proofs.write(json.dumps(dataclasses.asdict(proof), ensure_ascii=False) + "\n")
    total = SourceAccumulator()
    for accumulator in accumulators.values():
        total.merge(accumulator)
    all_remaining = [value for values in remaining_steps.values() for value in values]
    return TracingSummary(
        parts=parts,
        heartbeats=sorted(heartbeats),
        shards_traced=len(done),
        shards_planned=len(shards),
        proofs_planned=sum(len(shard.records) for shard in shards),
        sources=[accumulators[source].summary(source) for source in TRACE_ORDER if source in accumulators],
        total=total.summary("total"),
        splits={
            str(split): SplitCounts(split_proofs[split], len(split_statements[split]), split_steps[split])
            for split in DataSplit
        },
        remaining_steps={
            "all": length_distribution(all_remaining, REMAINING_STEP_BUCKETS),
            **{str(split): length_distribution(remaining_steps[split], REMAINING_STEP_BUCKETS) for split in DataSplit},
        },
        goals_before=length_distribution(goals_before, GOAL_COUNT_BUCKETS),
        step_characters=length_distribution(step_characters, STEP_CHARACTER_BUCKETS),
        verification=VerificationSummary(
            sampled, verified, plain_verified, round(verified / sampled, 4) if sampled else 0.0, disagreements
        ),
        throughput=throughput(paths, {shard.key for shard in done}),
    )


def _distribution_rows(
    distributions: dict[str, LengthDistribution], buckets: tuple[tuple[int, int | None], ...]
) -> tuple[list[str], list[list[object]]]:
    labels = [str(low) if low == high else f"{low}+" if high is None else f"{low}-{high}" for low, high in buckets]
    headers = ["", "count", "mean", "p50", "p90", "p99", "max", *labels]
    rows = [
        [
            name,
            distribution.count,
            distribution.mean,
            distribution.percentiles.get("p50", 0),
            distribution.percentiles.get("p90", 0),
            distribution.percentiles.get("p99", 0),
            distribution.maximum,
            *(distribution.histogram.get(label, 0) for label in labels),
        ]
        for name, distribution in distributions.items()
    ]
    return headers, rows


def render_markdown(summary: TracingSummary, output_directory: Path) -> str:
    status_names = [str(status) for status in TraceStatus]
    by_source = [*summary.sources, summary.total]
    sections = [
        "# Phase 2 proof tracing",
        f"Parts {', '.join(summary.parts)}: {summary.shards_traced}/{summary.shards_planned} shards traced "
        f"({summary.proofs_planned:,} proofs planned; `stp_conjectures` excluded). Every step ran with "
        f"{', '.join(f'{value:,}' for value in summary.heartbeats)} heartbeats and a wall-clock backstop. "
        "Only complete proofs (every step succeeds, no goals at the end) yield training steps; steps after the goals "
        "are closed are dropped. Proofs failing at a step (step_error, closed_early, goals_remaining) are re-checked "
        "as whole theorems with `verify_proof`: those that compile fail only in step-by-step replay, the others do "
        "not compile in the pinned environment (their failure reason is Lean's first error for the whole proof).",
        "## Replay by source",
        markdown_table(
            [
                "source",
                "planned",
                "attempted",
                "complete rate",
                *status_names,
                "block fallback (completed)",
                "failures compiling as whole proofs",
                f"complete with a step > {SEARCH_STEP_SECONDS:.0f} s",
                "steps",
            ],
            [
                [
                    entry.source,
                    entry.planned_proofs,
                    entry.attempted,
                    f"{entry.completion_rate:.1%}",
                    *(entry.statuses[name] for name in status_names),
                    f"{entry.block_fallbacks} ({entry.block_fallbacks_completed})",
                    f"{entry.failures_compiling_as_whole_proofs}/{entry.failures_checked_as_whole_proofs}",
                    entry.complete_proofs_with_slow_steps,
                    entry.training_steps,
                ]
                for entry in by_source
            ],
        ),
        "## Main failure reasons",
    ]
    for entry in by_source:
        reasons = "; ".join(f"{reason}: {count}" for reason, count in entry.failure_reasons.items())
        sections.append(f"- **{entry.source}**: {reasons or 'none'}")
    sections += [
        "## Splits",
        "2% of statements are held out for validation, by a stable hash of the canonical statement (12% of the "
        "statements appear in several sources under different identifiers).",
        markdown_table(
            ["split", "complete proofs", "statements", "steps"],
            [
                [name, counts.complete_proofs, counts.statements, counts.steps]
                for name, counts in summary.splits.items()
            ],
        ),
        "## Remaining steps per training step",
        markdown_table(*_distribution_rows(summary.remaining_steps, REMAINING_STEP_BUCKETS)),
        "## Open goals before each step",
        markdown_table(*_distribution_rows({"goals before": summary.goals_before}, GOAL_COUNT_BUCKETS)),
        "## Step length (characters)",
        markdown_table(*_distribution_rows({"step characters": summary.step_characters}, STEP_CHARACTER_BUCKETS)),
        "## Verification",
        f"{summary.verification.sampled_complete_proofs} complete proofs (a stable 2% sample) re-verified end to end "
        f"with `verify_state`: {summary.verification.verified} verified "
        f"(agreement {summary.verification.agreement_rate:.2%}); {summary.verification.plain_verified} also verify "
        "without the per-step heartbeat wrappers.",
    ]
    for disagreement in summary.verification.disagreements:
        sections.append(f"- `{disagreement.proof_identifier}`: {' / '.join(disagreement.problems)[:300]}")
    sections += [
        "## Throughput",
        markdown_table(
            [
                "invocation",
                "processes",
                "shards",
                "proofs",
                "wall s",
                "proofs/s",
                "steps/s",
                "tactic calls/s",
                "Lean busy",
            ],
            [
                [
                    entry.invocation,
                    entry.pool_size,
                    entry.shards,
                    entry.proofs,
                    entry.wall_seconds,
                    entry.proofs_per_second,
                    entry.training_steps_per_second,
                    entry.tactic_calls_per_second,
                    f"{entry.lean_seconds_per_process_second:.0%}",
                ]
                for entry in summary.throughput
            ],
        ),
        "## Data",
        f"Shards in `{output_directory}/shards/<source>/<part>_<index>.{{steps,proofs}}.jsonl`; merged files "
        f"`{output_directory}/steps_{{train,validation}}.jsonl` and `proofs.jsonl`. Schemas in "
        "`lean_search.corpora.records`: `TracedStep` (one per step of a complete proof; `previous_steps` rebuilds the "
        "state before it, see `tracing.state_before`) and `TracedProof` (one per proof: status, path, failing step, "
        "timing, verification).",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    arguments = parse_arguments()
    parts = selected_names(arguments.parts, PARTS)
    sources = selected_names(arguments.sources, TRACE_ORDER)
    paths = OutputPaths(arguments.output_directory)
    shards = [
        shard
        for shard in load_plan(paths, arguments.pilot_size, arguments.shard_size)
        if shard.source in sources and shard_part(shard.key) in parts
    ]
    if arguments.summarize:
        summary = summarize(shards, paths, arguments.merge, parts)
        summary_directory = RUN_DIRECTORY / "summary"
        summary_directory.mkdir(parents=True, exist_ok=True)
        (summary_directory / f"{arguments.summary_name}.json").write_text(
            json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        (summary_directory / f"{arguments.summary_name}.md").write_text(
            render_markdown(summary, paths.directory), encoding="utf-8"
        )
        print(render_markdown(summary, paths.directory))
        return
    pending = [shard for shard in shards if not paths.is_done(shard.key)]
    revision, dirty = git_state()
    invocation = Invocation(
        invocation=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=revision,
        git_dirty=dirty,
        pool_size=arguments.pool_size,
        parts=parts,
        sources=sources,
        heartbeats=arguments.heartbeats,
        timeout_seconds=arguments.timeout_seconds,
        pending_shards=len(pending),
        pending_proofs=sum(len(shard.records) for shard in pending),
    )
    append_json_line(paths.invocations, invocation)
    logger.info(
        "%d of %d shards pending (%d proofs; excluded sources: %s), git %s",
        len(pending),
        len(shards),
        invocation.pending_proofs,
        ", ".join(sorted(EXCLUDED_SOURCES)),
        revision[:10],
    )
    limits = TracingLimits(arguments.heartbeats, arguments.timeout_seconds)
    asyncio.run(run_tracing(pending, paths, arguments.pool_size, limits, invocation.invocation))
    logger.info("Done")


if __name__ == "__main__":
    main()
