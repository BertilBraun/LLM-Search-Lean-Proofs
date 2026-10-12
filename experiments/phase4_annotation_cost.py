"""Lean cost of the lemma applicability check per expansion, on miniF2F-valid roots and traced validation states.

    python experiments/phase4_annotation_cost.py --candidates frequent --processes 8 [--traced-states 256]

Candidates are the retriever's top N (`retrieved`, needs the premise embeddings) or, before those exist, the N
premises most often named in traced competition steps (`frequent`). Writes
$LEAN_SEARCH_RUNS/phase4_annotation_cost/summary/<candidates>.{json,md}.
"""

import argparse
import asyncio
import collections
import dataclasses
import hashlib
import json
import os
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.records import TracedStep, read_traced_steps
from lean_search.corpora.tracing import state_before
from lean_search.data import Split, load_minif2f
from lean_search.lean import LeanReplConfig, LeanReplPool, ProofState
from lean_search.retrieval.annotation import Annotation, Applicability, annotate
from lean_search.retrieval.config import ApplicabilityConfig, RetrievalConfig
from lean_search.retrieval.premises import (
    MINIF2F_OPEN_NAMESPACES,
    RetrievedPremise,
    read_signatures,
    step_premises,
)
from lean_search.retrieval.provider import load_goal_retriever
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RETRIEVAL_DIRECTORY = DATA_DIRECTORY / "retrieval"
TRACED_DIRECTORY = DATA_DIRECTORY / "traced"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_annotation_cost"


class CandidateSource(StrEnum):
    FREQUENT = "frequent"
    RETRIEVED = "retrieved"


@dataclass(frozen=True)
class AnnotationTask:
    kind: str
    name: str
    header: str
    statement: str
    goals: tuple[str, ...]
    traced_step: TracedStep | None


@dataclass(frozen=True)
class StateRecord:
    kind: str
    name: str
    goal_count: int
    candidates: int
    tactic_calls: int
    lean_seconds: float
    closing: int
    leaving_goals: int
    without_match: int


@dataclass(frozen=True)
class TryStatistics:
    tactic: str
    outcome: str
    count: int
    mean_seconds: float
    p50_seconds: float
    p90_seconds: float
    p99_seconds: float
    max_seconds: float


