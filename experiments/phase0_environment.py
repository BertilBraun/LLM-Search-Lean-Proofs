"""Phase 0: miniF2F statement check and Lean costs (process start, memory, concurrency, automation sweep)."""

import argparse
import asyncio
import itertools
import json
import os
import statistics
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from lean_search.data import Problem, Split, load_minif2f
from lean_search.lean import LeanError, LeanRepl, LeanReplConfig, LeanReplPool, LeanTimeout, ProofState, normalize_goal
from lean_search.lean.repl import PROJECT_DIRECTORY

RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase0_environment"
PARTS_DIRECTORY = RUN_DIRECTORY / "parts"
SUMMARY_DIRECTORY = RUN_DIRECTORY / "summary"
CGROUP_DIRECTORY = Path("/sys/fs/cgroup")
GIBIBYTE = 1 << 30
MEBIBYTE = 1 << 20

SWEEP_TACTICS = (
    "rfl",
    "decide",
    "norm_num",
    "simp",
    "simp_all",
    "ring_nf",
    "field_simp",
    "linarith",
    "nlinarith",
    "positivity",
    "omega",
    "aesop",
    "tauto",
    "intros",
    "constructor",
)
MEMORY_TACTICS = ("intros", "norm_num", "simp", "ring_nf", "omega", "linarith")
CONCURRENCY_TACTICS = ("norm_num", "simp", "linarith", "nlinarith", "omega", "aesop")
NO_RESTARTS = LeanReplConfig(max_anonymous_memory_bytes=1 << 50, max_proof_states=1 << 50)


@dataclass(frozen=True)
class StatementCheck:
    name: str
    split: str
    started: bool
    error: str | None
    goal_matches_dataset: bool
    needs_auto_implicit: bool
    seconds: float


@dataclass(frozen=True)
class ProcessCost:
    start_and_import_seconds: float
    resident_gibibytes: float
    anonymous_gibibytes: float


@dataclass(frozen=True)
class MemorySample:
    tactic_applications: int
    proof_states: int
    anonymous_mebibytes: float


@dataclass(frozen=True)
class ConcurrencyResult:
    processes: int
    ready_seconds: float
    applications: int
    applications_per_second: float
    median_latency_seconds: float
    p90_latency_seconds: float
    wall_clock_timeouts: int
    load_average_before: float
    baseline_cgroup_gibibytes: float
    baseline_cgroup_anonymous_gibibytes: float
    peak_cgroup_gibibytes: float
    peak_cgroup_anonymous_gibibytes: float
    peak_pool_anonymous_gibibytes: float
    max_process_anonymous_gibibytes: float
    cgroup_limit_gibibytes: float


@dataclass(frozen=True)
class SweepRecord:
    name: str
    tactic: str
    outcome: str
    seconds: float
    verified: bool | None


@dataclass(frozen=True)
class TacticStatistics:
    tactic: str
    attempts: int
    closed: int
    progress: int
    unchanged: int
    errors: int
    heartbeat_timeouts: int
    wall_clock_timeouts: int
    median_seconds: float
    p90_seconds: float
    max_seconds: float
    closing_rate: float
    progress_rate: float


class MemorySampler:
    def __init__(self, repls: Sequence[LeanRepl]) -> None:
        self.repls = repls
        self.peak_current = 0
        self.peak_anonymous = 0
        self.peak_pool_anonymous = 0
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "MemorySampler":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        assert self._task is not None
        self._task.cancel()

    async def _run(self) -> None:
        while True:
            self.peak_current = max(self.peak_current, cgroup_memory_current())
            self.peak_anonymous = max(self.peak_anonymous, cgroup_anonymous_memory())
            pool_anonymous = sum(repl.memory_usage().anonymous_bytes for repl in self.repls if repl.process_id)
            self.peak_pool_anonymous = max(self.peak_pool_anonymous, pool_anonymous)
            await asyncio.sleep(0.25)


def cgroup_memory_current() -> int:
    return int((CGROUP_DIRECTORY / "memory.current").read_text())


def cgroup_memory_limit() -> int:
    return int((CGROUP_DIRECTORY / "memory.max").read_text())


