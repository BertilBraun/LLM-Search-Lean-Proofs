"""Replay recorded steps under heartbeat caps: which steps of found proofs still complete, what former timeouts do.

    python experiments/heartbeat_replay.py --trees runs/phase5_expansions_visible_student/trees \
        --caps 25000 50000 100000 --timeout-sample 300 --output runs/heartbeat_replay_visible_student

For every tree, the parent states are rebuilt from the recorded steps with a generous limit; then (a) every step on
the found proof path and (b) a seeded sample of the edges that hit the wall clock run again from their parent at each
heartbeat cap, with --wall-clock seconds as the emergency stop. Reports per cap how many proof steps still complete,
how many former timeouts now finish, fail fast or run out of heartbeats, and their Lean seconds. Headers come from
miniF2F by problem name. Writes records.jsonl, summary.json and README.md to --output.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.data import load_minif2f
from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool, LeanTimeout, ProofState, ReplFailure
from lean_search.lean.repl import BlockFailure
from lean_search.search import FailureKind, NodeStatus, TreeRecord, read_tree
from lean_search.search.summary import markdown_table

BUILD_HEARTBEATS = 200_000
BUILD_TIMEOUT_SECONDS = 120.0
EXAMPLES = 20


class JobKind(StrEnum):
    PROOF_STEP = "proof_step"
    FORMER_TIMEOUT = "former_timeout"


class ReplayOutcome(StrEnum):
    COMPLETED = "completed"
    # A prefix of the block ran, then a tactic failed.
    PARTIAL = "partial"
    ERROR = "error"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    REPL_FAILURE = "repl_failure"
    # The parent state could not be rebuilt as recorded.
    UNREPLAYABLE = "unreplayable"


@dataclass(frozen=True)
class ReplayJob:
    kind: JobKind
    problem_name: str
    parent_id: int
    text: str
    # The recorded edge (former timeouts) or the step's node (proof steps), and the recorded Lean seconds.
    recorded_id: int
    recorded_seconds: float


@dataclass(frozen=True)
class ReplayRecord:
    job: ReplayJob
    heartbeats: int
    outcome: ReplayOutcome
    applied_tactics: int
    total_tactics: int
    lean_seconds: float
    message: str


@dataclass(frozen=True)
class SecondsSummary:
    count: int
    total: float
    median: float
    p95: float


@dataclass(frozen=True)
class CapSummary:
    kind: JobKind
    heartbeats: int
    jobs: int
    outcomes: dict[str, int]
    seconds: SecondsSummary
    seconds_by_outcome: dict[str, SecondsSummary]
    recorded_seconds: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", nargs="+", required=True, type=Path)
    parser.add_argument("--caps", nargs="+", type=int, default=[25_000, 50_000, 100_000])
    parser.add_argument("--timeout-sample", type=int, default=300, help="former wall-clock timeouts to replay")
    parser.add_argument("--limit-trees", type=int, help="at most this many trees per directory (sorted by name)")
    parser.add_argument("--only-solved", action="store_true", help="only trees with a found proof")
    parser.add_argument("--wall-clock", type=float, default=60.0, help="emergency stop per tactic, in seconds")
    parser.add_argument("--repls", type=int, default=int(os.environ.get("LEAN_SEARCH_CPU_COUNT", "4")))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def proof_path(record: TreeRecord) -> list[int]:
    """Node ids from the root to the verified proof, or [] when the tree has none."""
    proved = [node for node in record.nodes if node.status == NodeStatus.PROVED and not node.goals]
    if not proved:
        return []
    path = [proved[0].node_id]
    while (parent := record.nodes[path[-1]].parent_id) is not None:
        path.append(parent)
    return path[::-1]


def proof_jobs(record: TreeRecord) -> list[ReplayJob]:
    jobs = []
    for node_id in proof_path(record)[1:]:
        node = record.nodes[node_id]
        assert node.parent_id is not None and node.step is not None
        jobs.append(
            ReplayJob(
                JobKind.PROOF_STEP, record.problem_name, node.parent_id, node.step, node_id, node.step_lean_seconds
            )
        )
    return jobs


def timeout_jobs(record: TreeRecord) -> list[ReplayJob]:
    return [
        ReplayJob(
            JobKind.FORMER_TIMEOUT, record.problem_name, edge.parent_id, edge.text, edge.edge_id, edge.lean_seconds
        )
        for edge in record.edges
        if edge.failure is not None and edge.failure.kind == FailureKind.WALL_CLOCK_TIMEOUT
    ]


def replay_outcome(failure: BlockFailure | None, applied: int) -> ReplayOutcome:
    match failure:
        case None:
            return ReplayOutcome.COMPLETED
        case LeanTimeout(wall_clock=True):
            return ReplayOutcome.WALL_CLOCK_TIMEOUT
        case LeanTimeout():
            return ReplayOutcome.HEARTBEAT_TIMEOUT
        case ReplFailure():
            return ReplayOutcome.REPL_FAILURE
        case _ if applied:
            return ReplayOutcome.PARTIAL
        case _:
            return ReplayOutcome.ERROR


class TreeReplayer:
    """Rebuilds the parent states of one tree on one REPL and replays its jobs at every cap."""

    def __init__(self, repl: LeanRepl, record: TreeRecord, header: str, wall_clock: float) -> None:
        self.repl = repl
        self.record = record
        self.header = header
        self.wall_clock = wall_clock
        self.states: dict[int, ProofState | None] = {}

    async def state(self, node_id: int) -> ProofState | None:
        if node_id not in self.states:
            self.states[node_id] = await self._build(node_id)
        return self.states[node_id]

    async def _build(self, node_id: int) -> ProofState | None:
        node = self.record.nodes[node_id]
        if node.parent_id is None:
            start = await self.repl.start_proof(self.record.statement, self.header)
            state = start.outcome if isinstance(start.outcome, ProofState) else None
        else:
            parent = await self.state(node.parent_id)
            if parent is None or node.step is None:
                return None
            result = await self.repl.apply_block(parent, node.step, BUILD_HEARTBEATS, BUILD_TIMEOUT_SECONDS)
            state = result.state if result.failure is None else None
        if state is None or [" ".join(goal.split()) for goal in state.goals] != [
            " ".join(goal.split()) for goal in node.goals
        ]:
            return None
        return state

    async def replay(self, job: ReplayJob, heartbeats: int) -> ReplayRecord:
        parent = await self.state(job.parent_id)
        if parent is None:
            return ReplayRecord(job, heartbeats, ReplayOutcome.UNREPLAYABLE, 0, 0, 0.0, "")
        result = await self.repl.apply_block(parent, job.text, heartbeats, self.wall_clock)
        applied = len(result.applied_tactics)
        message = "" if result.failure is None else result.failure.message.split("\n")[0][:300]
        return ReplayRecord(
            job,
            heartbeats,
            replay_outcome(result.failure, applied),
            applied,
            result.total_tactics,
            result.elapsed_seconds,
            message,
        )


async def replay_tree(
    pool: LeanReplPool,
    record: TreeRecord,
    header: str,
    jobs: Sequence[ReplayJob],
    caps: Sequence[int],
    wall_clock: float,
) -> list[ReplayRecord]:
    async with pool.acquire() as repl:
        replayer = TreeReplayer(repl, record, header, wall_clock)
        records = []
        for job in jobs:
            for heartbeats in caps:
                records.append(await replayer.replay(job, heartbeats))
        return records


def seconds_summary(values: Sequence[float]) -> SecondsSummary:
    if not values:
        return SecondsSummary(0, 0.0, 0.0, 0.0)
    ordered = sorted(values)
    return SecondsSummary(
        len(ordered), sum(ordered), statistics.median(ordered), ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    )


def cap_summaries(records: Sequence[ReplayRecord], caps: Sequence[int]) -> list[CapSummary]:
    summaries = []
    for kind in JobKind:
        for heartbeats in caps:
            selected = [record for record in records if record.job.kind == kind and record.heartbeats == heartbeats]
            outcomes = {
                outcome.value: sum(record.outcome == outcome for record in selected) for outcome in ReplayOutcome
            }
            summaries.append(
                CapSummary(
                    kind=kind,
                    heartbeats=heartbeats,
                    jobs=len(selected),
                    outcomes=outcomes,
                    seconds=seconds_summary([record.lean_seconds for record in selected]),
                    seconds_by_outcome={
                        outcome.value: seconds_summary(
                            [record.lean_seconds for record in selected if record.outcome == outcome]
                        )
                        for outcome in ReplayOutcome
                        if any(record.outcome == outcome for record in selected)
                    },
                    recorded_seconds=sum(record.job.recorded_seconds for record in selected),
                )
            )
    return summaries


def readme(summaries: Sequence[CapSummary], records: Sequence[ReplayRecord], arguments: argparse.Namespace) -> str:
    outcome_names = [outcome.value for outcome in ReplayOutcome]
    rows = [
        [
            summary.kind.value,
            str(summary.heartbeats),
            str(summary.jobs),
            *(str(summary.outcomes[name]) for name in outcome_names),
            f"{summary.seconds.total:.1f}",
            f"{summary.seconds.median:.2f}",
            f"{summary.seconds.p95:.2f}",
            f"{summary.recorded_seconds:.1f}",
        ]
        for summary in summaries
    ]
    failing_steps = [
        record
        for record in records
        if record.job.kind == JobKind.PROOF_STEP and record.outcome != ReplayOutcome.COMPLETED
    ][:EXAMPLES]
    lines = [
        "# Heartbeat replay",
        "",
        f"Trees: {', '.join(str(path) for path in arguments.trees)}; caps {arguments.caps}; emergency wall clock "
        f"{arguments.wall_clock} s; {arguments.repls} REPLs. Lean seconds are wall-clock time inside the REPL "
        "(load-dependent); `recorded` is what the original search spent on the same jobs.",
        "",
        markdown_table(["jobs", "heartbeats", "n", *outcome_names, "Lean s", "median s", "p95 s", "recorded s"], rows),
        "",
        "## Proof steps that did not complete (examples)",
        "",
        *(
            f"- `{record.job.problem_name}` node {record.job.recorded_id} at {record.heartbeats}: "
            f"{record.outcome.value} after {record.lean_seconds:.1f} s, `{record.job.text[:120]}`"
            for record in failing_steps
        ),
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    arguments = parse_arguments()
    headers = {problem.name: problem.header for problem in load_minif2f()}
    records_by_name: dict[str, TreeRecord] = {}
    for directory in arguments.trees:
        for path in sorted(directory.glob("*.json.gz"))[: arguments.limit_trees]:
            record = read_tree(path)
            if not arguments.only_solved or proof_path(record):
                records_by_name[record.problem_name] = record
    former_timeouts = [job for record in records_by_name.values() for job in timeout_jobs(record)]
    sampled = random.Random(arguments.seed).sample(former_timeouts, min(arguments.timeout_sample, len(former_timeouts)))
    jobs_by_name: dict[str, list[ReplayJob]] = {name: proof_jobs(record) for name, record in records_by_name.items()}
    for job in sampled:
        jobs_by_name[job.problem_name].append(job)
    config = LeanReplConfig(tactic_timeout_seconds=arguments.wall_clock)
    async with LeanReplPool(arguments.repls, config) as pool:
        results = await asyncio.gather(
            *(
                replay_tree(pool, records_by_name[name], headers[name], jobs, arguments.caps, arguments.wall_clock)
                for name, jobs in jobs_by_name.items()
                if jobs
            )
        )
    records = [record for tree_records in results for record in tree_records]
    summaries = cap_summaries(records, arguments.caps)
    arguments.output.mkdir(parents=True, exist_ok=True)
    with (arguments.output / "records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")
    (arguments.output / "summary.json").write_text(
        json.dumps([dataclasses.asdict(summary) for summary in summaries], indent=2)
    )
    (arguments.output / "README.md").write_text(readme(summaries, records, arguments))
    print(readme(summaries, records, arguments))


if __name__ == "__main__":
    asyncio.run(main())
