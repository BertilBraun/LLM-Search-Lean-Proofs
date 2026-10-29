"""Fixed-target evaluations: a problem set searched at a fixed budget with the served version, resumable.

A run directory holds config.toml (the search's run config, which the value benchmark reads for provenance),
results.jsonl (one SearchResult per problem), trees/<problem>.json.gz and, once complete, summary.json; a repeated run
of the same version also holds comparison.json against the first.
"""

import asyncio
import contextlib
import datetime
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.data import Problem
from lean_search.expert_iteration.pool_search import PRELOADED_HEADER_SHARE, common_headers
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.monitoring.families import BandOutcome, FixedTargets
from lean_search.rl.renaming import StatementRenamings, search_problem
from lean_search.rl.search_models import open_search_models, run_config_text
from lean_search.search import CompletedSearch, RunConfig, SearchResult, StopReason, read_results, tree_record
from lean_search.search.records import from_json_object, to_json, write_tree


class EvaluationKind(StrEnum):
    PROBE = "probe"
    MINIF2F = "minif2f"
    HELD_OUT_STATES = "held_out_states"


@dataclass(frozen=True)
class EvaluationProblem:
    problem: Problem
    # The probe's difficulty stratum; empty for miniF2F.
    stratum: str = ""


@dataclass(frozen=True)
class StratumOutcome:
    stratum: str
    problems: int
    solved: int


@dataclass(frozen=True)
class EvaluationSummary:
    kind: EvaluationKind
    run_name: str
    policy_version: int
    value_version: int
    # For held-out states: states and policy samples, `solved` the successful samples.
    problems: int
    solved: int
    by_stratum: tuple[StratumOutcome, ...]
    expansion_budget: int
    expansions: int
    generated_tokens: int
    lean_seconds: float
    wall_seconds: float
    started_at: str
    finished_at: str
    samples: int = 0
    # Searches stopped by the per-problem wall-clock cap rather than the expansion budget.
    wall_clock_stops: int = 0

    @property
    def solve_rate(self) -> float:
        return self.solved / self.problems if self.problems else 0.0


@dataclass(frozen=True)
class RepeatComparison:
    """Two runs of one version on the same problems: the run-to-run noise."""

    problems: int
    first_solved: int
    second_solved: int
    # Solved by one run only; the difference's paired spread.
    only_first: int
    only_second: int

    @property
    def difference(self) -> int:
        return self.second_solved - self.first_solved

    @property
    def discordant(self) -> int:
        return self.only_first + self.only_second


@dataclass(frozen=True)
class EvaluationPaths:
    directory: Path

    @property
    def config(self) -> Path:
        return self.directory / "config.toml"

    @property
    def results(self) -> Path:
        return self.directory / "results.jsonl"

    @property
    def trees(self) -> Path:
        return self.directory / "trees"

    @property
    def summary(self) -> Path:
        return self.directory / "summary.json"

    @property
    def comparison(self) -> Path:
        return self.directory / "comparison.json"


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def stratum_outcomes(problems: Sequence[EvaluationProblem], results: Sequence[SearchResult]) -> list[StratumOutcome]:
    solved = {result.problem_name for result in results if result.proved}
    strata = sorted({problem.stratum for problem in problems if problem.stratum})
    return [
        StratumOutcome(
            stratum,
            sum(problem.stratum == stratum for problem in problems),
            sum(problem.stratum == stratum and problem.problem.name in solved for problem in problems),
        )
        for stratum in strata
    ]


def search_summary(
    kind: EvaluationKind,
    run_name: str,
    versions: tuple[int, int],
    problems: Sequence[EvaluationProblem],
    results: Sequence[SearchResult],
    config: RunConfig,
    started_at: str,
    wall_seconds: float,
) -> EvaluationSummary:
    return EvaluationSummary(
        kind=kind,
        run_name=run_name,
        policy_version=versions[0],
        value_version=versions[1],
        problems=len(problems),
        solved=sum(result.proved for result in results),
        by_stratum=tuple(stratum_outcomes(problems, results)),
        expansion_budget=config.search.max_expansions,
        expansions=sum(result.accounting.expansions for result in results),
        generated_tokens=sum(result.accounting.generated_tokens for result in results),
        lean_seconds=sum(result.accounting.lean_seconds for result in results),
        wall_seconds=wall_seconds,
        started_at=started_at,
        finished_at=now(),
        wall_clock_stops=sum(result.stop_reason == StopReason.WALL_CLOCK_BUDGET for result in results),
    )