def cgroup_anonymous_memory() -> int:
    for line in (CGROUP_DIRECTORY / "memory.stat").read_text().splitlines():
        key, value = line.split()
        if key == "anon":
            return int(value)
    raise AssertionError("memory.stat has no anon field")


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def outcome_label(initial: ProofState, outcome: ProofState | LeanError | LeanTimeout) -> str:
    match outcome:
        case ProofState(is_proved=True):
            return "closed"
        case ProofState() if outcome.goal_key != initial.goal_key:
            return "progress"
        case ProofState():
            return "unchanged"
        case LeanTimeout(wall_clock=True):
            return "wall_clock_timeout"
        case LeanTimeout():
            return "heartbeat_timeout"
        case LeanError():
            return "error"


def save_part(name: str, data: object) -> None:
    PARTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (PARTS_DIRECTORY / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))


async def check_statements(problems: Sequence[Problem], pool_size: int) -> list[StatementCheck]:
    async def check(problem: Problem) -> StatementCheck:
        async with pool.acquire() as repl:
            result = await repl.start_proof(problem.formal_statement, problem.header)
            strict = await repl.start_proof(
                "set_option autoImplicit false in\n" + problem.formal_statement, problem.header
            )
        match result.outcome:
            case ProofState() as state:
                return StatementCheck(
                    problem.name,
                    problem.split,
                    started=True,
                    error=None,
                    goal_matches_dataset=normalize_goal(state.goals[0]) == normalize_goal(problem.goal),
                    needs_auto_implicit=not isinstance(strict.outcome, ProofState),
                    seconds=result.elapsed_seconds,
                )
            case LeanError(message=message) | LeanTimeout(message=message):
                return StatementCheck(problem.name, problem.split, False, message, False, False, result.elapsed_seconds)

    async with LeanReplPool(pool_size) as pool:
        await pool.start([problems[0].header])
        return list(await asyncio.gather(*(check(problem) for problem in problems)))


async def measure_process_costs(header: str, repetitions: int) -> list[ProcessCost]:
    costs = []
    for _ in range(repetitions):
        started = time.monotonic()
        async with LeanRepl() as repl:
            await repl.load_header(header)
            seconds = time.monotonic() - started
            usage = repl.memory_usage()
        costs.append(ProcessCost(seconds, usage.resident_bytes / GIBIBYTE, usage.anonymous_bytes / GIBIBYTE))
    return costs


async def measure_memory_growth(problems: Sequence[Problem], applications: int) -> list[MemorySample]:
    samples = []
    async with LeanRepl(NO_RESTARTS) as repl:
        await repl.load_header(problems[0].header)
        samples.append(MemorySample(0, repl.proof_state_count, repl.memory_usage().anonymous_bytes / MEBIBYTE))
        count = 0
        problem_iterator = itertools.cycle(problems)
        while count < applications:
            problem = next(problem_iterator)
            start = await repl.start_proof(problem.formal_statement, problem.header)
            if not isinstance(start.outcome, ProofState):
                continue
            for tactic in MEMORY_TACTICS:
                await repl.apply_tactic(start.outcome, tactic, heartbeats=50_000)
                count += 1
                if count % 100 == 0:
                    anonymous = repl.memory_usage().anonymous_bytes / MEBIBYTE
                    samples.append(MemorySample(count, repl.proof_state_count, anonymous))
    return samples


async def measure_concurrency(problems: Sequence[Problem], processes: int, seconds: float) -> ConcurrencyResult:
    baseline = cgroup_memory_current()
    baseline_anonymous = cgroup_anonymous_memory()
    load_average = os.getloadavg()[0]
    latencies: list[float] = []
    wall_clock_timeouts = 0
    problem_iterator = itertools.cycle(problems)

    async def work(repl: LeanRepl, deadline: float) -> None:
        nonlocal wall_clock_timeouts
        while time.monotonic() < deadline:
            problem = next(problem_iterator)
            start = await repl.start_proof(problem.formal_statement, problem.header)
            if not isinstance(start.outcome, ProofState):
                continue
            for tactic in CONCURRENCY_TACTICS:
                result = await repl.apply_tactic(start.outcome, tactic)
                latencies.append(result.elapsed_seconds)
                if isinstance(result.outcome, LeanTimeout) and result.outcome.wall_clock:
                    wall_clock_timeouts += 1

    pool = LeanReplPool(processes, NO_RESTARTS)
    started = time.monotonic()
    async with pool, MemorySampler(pool.repls) as sampler:
        await pool.start([problems[0].header])
        ready_seconds = time.monotonic() - started
        work_started = time.monotonic()
        await asyncio.gather(*(work(repl, work_started + seconds) for repl in pool.repls))
        elapsed = time.monotonic() - work_started
        running = [repl for repl in pool.repls if repl.process_id is not None]
        max_process_anonymous = max(repl.memory_usage().anonymous_bytes for repl in running)
    return ConcurrencyResult(
        processes=processes,
        ready_seconds=ready_seconds,
        applications=len(latencies),
        applications_per_second=len(latencies) / elapsed,
        median_latency_seconds=statistics.median(latencies),
        p90_latency_seconds=percentile(latencies, 0.9),
        wall_clock_timeouts=wall_clock_timeouts,
        load_average_before=load_average,
        baseline_cgroup_gibibytes=baseline / GIBIBYTE,
        baseline_cgroup_anonymous_gibibytes=baseline_anonymous / GIBIBYTE,
        peak_cgroup_gibibytes=sampler.peak_current / GIBIBYTE,
        peak_cgroup_anonymous_gibibytes=sampler.peak_anonymous / GIBIBYTE,
        peak_pool_anonymous_gibibytes=sampler.peak_pool_anonymous / GIBIBYTE,
        max_process_anonymous_gibibytes=max_process_anonymous / GIBIBYTE,
        cgroup_limit_gibibytes=cgroup_memory_limit() / GIBIBYTE,
    )


