"""Searching pool statements in the standard run layout (results.jsonl, trees/), resumable theorem by theorem."""

import asyncio
import contextlib
import json
import os
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.data import Problem
from lean_search.expert_iteration.pool import problem_source
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.policy.expander import PolicyExpander, PolicyStatistics, open_policy_expander
from lean_search.search import (
    CompletedSearch,
    RunConfig,
    SearchResult,
    StopReason,
    build_expander,
    build_priority_function,
    search_problems,
    tree_record,
    write_tree,
)
from lean_search.search.records import from_json_object, to_json
from lean_search.value.estimator import ValueModelEstimator, ValueStatistics, open_value_estimator

STATISTICS_INTERVAL = 50


class TreeSelection(StrEnum):
    ALL = "all"
    SOLVED = "solved"


@dataclass(frozen=True)
class PoolRunPaths:
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
    def invocations(self) -> Path:
        return self.directory / "invocations.jsonl"

    @property
    def statistics(self) -> Path:
        return self.directory / "statistics"

    @property
    def summary(self) -> Path:
        return self.directory / "summary"

    def tree(self, problem_name: str) -> Path:
        return self.trees / f"{problem_name}.json.gz"

    def policy_statistics(self, invocation: int) -> Path:
        return self.statistics / f"policy_{invocation:03d}.json"

    def value_statistics(self, invocation: int) -> Path:
        return self.statistics / f"value_{invocation:03d}.json"


@dataclass(frozen=True)
class Invocation:
    index: int
    started_at: str
    git_revision: str
    git_dirty: bool
    pending_problems: int
    completed_problems: int
    wall_seconds: float


@dataclass(frozen=True)
class SourceSolveRate:
    source: str
    statements: int
    load_failures: int
    solved: int
    # Of the statements that loaded.
    solve_rate: float


@dataclass(frozen=True)
class ModelThroughput:
    policy_requests: int
    policy_samples: int
    policy_prompt_tokens: int
    generated_tokens: int
    truncated_samples: int
    value_requests: int
    value_prompt_tokens: int
    # From each invocation's first policy request to its last response, summed.
    policy_window_seconds: float
    samples_per_second: float


def read_completed_results(path: Path) -> list[SearchResult]:
    """The results written so far; a last line cut short by a killed run is dropped and the file rewritten."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    results: list[SearchResult] = []
    kept_lines: list[str] = []
    for line in lines:
        try:
            results.append(from_json_object(SearchResult, json.loads(line)))
        except json.JSONDecodeError:
            continue
        kept_lines.append(line)
    if len(kept_lines) != len(lines):
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text("".join(line + "\n" for line in kept_lines), encoding="utf-8")
        os.replace(temporary, path)
    return results


def read_invocations(path: Path) -> list[Invocation]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(Invocation, json.loads(line)) for line in lines if line.strip()]


def append_invocation(path: Path, invocation: Invocation) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(to_json(invocation) + "\n")


def model_throughput(policy_paths: Sequence[Path], value_paths: Sequence[Path]) -> ModelThroughput:
    """Totals over the per-invocation statistics files of a run."""
    policy = [from_json_object(PolicyStatistics, json.loads(path.read_text(encoding="utf-8"))) for path in policy_paths]
    value = [from_json_object(ValueStatistics, json.loads(path.read_text(encoding="utf-8"))) for path in value_paths]
    samples = sum(statistics.samples for statistics in policy)
    window_seconds = sum(statistics.window_seconds for statistics in policy)
    return ModelThroughput(
        policy_requests=sum(statistics.requests for statistics in policy),
        policy_samples=samples,
        policy_prompt_tokens=sum(statistics.prompt_tokens for statistics in policy),
        generated_tokens=sum(statistics.generated_tokens for statistics in policy),
        truncated_samples=sum(statistics.truncated_samples for statistics in policy),
        value_requests=sum(statistics.requests for statistics in value),
        value_prompt_tokens=sum(statistics.prompt_tokens for statistics in value),
        policy_window_seconds=window_seconds,
        samples_per_second=samples / window_seconds if window_seconds else 0.0,
    )


def source_solve_rates(results: Sequence[SearchResult]) -> tuple[SourceSolveRate, ...]:
    statements: Counter[str] = Counter()
    load_failures: Counter[str] = Counter()
    solved: Counter[str] = Counter()
    for result in results:
        source = problem_source(result.problem_name)
        statements[source] += 1
        load_failures[source] += result.stop_reason == StopReason.START_FAILED
        solved[source] += result.proved
    return tuple(
        SourceSolveRate(
            source,
            statements[source],
            load_failures[source],
            solved[source],
            solved[source] / max(1, statements[source] - load_failures[source]),
        )
        for source in sorted(statements)
    )


def pending_problems(problems: Sequence[Problem], completed: Sequence[SearchResult]) -> list[Problem]:
    done = {result.problem_name for result in completed}
    return [problem for problem in problems if problem.name not in done]


async def search_pool(
    problems: Sequence[Problem],
    config: RunConfig,
    paths: PoolRunPaths,
    trees: TreeSelection,
    invocation: int,
    log: Callable[[str], None],
) -> None:
    """Searches the problems, appending each result as it completes; trees of all or only of solved problems."""
    async with contextlib.AsyncExitStack() as stack:
        policy: PolicyExpander | None = None
        if config.expander.kind.uses_policy:
            policy = await stack.enter_async_context(open_policy_expander(config.policy, config.search.forbidden_steps))
        value_estimator: ValueModelEstimator | None = None
        if config.value.model:
            value_estimator = await stack.enter_async_context(open_value_estimator(config.value))

        def write_statistics() -> None:
            paths.statistics.mkdir(parents=True, exist_ok=True)
            if policy is not None:
                paths.policy_statistics(invocation).write_text(to_json(policy.statistics), encoding="utf-8")
            if value_estimator is not None:
                paths.value_statistics(invocation).write_text(to_json(value_estimator.statistics), encoding="utf-8")

        expander = build_expander(config, policy)
        priority_function = build_priority_function(config.priority, value_estimator)
        statements = {problem.name: problem.formal_statement for problem in problems}
        completed_count = 0
        solved_count = 0

        async def on_completed(completed: CompletedSearch) -> None:
            nonlocal completed_count, solved_count
            result = completed.result
            completed_count += 1
            solved_count += result.proved
            if completed.tree is not None and (trees == TreeSelection.ALL or result.proved):
                record = tree_record(completed.tree, statements[result.problem_name], result)
                await asyncio.to_thread(write_tree, paths.tree(result.problem_name), record)
            # The result is written after its tree, so a resumed run never lacks the tree of a completed theorem.
            with paths.results.open("a", encoding="utf-8") as results_file:
                results_file.write(to_json(result) + "\n")
            if completed_count % STATISTICS_INTERVAL == 0:
                write_statistics()
            accounting = result.accounting
            log(
                f"[{completed_count}/{len(problems)}] {result.problem_name}: {result.stop_reason}"
                f" steps={len(result.proof_steps)} expansions={accounting.expansions} nodes={accounting.nodes}"
                f" lean={accounting.lean_seconds:.1f}s wall={accounting.wall_seconds:.1f}s"
                f" | solved {solved_count}/{completed_count}"
            )

        try:
            async with LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction) as pool:
                started = time.monotonic()
                await pool.start(sorted({problem.header for problem in problems}))
                log(f"Pool of {config.lean.pool_size} ready in {time.monotonic() - started:.1f}s")
                await search_problems(
                    problems, pool, expander, priority_function, config.search, config.lean.concurrency, on_completed
                )
        finally:
            write_statistics()