def compare_repeats(first: Sequence[SearchResult], second: Sequence[SearchResult]) -> RepeatComparison:
    first_solved = {result.problem_name for result in first if result.proved}
    second_solved = {result.problem_name for result in second if result.proved}
    assert {result.problem_name for result in first} == {result.problem_name for result in second}
    return RepeatComparison(
        problems=len(first),
        first_solved=len(first_solved),
        second_solved=len(second_solved),
        only_first=len(first_solved - second_solved),
        only_second=len(second_solved - first_solved),
    )


def fixed_targets_record(summary: EvaluationSummary, comparison: RepeatComparison | None = None) -> FixedTargets:
    match summary.kind:
        case EvaluationKind.PROBE:
            return FixedTargets(
                probe_solved=summary.solved,
                probe_problems=summary.problems,
                probe_expansion_budget=summary.expansion_budget,
                probe_by_difficulty={
                    outcome.stratum: BandOutcome(outcome.problems, outcome.solved) for outcome in summary.by_stratum
                },
                evaluation_seconds=summary.wall_seconds,
                probe_wall_clock_stops=summary.wall_clock_stops,
                probe_repeat_difference=None if comparison is None else comparison.difference,
                probe_repeat_discordant=None if comparison is None else comparison.discordant,
            )
        case EvaluationKind.MINIF2F:
            return FixedTargets(
                minif2f_valid_solved=summary.solved,
                minif2f_valid_problems=summary.problems,
                expansion_budget=summary.expansion_budget,
                evaluation_seconds=summary.wall_seconds,
                minif2f_wall_clock_stops=summary.wall_clock_stops,
            )
        case EvaluationKind.HELD_OUT_STATES:
            return FixedTargets(
                held_out_success=summary.solved / summary.samples if summary.samples else None,
                held_out_states=summary.problems,
                evaluation_seconds=summary.wall_seconds,
            )


def keep_config(paths: EvaluationPaths, config: RunConfig) -> None:
    text = run_config_text(config)
    if paths.config.exists() and paths.config.read_text(encoding="utf-8") != text:
        raise ValueError(f"{paths.config} holds another config; an evaluation run keeps one.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(text, encoding="utf-8")


async def search_problem_set(
    problems: Sequence[EvaluationProblem],
    config: RunConfig,
    paths: EvaluationPaths,
    log: Callable[[str], None],
    renamings: StatementRenamings | None = None,
) -> list[SearchResult]:
    """Searches the problems without a result yet (renamed when given renamings); returns every problem's result."""
    keep_config(paths, config)
    done = read_results(paths.results) if paths.results.exists() else []
    finished = {result.problem_name for result in done}
    pending = [problem.problem for problem in problems if problem.problem.name not in finished]
    results = list(done)

    async def on_completed(completed: CompletedSearch) -> None:
        result = completed.result
        if completed.tree is not None:
            record = tree_record(completed.tree, completed.tree.root.state.statement, result)
            await asyncio.to_thread(write_tree, paths.trees / f"{result.problem_name}.json.gz", record)
        with paths.results.open("a", encoding="utf-8") as handle:
            handle.write(to_json(result) + "\n")
        results.append(result)
        solved = sum(result.proved for result in results)
        log(f"[{len(results)}/{len(problems)}] {result.problem_name}: {result.stop_reason} | solved {solved}")

    if pending:
        async with contextlib.AsyncExitStack() as stack:
            models = await stack.enter_async_context(open_search_models(config))
            pool = await stack.enter_async_context(
                LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction)
            )
            await pool.start(common_headers(pending, PRELOADED_HEADER_SHARE))
            semaphore = asyncio.Semaphore(config.lean.concurrency)

            async def search_one(problem: Problem) -> None:
                async with semaphore:
                    async with pool.acquire() as repl:
                        completed = await search_problem(
                            problem, repl, models.expander, models.priority_function, config.search, renamings
                        )
                    await on_completed(completed)

            await asyncio.gather(*(search_one(problem) for problem in pending))
        if renamings is not None:
            log(
                f"Renaming: {renamings.missing} problems without a renaming, "
                f"{renamings.failed_original_checks} proofs failed the check against the original statement"
            )
    return results


async def run_problem_set_evaluation(
    kind: EvaluationKind,
    run_name: str,
    versions: tuple[int, int],
    problems: Sequence[EvaluationProblem],
    config: RunConfig,
    paths: EvaluationPaths,
    log: Callable[[str], None],
    renamings: StatementRenamings | None = None,
) -> EvaluationSummary:
    started_at = now()
    started = time.monotonic()
    results = await search_problem_set(problems, config, paths, log, renamings)
    summary = search_summary(
        kind, run_name, versions, problems, results, config, started_at, time.monotonic() - started
    )
    paths.summary.write_text(to_json(summary), encoding="utf-8")
    return summary


def read_summary(path: Path) -> EvaluationSummary:
    return from_json_object(EvaluationSummary, json.loads(path.read_text(encoding="utf-8")))