async def run_sweep(
    problems: Sequence[Problem], pool_size: int, heartbeats: int, timeout_seconds: float
) -> list[SweepRecord]:
    async def sweep(problem: Problem) -> list[SweepRecord]:
        records = []
        async with pool.acquire() as repl:
            start = await repl.start_proof(problem.formal_statement, problem.header)
            if not isinstance(start.outcome, ProofState):
                return []
            for tactic in SWEEP_TACTICS:
                result = await repl.apply_tactic(start.outcome, tactic, heartbeats, timeout_seconds)
                label = outcome_label(start.outcome, result.outcome)
                verified = None
                if label == "closed":
                    verification = await repl.verify_proof(problem.formal_statement, tactic, problem.header)
                    verified = verification.verified
                records.append(SweepRecord(problem.name, tactic, label, result.elapsed_seconds, verified))
        return records

    async with LeanReplPool(pool_size) as pool:
        await pool.start([problems[0].header])
        results = await asyncio.gather(*(sweep(problem) for problem in problems))
    return [record for records in results for record in records]


def sweep_statistics(records: Sequence[SweepRecord]) -> list[TacticStatistics]:
    statistics_by_tactic = []
    for tactic in SWEEP_TACTICS:
        tactic_records = [record for record in records if record.tactic == tactic]
        counts = Counter(record.outcome for record in tactic_records)
        seconds = [record.seconds for record in tactic_records]
        attempts = len(tactic_records)
        statistics_by_tactic.append(
            TacticStatistics(
                tactic=tactic,
                attempts=attempts,
                closed=counts["closed"],
                progress=counts["progress"],
                unchanged=counts["unchanged"],
                errors=counts["error"],
                heartbeat_timeouts=counts["heartbeat_timeout"],
                wall_clock_timeouts=counts["wall_clock_timeout"],
                median_seconds=statistics.median(seconds),
                p90_seconds=percentile(seconds, 0.9),
                max_seconds=max(seconds),
                closing_rate=counts["closed"] / attempts,
                progress_rate=(counts["closed"] + counts["progress"]) / attempts,
            )
        )
    return sorted(statistics_by_tactic, key=lambda entry: entry.median_seconds)


def markdown_table(rows: Sequence[object], columns: Sequence[str]) -> str:
    def cell(value: object) -> str:
        return f"{value:.3g}" if isinstance(value, float) else str(value)

    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(getattr(row, column)) for column in columns) + " |" for row in rows]
    return "\n".join(lines)


