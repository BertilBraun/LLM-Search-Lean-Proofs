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
from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool, ProofState
from lean_search.retrieval.annotation import AUTOMATION_SUFFIX, Annotation, Applicability, annotate
from lean_search.retrieval.config import DEFAULT_RETRIEVER, ApplicabilityConfig, RetrievalConfig
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
    closing_with_automation: int
    leaving_goals: int
    without_match: int
    # Lean seconds of the automation follow-ups alone.
    automation_seconds: float
    automation_alone_closes: bool


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
    candidates_closing_with_automation: float
    candidates_leaving_goals: float
    candidates_without_match: float
    states_with_a_closing_candidate: float
    states_with_a_candidate_closing_with_automation: float
    automation_seconds_per_state: float
    # The same over the states the automation alone does not close (in the search, the sweep runs first).
    states_automation_alone_closes: int
    candidates_closing_with_automation_where_automation_alone_fails: float
    states_with_a_candidate_closing_with_automation_where_automation_alone_fails: float
    process_restarts: int
    tries: tuple[TryStatistics, ...]
    frequent_premises: tuple[str, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", type=CandidateSource, choices=list(CandidateSource), required=True)
    parser.add_argument("--candidate-count", type=int, default=32)
    parser.add_argument("--retriever", default=DEFAULT_RETRIEVER, help="for --candidates retrieved")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--traced-states", type=int, default=256)
    parser.add_argument("--heartbeats", type=int, default=ApplicabilityConfig.heartbeats)
    parser.add_argument("--timeout-seconds", type=float, default=ApplicabilityConfig.timeout_seconds)
    parser.add_argument("--automation", default="", help="follow-up run with `<;>` after a tactic that left goals")
    parser.add_argument("--automation-heartbeats", type=int, default=ApplicabilityConfig.automation_heartbeats)
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


def retrieved_candidates(
    tasks: Sequence[AnnotationTask], count: int, retriever_name: str
) -> list[tuple[RetrievedPremise, ...]]:
    retriever = load_goal_retriever(RetrievalConfig(lemma_count=count, candidate_count=count, retriever=retriever_name))
    return retriever.retrieve([task.goals for task in tasks], count)


@dataclass(frozen=True)
class TaskResult:
    task: AnnotationTask
    annotation: Annotation
    # The automation follow-up alone closes every goal (False without a follow-up).
    automation_alone_closes: bool


async def automation_alone_closes(repl: LeanRepl, state: ProofState, config: ApplicabilityConfig) -> bool:
    if not config.automation:
        return False
    result = await repl.apply_tactic(state, f"({config.automation})", heartbeats=config.automation_heartbeats)
    return isinstance(result.outcome, ProofState) and result.outcome.is_proved


async def annotate_task(
    pool: LeanReplPool, task: AnnotationTask, premises: Sequence[RetrievedPremise], config: ApplicabilityConfig
) -> TaskResult | None:
    async with pool.acquire() as repl:
        if task.traced_step is None:
            outcome = (await repl.start_proof(task.statement, task.header)).outcome
        else:
            # A no-op step replays the traced state on this process, so the checks measure only themselves.
            outcome = (await repl.apply_tactic(state_before(task.traced_step), "skip")).outcome
        match outcome:
            case ProofState():
                annotation = await annotate(repl, outcome, premises, config)
                return TaskResult(task, annotation, await automation_alone_closes(repl, outcome, config))
            case _:
                return None


async def run_tasks(
    tasks: Sequence[AnnotationTask],
    candidates: Sequence[tuple[RetrievedPremise, ...]],
    config: ApplicabilityConfig,
    processes: int,
) -> tuple[list[TaskResult], int, int, float]:
    results: list[TaskResult] = []
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
                result = await annotate_task(pool, tasks[index], candidates[index], config)
                if result is None:
                    failed += 1
                    continue
                results.append(result)
                seconds = result.annotation.lean_seconds
                print(f"[{len(results)}/{len(tasks)}] {tasks[index].name}: {seconds:.2f}s", flush=True)

        await asyncio.gather(*(worker() for _ in range(processes)))
        wall_seconds = time.monotonic() - started
        restarts = sum(repl.restart_count for repl in pool.repls)
    return results, failed, restarts, wall_seconds


def quantile(ordered: Sequence[float], fraction: float) -> float:
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def try_statistics(results: Sequence[TaskResult]) -> tuple[TryStatistics, ...]:
    seconds: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for result in results:
        for lemma in result.annotation.lemmas:
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


def mean_or_zero(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def state_record(result: TaskResult) -> StateRecord:
    task = result.task
    annotation = result.annotation
    applicabilities = collections.Counter(lemma.check.applicability for lemma in annotation.lemmas)
    return StateRecord(
        task.kind,
        task.name,
        len(task.goals),
        len(annotation.lemmas),
        annotation.tactic_calls,
        annotation.lean_seconds,
        applicabilities[Applicability.CLOSES],
        applicabilities[Applicability.CLOSES_WITH_AUTOMATION],
        applicabilities[Applicability.LEAVES_GOALS],
        applicabilities[Applicability.NO_MATCH],
        sum(
            attempt.seconds
            for lemma in annotation.lemmas
            for attempt in lemma.tries
            if attempt.tactic.endswith(AUTOMATION_SUFFIX)
        ),
        result.automation_alone_closes,
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
                f"{summary.processes} REPL processes, {summary.wall_seconds:.0f} s wall. "
                + (
                    f"After a tactic that leaves goals, `<tactic> <;> ({config.automation})` runs with "
                    f"{config.automation_heartbeats:,} heartbeats."
                    if config.automation
                    else "No automation follow-up."
                ),
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
                        [
                            "Candidates closing with automation, per state",
                            f"{summary.candidates_closing_with_automation:.2f}",
                        ],
                        ["Candidates leaving goals, per state", f"{summary.candidates_leaving_goals:.2f}"],
                        ["Candidates without a match, per state", f"{summary.candidates_without_match:.2f}"],
                        ["States with a closing candidate", f"{summary.states_with_a_closing_candidate:.1%}"],
                        [
                            "States with a candidate closing with automation",
                            f"{summary.states_with_a_candidate_closing_with_automation:.1%}",
                        ],
                        ["Automation follow-up Lean seconds per state", f"{summary.automation_seconds_per_state:.2f}"],
                        ["States the automation alone closes", str(summary.states_automation_alone_closes)],
                        [
                            "Where it does not: candidates closing with automation, per state",
                            f"{summary.candidates_closing_with_automation_where_automation_alone_fails:.2f}",
                        ],
                        [
                            "Where it does not: states with a candidate closing with automation",
                            f"{summary.states_with_a_candidate_closing_with_automation_where_automation_alone_fails:.1%}",
                        ],
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
    config = ApplicabilityConfig(
        heartbeats=arguments.heartbeats,
        timeout_seconds=arguments.timeout_seconds,
        automation=arguments.automation,
        automation_heartbeats=arguments.automation_heartbeats,
    )
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
            candidates = retrieved_candidates(tasks, arguments.candidate_count, arguments.retriever)
    print(f"{len(tasks)} states, candidates ready", flush=True)
    results, failed, restarts, wall_seconds = asyncio.run(run_tasks(tasks, candidates, config, arguments.processes))
    records = [state_record(result) for result in results]
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
        candidates_closing_with_automation=statistics.fmean(record.closing_with_automation for record in records),
        candidates_leaving_goals=statistics.fmean(record.leaving_goals for record in records),
        candidates_without_match=statistics.fmean(record.without_match for record in records),
        states_with_a_closing_candidate=statistics.fmean(record.closing > 0 for record in records),
        states_with_a_candidate_closing_with_automation=statistics.fmean(
            record.closing_with_automation > 0 for record in records
        ),
        automation_seconds_per_state=statistics.fmean(record.automation_seconds for record in records),
        states_automation_alone_closes=sum(record.automation_alone_closes for record in records),
        candidates_closing_with_automation_where_automation_alone_fails=mean_or_zero(
            [record.closing_with_automation for record in records if not record.automation_alone_closes]
        ),
        states_with_a_candidate_closing_with_automation_where_automation_alone_fails=mean_or_zero(
            [record.closing_with_automation > 0 for record in records if not record.automation_alone_closes]
        ),
        process_restarts=restarts,
        tries=try_statistics(results),
        frequent_premises=tuple(frequent),
    )
    directory = RUN_DIRECTORY / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{arguments.candidates}_{arguments.candidate_count}_{arguments.heartbeats}" + (
        "_automation" if arguments.automation else ""
    )
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