@dataclass(frozen=True)
class CostSummary:
    candidates: CandidateSource
    candidate_count: int
    config: ApplicabilityConfig
    processes: int
    states: int
    failed_states: int
    wall_seconds: float
    lean_seconds_per_state_mean: float
    lean_seconds_per_state_p50: float
    lean_seconds_per_state_p90: float
    lean_seconds_per_state_max: float
    tactic_calls_per_state: float
    candidates_closing: float
    candidates_leaving_goals: float
    candidates_without_match: float
    states_with_a_closing_candidate: float
    process_restarts: int
    tries: tuple[TryStatistics, ...]
    frequent_premises: tuple[str, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", type=CandidateSource, choices=list(CandidateSource), required=True)
    parser.add_argument("--candidate-count", type=int, default=32)
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--traced-states", type=int, default=256)
    parser.add_argument("--heartbeats", type=int, default=ApplicabilityConfig.heartbeats)
    parser.add_argument("--timeout-seconds", type=float, default=ApplicabilityConfig.timeout_seconds)
    return parser.parse_args()


def stable_key(text: str) -> bytes:
    return hashlib.sha256(f"phase4-annotation-cost\n{text}".encode()).digest()


def frequent_premises(known_names: set[str], count: int) -> list[str]:
    counts: collections.Counter[str] = collections.Counter()
    for step in read_traced_steps(TRACED_DIRECTORY / "steps_train.jsonl"):
        counts.update(step_premises(step.step, known_names, MINIF2F_OPEN_NAMESPACES))
    return [name for name, _ in counts.most_common(count)]


def traced_tasks(count: int) -> list[AnnotationTask]:
    steps = sorted(
        read_traced_steps(TRACED_DIRECTORY / "steps_validation.jsonl"),
        key=lambda step: stable_key(f"{step.proof_identifier}#{step.step_index}"),
    )
    return [
        AnnotationTask(
            "traced",
            f"{step.proof_identifier}#{step.step_index}",
            step.header,
            step.formal_statement,
            step.goals_before,
            step,
        )
        for step in steps[:count]
    ]


def minif2f_tasks() -> list[AnnotationTask]:
    return [
        AnnotationTask("minif2f_root", problem.name, problem.header, problem.formal_statement, (problem.goal,), None)
        for problem in load_minif2f(Split.VALID)
    ]


def retrieved_candidates(tasks: Sequence[AnnotationTask], count: int) -> list[tuple[RetrievedPremise, ...]]:
    retriever = load_goal_retriever(RetrievalConfig(lemma_count=count, candidate_count=count))
    return retriever.retrieve([task.goals for task in tasks], count)


async def annotate_task(
    pool: LeanReplPool, task: AnnotationTask, premises: Sequence[RetrievedPremise], config: ApplicabilityConfig
) -> Annotation | None:
    async with pool.acquire() as repl:
        if task.traced_step is None:
            outcome = (await repl.start_proof(task.statement, task.header)).outcome
        else:
            # A no-op step replays the traced state on this process, so the checks measure only themselves.
            outcome = (await repl.apply_tactic(state_before(task.traced_step), "skip")).outcome
        match outcome:
            case ProofState():
                return await annotate(repl, outcome, premises, config)
            case _:
                return None


async def run_tasks(
    tasks: Sequence[AnnotationTask],
    candidates: Sequence[tuple[RetrievedPremise, ...]],
    config: ApplicabilityConfig,
    processes: int,
) -> tuple[list[tuple[AnnotationTask, Annotation]], int, int, float]:
    results: list[tuple[AnnotationTask, Annotation]] = []
    failed = 0
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(len(tasks)):
        queue.put_nowait(index)

    async with LeanReplPool(processes, LeanReplConfig()) as pool:
        await pool.start(sorted({task.header for task in tasks}))
        started = time.monotonic()

        async def worker() -> None:
            nonlocal failed
            while not queue.empty():
                index = queue.get_nowait()
                annotation = await annotate_task(pool, tasks[index], candidates[index], config)
                if annotation is None:
                    failed += 1
                    continue
                results.append((tasks[index], annotation))
                print(f"[{len(results)}/{len(tasks)}] {tasks[index].name}: {annotation.lean_seconds:.2f}s", flush=True)

        await asyncio.gather(*(worker() for _ in range(processes)))
        wall_seconds = time.monotonic() - started
        restarts = sum(repl.restart_count for repl in pool.repls)
    return results, failed, restarts, wall_seconds


def quantile(ordered: Sequence[float], fraction: float) -> float:
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def try_statistics(results: Sequence[tuple[AnnotationTask, Annotation]]) -> tuple[TryStatistics, ...]:
    seconds: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for _, annotation in results:
        for lemma in annotation.lemmas:
            for attempt in lemma.tries:
                seconds[(attempt.tactic, attempt.outcome.value)].append(attempt.seconds)
    rows = []
    for (tactic, outcome), values in sorted(seconds.items()):
        ordered = sorted(values)
        rows.append(
            TryStatistics(
                tactic,
                outcome,
                len(ordered),
                statistics.fmean(ordered),
                quantile(ordered, 0.5),
                quantile(ordered, 0.9),
                quantile(ordered, 0.99),
                ordered[-1],
            )
        )
    return tuple(rows)


def state_record(task: AnnotationTask, annotation: Annotation) -> StateRecord:
    applicabilities = collections.Counter(lemma.check.applicability for lemma in annotation.lemmas)
    return StateRecord(
        task.kind,
        task.name,
        len(task.goals),
        len(annotation.lemmas),
        annotation.tactic_calls,
        annotation.lean_seconds,
        applicabilities[Applicability.CLOSES],
        applicabilities[Applicability.LEAVES_GOALS],
        applicabilities[Applicability.NO_MATCH],
    )


def render_markdown(summary: CostSummary) -> str:
    config = summary.config
    tries = [
        [
            row.tactic,
            row.outcome,
            f"{row.count:,}",
            f"{row.mean_seconds * 1000:.0f}",
            f"{row.p50_seconds * 1000:.0f}",
            f"{row.p90_seconds * 1000:.0f}",
            f"{row.p99_seconds * 1000:.0f}",
            f"{row.max_seconds * 1000:.0f}",
        ]
        for row in summary.tries
    ]
    source = (
        "the retriever's top candidates"
        if summary.candidates == CandidateSource.RETRIEVED
        else "the premises most often named in traced competition steps (the same list for every state, a stand-in "
        "until the premise embeddings exist)"
    )
    return (
        "\n\n".join(
            [
                f"# Applicability check cost ({summary.candidates})",
                f"{summary.states} states ({summary.failed_states} failed to start): miniF2F-valid roots and traced "
                f"validation-split competition states. Candidates: {summary.candidate_count} per state, {source}. "
                f"Tactics {', '.join(f'`{tactic}`' for tactic in config.tactics)} in order until one closes the goal, "
                f"{config.heartbeats:,} heartbeats, {config.timeout_seconds:g} s wall-clock backstop; "
                f"{summary.processes} REPL processes, {summary.wall_seconds:.0f} s wall.",
                markdown_table(
                    ["Quantity", "Value"],
                    [
                        ["Lean seconds per state, mean", f"{summary.lean_seconds_per_state_mean:.2f}"],
                        [
                            "p50 / p90 / max",
                            f"{summary.lean_seconds_per_state_p50:.2f} / "
                            f"{summary.lean_seconds_per_state_p90:.2f} / {summary.lean_seconds_per_state_max:.2f}",
                        ],
                        ["Tactic calls per state", f"{summary.tactic_calls_per_state:.1f}"],
                        ["Candidates closing the goal, per state", f"{summary.candidates_closing:.2f}"],
                        ["Candidates leaving goals, per state", f"{summary.candidates_leaving_goals:.2f}"],
                        ["Candidates without a match, per state", f"{summary.candidates_without_match:.2f}"],
                        ["States with a closing candidate", f"{summary.states_with_a_closing_candidate:.1%}"],
                        ["Process restarts", str(summary.process_restarts)],
                    ],
                ),
                "## Per tactic call (milliseconds)",
                markdown_table(["Tactic", "Outcome", "Calls", "Mean", "p50", "p90", "p99", "Max"], tries),
            ]
        )
        + "\n"
    )


def main() -> None:
    arguments = parse_arguments()
    config = ApplicabilityConfig(heartbeats=arguments.heartbeats, timeout_seconds=arguments.timeout_seconds)
    tasks = minif2f_tasks() + traced_tasks(arguments.traced_states)
    frequent: list[str] = []
    match arguments.candidates:
        case CandidateSource.FREQUENT:
            signatures = {
                signature.full_name: signature.signature
                for signature in read_signatures(RETRIEVAL_DIRECTORY / "signatures.jsonl")
            }
            frequent = frequent_premises(set(signatures), arguments.candidate_count)
            premises = tuple(RetrievedPremise(name, signatures[name], 0.0) for name in frequent)
            candidates = [premises] * len(tasks)
        case CandidateSource.RETRIEVED:
            candidates = retrieved_candidates(tasks, arguments.candidate_count)
    print(f"{len(tasks)} states, candidates ready", flush=True)
    results, failed, restarts, wall_seconds = asyncio.run(run_tasks(tasks, candidates, config, arguments.processes))
    records = [state_record(task, annotation) for task, annotation in results]
    seconds = sorted(record.lean_seconds for record in records)
    summary = CostSummary(
        candidates=arguments.candidates,
        candidate_count=arguments.candidate_count,
        config=config,
        processes=arguments.processes,
        states=len(records),
        failed_states=failed,
        wall_seconds=wall_seconds,
        lean_seconds_per_state_mean=statistics.fmean(seconds),
        lean_seconds_per_state_p50=quantile(seconds, 0.5),
        lean_seconds_per_state_p90=quantile(seconds, 0.9),
        lean_seconds_per_state_max=seconds[-1],
        tactic_calls_per_state=statistics.fmean(record.tactic_calls for record in records),
        candidates_closing=statistics.fmean(record.closing for record in records),
        candidates_leaving_goals=statistics.fmean(record.leaving_goals for record in records),
        candidates_without_match=statistics.fmean(record.without_match for record in records),
        states_with_a_closing_candidate=statistics.fmean(record.closing > 0 for record in records),
        process_restarts=restarts,
        tries=try_statistics(results),
        frequent_premises=tuple(frequent),
    )
    directory = RUN_DIRECTORY / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{arguments.candidates}_{arguments.heartbeats}"
    (directory / f"{name}.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    with (RUN_DIRECTORY / f"{name}_states.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")
    markdown = render_markdown(summary)
    (directory / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