def load_part(name: str) -> object | None:
    path = PARTS_DIRECTORY / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def write_summary(arguments: argparse.Namespace) -> None:
    toolchain = (PROJECT_DIRECTORY / "lean-toolchain").read_text().strip()
    manifest = json.loads((PROJECT_DIRECTORY / "lake-manifest.json").read_text())
    revisions = {package["name"]: package["rev"] for package in manifest["packages"]}
    summary: dict[str, object] = {
        "environment": {
            "lean_toolchain": toolchain,
            "revisions": revisions,
            "cpu_count": os.environ.get("LEAN_SEARCH_CPU_COUNT"),
            "cgroup_memory_limit_gibibytes": cgroup_memory_limit() / GIBIBYTE,
            "node_state_at_invocation_start": load_part("context"),
        },
        "settings": {
            "sweep_heartbeats": arguments.sweep_heartbeats,
            "sweep_timeout_seconds": arguments.sweep_timeout_seconds,
            "sweep_tactics": SWEEP_TACTICS,
            "concurrency_tactics": CONCURRENCY_TACTICS,
            "memory_tactics": MEMORY_TACTICS,
        },
    }
    markdown = [
        "# Phase 0: Lean environment",
        "",
        f"`{toolchain}`, Mathlib `{revisions['mathlib']}`, REPL `{revisions['REPL']}`. Other workloads share the "
        f"node; its state when each set of parts started: {load_part('context')}.",
        "",
    ]

    if (statement_rows := load_part("statements")) is not None:
        checks = [StatementCheck(**row) for row in statement_rows]
        failures = [check for check in checks if not check.started]
        statements = {
            "total": len(checks),
            "started": sum(check.started for check in checks),
            "started_by_split": dict(Counter(check.split for check in checks if check.started)),
            "goal_matches_dataset": sum(check.goal_matches_dataset for check in checks),
            "needs_auto_implicit": [check.name for check in checks if check.needs_auto_implicit],
            "median_start_seconds": statistics.median(check.seconds for check in checks),
            "failures": [{"name": check.name, "split": check.split, "error": check.error} for check in failures],
        }
        summary["statements"] = statements
        markdown += [
            "## Statements",
            "",
            f"{statements['started']}/{statements['total']} statements yield a proof state "
            f"({statements['started_by_split']}). Initial goal equal to DeepSeek's `goal` field (normalized): "
            f"{statements['goal_matches_dataset']}/{statements['total']}. Statements that only elaborate with "
            f"`autoImplicit` (the REPL default): {len(statements['needs_auto_implicit'])}. Median start time "
            f"{statements['median_start_seconds']:.3f} s.",
            "",
        ]
        markdown += [f"- `{failure.name}` ({failure.split}): {(failure.error or '')[:300]}" for failure in failures]
        markdown.append("")

    if (cost_rows := load_part("process_costs")) is not None:
        costs = [ProcessCost(**row) for row in cost_rows]
        summary["process_costs"] = {
            "runs": [asdict(cost) for cost in costs],
            "median_start_and_import_seconds": statistics.median(cost.start_and_import_seconds for cost in costs),
        }
        markdown += ["## Process costs", "", "REPL start plus header import (`import Mathlib`), sequential runs:", ""]
        markdown += [
            markdown_table(costs, ["start_and_import_seconds", "resident_gibibytes", "anonymous_gibibytes"]),
            "",
        ]

    if (memory_rows := load_part("memory_growth")) is not None:
        samples = [MemorySample(**row) for row in memory_rows]
        first, last = samples[0], samples[-1]
        growth = (last.anonymous_mebibytes - first.anonymous_mebibytes) / (last.tactic_applications / 100)
        summary["memory_growth"] = {
            "samples": [asdict(sample) for sample in samples],
            "anonymous_mebibytes_per_100_applications": growth,
            "proof_states_created": last.proof_states,
        }
        markdown += [
            "## Memory growth",
            "",
            f"One process, {last.tactic_applications} applications of {', '.join(MEMORY_TACTICS)} (50k heartbeats) to "
            f"initial states of miniF2F-valid, {last.proof_states} proof states created: anonymous RSS "
            f"{first.anonymous_mebibytes:.0f} → {last.anonymous_mebibytes:.0f} MiB, "
            f"**{growth:.1f} MiB per 100 tactic applications**.",
            "",
        ]

    if (concurrency_rows := load_part("concurrency")) is not None:
        results = [ConcurrencyResult(**row) for row in concurrency_rows]
        summary["concurrency"] = [asdict(result) for result in results]
        markdown += [
            "## Concurrency",
            "",
            f"Each process repeatedly starts a miniF2F-valid problem and applies {', '.join(CONCURRENCY_TACTICS)} "
            f"(default limits) for {arguments.concurrency_seconds:.0f} s, sampled every 0.25 s. Pool anonymous = sum "
            "of the REPL processes' private memory; the Mathlib .olean files are shared file mappings (about 3.3 GiB "
            "once per node). Cgroup figures include other workloads on the node (baseline before the pool starts), "
            f"limit {cgroup_memory_limit() / GIBIBYTE:.1f} GiB.",
            "",
            markdown_table(
                results,
                [
                    "processes",
                    "load_average_before",
                    "ready_seconds",
                    "applications_per_second",
                    "median_latency_seconds",
                    "p90_latency_seconds",
                    "wall_clock_timeouts",
                    "peak_pool_anonymous_gibibytes",
                    "max_process_anonymous_gibibytes",
                    "baseline_cgroup_anonymous_gibibytes",
                    "peak_cgroup_anonymous_gibibytes",
                    "peak_cgroup_gibibytes",
                ],
            ),
            "",
        ]

    if (sweep_rows := load_part("sweep")) is not None:
        records = [SweepRecord(**row) for row in sweep_rows]
        tactic_statistics = sweep_statistics(records)
        closed_problems = {record.name for record in records if record.outcome == "closed"}
        verification = Counter(record.verified for record in records if record.outcome == "closed")
        problem_count = len({record.name for record in records})
        summary["sweep"] = {
            "problems": problem_count,
            "closed_by_any_tactic": len(closed_problems),
            "closing_tactics_verified": verification[True],
            "closing_tactics_failing_verification": [
                {"name": record.name, "tactic": record.tactic}
                for record in records
                if record.outcome == "closed" and not record.verified
            ],
            "tactics": [asdict(entry) for entry in tactic_statistics],
        }
        markdown += [
            "## Automation sweep",
            "",
            f"Initial states of {problem_count} miniF2F-valid problems, {arguments.sweep_heartbeats} heartbeats per "
            f"tactic, {arguments.sweep_timeout_seconds:.0f} s wall-clock backstop, pool of {arguments.pool_size} "
            "processes. Progress = valid and goals changed (closing included). Sorted by median latency. "
            f"Closed by at least one tactic: {len(closed_problems)}/{problem_count}; every closing tactic re-verified "
            f"as a full proof: {verification[True]}/{sum(verification.values())} pass.",
            "",
            markdown_table(
                tactic_statistics,
                [
                    "tactic",
                    "closing_rate",
                    "progress_rate",
                    "median_seconds",
                    "p90_seconds",
                    "max_seconds",
                    "errors",
                    "heartbeat_timeouts",
                    "wall_clock_timeouts",
                ],
            ),
            "",
        ]

    SUMMARY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (SUMMARY_DIRECTORY / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    (SUMMARY_DIRECTORY / "summary.md").write_text("\n".join(markdown))


async def main(arguments: argparse.Namespace) -> None:
    problems = load_minif2f()
    valid = [problem for problem in problems if problem.split == Split.VALID]
    if arguments.limit is not None:
        problems, valid = problems[: arguments.limit], valid[: arguments.limit]
    parts = set(arguments.parts.split(","))
    context = {
        "load_average": os.getloadavg(),
        "cgroup_memory_current_gibibytes": cgroup_memory_current() / GIBIBYTE,
        "cgroup_anonymous_gibibytes": cgroup_anonymous_memory() / GIBIBYTE,
    }
    save_part("context", {**(load_part("context") or {}), ",".join(sorted(parts)): context})
    if "statements" in parts:
        save_part("statements", [asdict(check) for check in await check_statements(problems, arguments.pool_size)])
    if "process_costs" in parts:
        save_part("process_costs", [asdict(cost) for cost in await measure_process_costs(valid[0].header, 3)])
    if "memory_growth" in parts:
        samples = await measure_memory_growth(valid, arguments.memory_applications)
        save_part("memory_growth", [asdict(sample) for sample in samples])
    if "concurrency" in parts:
        results = []
        for processes in map(int, arguments.concurrency.split(",")):
            results.append(await measure_concurrency(valid, processes, arguments.concurrency_seconds))
            save_part("concurrency", [asdict(result) for result in results])
    if "sweep" in parts:
        records = await run_sweep(
            valid, arguments.pool_size, arguments.sweep_heartbeats, arguments.sweep_timeout_seconds
        )
        save_part("sweep", [asdict(record) for record in records])
    write_summary(arguments)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", default="statements,process_costs,memory_growth,concurrency,sweep")
    parser.add_argument("--limit", type=int, default=None, help="only the first N problems (smoke test)")
    parser.add_argument("--pool-size", type=int, default=32)
    parser.add_argument("--memory-applications", type=int, default=2000)
    parser.add_argument("--concurrency", default="8,16,32")
    parser.add_argument("--concurrency-seconds", type=float, default=60.0)
    parser.add_argument("--sweep-heartbeats", type=int, default=200_000)
    parser.add_argument("--sweep-timeout-seconds", type=float, default=60.0)
    asyncio.run(main(parser.parse_args()))
