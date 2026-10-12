"""Prepare the expert-iteration statement pool: stratified candidates, a load check and an automation pre-filter.

    python experiments/phase6_pool.py --config experiments/configs/expert_iteration/pool_v1.toml --name pool_v1 \
        --step select | prefilter [--limit N] | finalize

select: per source the first `candidates` statements of a seeded hash order of the merged, decontaminated pool,
leaving out statements whose proofs the policy was trained on, interleaved so that every prefix is stratified;
import lines are made identical where that does not change the environment. Writes
$LEAN_SEARCH_DATA/expert_iteration/<name>/candidates.jsonl and selection.json.

prefilter: an automation-only search of the candidates in order (the start doubles as the load check), resumable:
re-running skips finished statements. Writes the standard run layout to $LEAN_SEARCH_RUNS/phase6_<name>_prefilter/
(trees of solved statements only: automation-only dead ends say nothing about the policy's search).

finalize: classifies the longest prefix of candidates that all have a result, so outputs only ever grow at the end:
prepared.jsonl (loaded, not solved by automation; the rounds' statements), automation_solved.jsonl, load_failed.jsonl,
summary.json; the statistics go to $LEAN_SEARCH_RUNS/phase6_<name>/summary/{summary.json,README.md}.
"""

import argparse
import asyncio
import dataclasses
import datetime
import json
import os
import shutil
import signal
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.pipeline import statement_key
from lean_search.corpora.records import StatementRecord, read_proof_records, read_statement_records, write_jsonl
from lean_search.expert_iteration.config import PoolConfig, load_pool_config
from lean_search.expert_iteration.pool import (
    PrefilterOutcome,
    SourceSelection,
    canonical_header,
    completed_prefix,
    first_per_name,
    interleave,
    load_failure_category,
    pool_problem,
    prefilter_outcome,
    problem_name,
    problem_source,
    select_by_source,
)
from lean_search.expert_iteration.pool_search import (
    Invocation,
    PoolRunPaths,
    TreeSelection,
    append_invocation,
    pending_problems,
    read_completed_results,
    read_invocations,
    search_pool,
    statements_per_hour,
)
from lean_search.search import RunConfig, SearchResult, load_run_config
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table, percentile

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
TOP_FAILURE_CATEGORIES = 12


class Step(StrEnum):
    SELECT = "select"
    PREFILTER = "prefilter"
    FINALIZE = "finalize"


@dataclass(frozen=True)
class SourceSelectionStatistics:
    source: str
    quota: int
    available: int
    checked: int
    excluded: int
    selected: int


@dataclass(frozen=True)
class SelectionSummary:
    name: str
    built: str
    git_revision: str
    config: PoolConfig
    excluded_statement_keys: int
    headers_rewritten: int
    # Statements of one source with the same identifier (26 in NuminaMath-LEAN); the first in candidate order stays.
    duplicate_names_dropped: int
    candidates: int
    sources: tuple[SourceSelectionStatistics, ...]
    seconds: float


@dataclass(frozen=True)
class LoadFailure:
    problem_name: str
    source: str
    category: str
    message: str


@dataclass(frozen=True)
class FailureCategory:
    category: str
    statements: int


@dataclass(frozen=True)
class SourcePrefilterStatistics:
    source: str
    candidates: int
    processed: int
    load_failed: int
    automation_solved: int
    prepared: int
    load_failure_rate: float
    # Of the statements that loaded.
    automation_solve_rate: float
    failure_categories: tuple[FailureCategory, ...]


@dataclass(frozen=True)
class PrefilterCost:
    mean_wall_seconds: float
    p90_wall_seconds: float
    mean_lean_seconds: float
    mean_expansions: float
    invocation_wall_seconds: float
    statements_per_hour: float


@dataclass(frozen=True)
class PoolSummary:
    name: str
    finalized: str
    git_revision: str
    prefilter_config: str
    max_expansions: int
    max_wall_seconds: float
    concurrency: int
    candidates: int
    processed: int
    prepared: int
    automation_solved: int
    load_failed: int
    sources: tuple[SourcePrefilterStatistics, ...]
    cost: PrefilterCost
    selection: SelectionSummary


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--step", type=Step, choices=list(Step), required=True)
    parser.add_argument("--limit", type=int, help="prefilter only the first N candidates")
    return parser.parse_args()


def git_state() -> tuple[str, bool]:
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
        ).stdout.strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(message, flush=True)


def excluded_statement_keys(config: PoolConfig, cache: Path) -> frozenset[str]:
    if cache.exists():
        return frozenset(cache.read_text(encoding="utf-8").split())
    keys = {
        statement_key(proof.formal_statement)
        for path in config.excluded_proofs
        for proof in read_proof_records(DATA_DIRECTORY / path)
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(keys)) + "\n", encoding="utf-8")
    return frozenset(keys)


def select(config: PoolConfig, output_directory: Path) -> None:
    started = time.perf_counter()
    excluded = excluded_statement_keys(config, output_directory / "excluded_statement_keys.txt")
    log(f"{len(excluded):,} excluded statement keys after {time.perf_counter() - started:.0f} s")
    selections = select_by_source(
        read_statement_records(DATA_DIRECTORY / config.statements),
        config.sources,
        config.seed,
        lambda statement: statement_key(statement.formal_statement) in excluded,
    )
    ordered, duplicate_names = first_per_name(interleave([selection.ordered() for selection in selections]))
    headers_rewritten = sum(canonical_header(statement.header) != statement.header for statement in ordered)
    candidates = [dataclasses.replace(statement, header=canonical_header(statement.header)) for statement in ordered]
    write_jsonl(output_directory / "candidates.jsonl", candidates)
    revision, _ = git_state()
    summary = SelectionSummary(
        name=output_directory.name,
        built=now(),
        git_revision=revision,
        config=config,
        excluded_statement_keys=len(excluded),
        headers_rewritten=headers_rewritten,
        duplicate_names_dropped=duplicate_names,
        candidates=len(candidates),
        sources=tuple(selection_statistics(selection) for selection in selections),
        seconds=time.perf_counter() - started,
    )
    write_json(output_directory / "selection.json", summary)
    for source in summary.sources:
        log(
            f"{source.source}: {source.selected:,} of {source.available:,} selected "
            f"({source.excluded:,} of {source.checked:,} checked were excluded)"
        )
    log(
        f"{len(candidates):,} candidates, {headers_rewritten:,} headers rewritten, {duplicate_names} duplicate names "
        f"dropped, {summary.seconds:.0f} s"
    )


def selection_statistics(selection: SourceSelection) -> SourceSelectionStatistics:
    return SourceSelectionStatistics(
        selection.name,
        selection.capacity,
        selection.available,
        selection.checked,
        selection.excluded,
        len(selection.keyed),
    )


def write_json(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(record), indent=1, ensure_ascii=False), encoding="utf-8")


def prefilter_run_config(config: PoolConfig) -> RunConfig:
    run_config = load_run_config(REPOSITORY_DIRECTORY / config.prefilter_search)
    if run_config.expander.kind.uses_policy:
        raise ValueError("The pre-filter is automation only.")
    return run_config


def prefilter(config: PoolConfig, output_directory: Path, paths: PoolRunPaths, limit: int | None) -> None:
    run_config = prefilter_run_config(config)
    candidates = list(read_statement_records(output_directory / "candidates.jsonl"))[:limit]
    paths.directory.mkdir(parents=True, exist_ok=True)
    config_text = (REPOSITORY_DIRECTORY / config.prefilter_search).read_text(encoding="utf-8")
    if paths.config.exists() and paths.config.read_text(encoding="utf-8") != config_text:
        raise ValueError(f"{paths.config} differs from {config.prefilter_search}; use another --name.")
    paths.config.write_text(config_text, encoding="utf-8")
    problems = [pool_problem(statement) for statement in candidates]
    pending = pending_problems(problems, read_completed_results(paths.results))
    invocation = len(read_invocations(paths.invocations))
    revision, dirty = git_state()
    log(f"{len(pending):,} of {len(problems):,} candidates pending, invocation {invocation}, git {revision[:10]}")
    started_at = now()
    started = time.monotonic()
    # A plain kill then unwinds like Ctrl-C, so the REPLs close and the invocation is recorded.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        asyncio.run(search_pool(pending, run_config, paths, TreeSelection.SOLVED, invocation, log))
    finally:
        completed = len(pending) - len(pending_problems(pending, read_completed_results(paths.results)))
        append_invocation(
            paths.invocations,
            Invocation(invocation, started_at, revision, dirty, len(pending), completed, time.monotonic() - started),
        )


def finalize(config: PoolConfig, output_directory: Path, paths: PoolRunPaths) -> None:
    candidates = list(read_statement_records(output_directory / "candidates.jsonl"))
    results = {result.problem_name: result for result in read_completed_results(paths.results)}
    names = [problem_name(statement) for statement in candidates]
    processed = completed_prefix(names, results)
    outcomes = [prefilter_outcome(results[name]) for name in names[:processed]]
    by_outcome: dict[PrefilterOutcome, list[StatementRecord]] = {outcome: [] for outcome in PrefilterOutcome}
    for statement, outcome in zip(candidates, outcomes, strict=False):
        by_outcome[outcome].append(statement)
    write_jsonl(output_directory / "prepared.jsonl", by_outcome[PrefilterOutcome.UNSOLVED])
    write_jsonl(output_directory / "automation_solved.jsonl", by_outcome[PrefilterOutcome.AUTOMATION_SOLVED])
    failures = [
        load_failure(statement, results[problem_name(statement)])
        for statement in by_outcome[PrefilterOutcome.LOAD_FAILED]
    ]
    write_json_lines(output_directory / "load_failed.jsonl", failures)
    selection = json.loads((output_directory / "selection.json").read_text(encoding="utf-8"))
    run_config = prefilter_run_config(config)
    revision, _ = git_state()
    processed_results = [results[name] for name in names[:processed]]
    summary = PoolSummary(
        name=output_directory.name,
        finalized=now(),
        git_revision=revision,
        prefilter_config=config.prefilter_search,
        max_expansions=run_config.search.max_expansions,
        max_wall_seconds=run_config.search.max_wall_seconds,
        concurrency=run_config.lean.concurrency,
        candidates=len(candidates),
        processed=processed,
        prepared=len(by_outcome[PrefilterOutcome.UNSOLVED]),
        automation_solved=len(by_outcome[PrefilterOutcome.AUTOMATION_SOLVED]),
        load_failed=len(failures),
        sources=tuple(
            source_statistics(quota.name, candidates, processed_results, outcomes, failures) for quota in config.sources
        ),
        cost=prefilter_cost(processed_results, read_invocations(paths.invocations)),
        selection=from_json_object(SelectionSummary, selection),
    )
    write_json(output_directory / "summary.json", summary)
    summary_directory = RUNS_DIRECTORY / f"phase6_{output_directory.name}" / "summary"
    write_json(summary_directory / "summary.json", summary)
    markdown = render_markdown(summary)
    (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    shutil.copyfile(paths.config, summary_directory / "prefilter_config.toml")
    log(markdown)


def load_failure(statement: StatementRecord, result: SearchResult) -> LoadFailure:
    message = result.start_failure or ""
    return LoadFailure(problem_name(statement), statement.source, load_failure_category(message), message)


def write_json_lines(path: Path, records: Sequence[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def source_statistics(
    source: str,
    candidates: Sequence[StatementRecord],
    processed_results: Sequence[SearchResult],
    outcomes: Sequence[PrefilterOutcome],
    failures: Sequence[LoadFailure],
) -> SourcePrefilterStatistics:
    counts = Counter(
        outcome
        for result, outcome in zip(processed_results, outcomes, strict=True)
        if problem_source(result.problem_name) == source
    )
    processed = sum(counts.values())
    loaded = processed - counts[PrefilterOutcome.LOAD_FAILED]
    categories = Counter(failure.category for failure in failures if failure.source == source)
    return SourcePrefilterStatistics(
        source=source,
        candidates=sum(statement.source == source for statement in candidates),
        processed=processed,
        load_failed=counts[PrefilterOutcome.LOAD_FAILED],
        automation_solved=counts[PrefilterOutcome.AUTOMATION_SOLVED],
        prepared=counts[PrefilterOutcome.UNSOLVED],
        load_failure_rate=counts[PrefilterOutcome.LOAD_FAILED] / max(1, processed),
        automation_solve_rate=counts[PrefilterOutcome.AUTOMATION_SOLVED] / max(1, loaded),
        failure_categories=tuple(
            FailureCategory(category, count) for category, count in categories.most_common(TOP_FAILURE_CATEGORIES)
        ),
    )


def prefilter_cost(processed_results: Sequence[SearchResult], invocations: Sequence[Invocation]) -> PrefilterCost:
    walls = [result.accounting.wall_seconds for result in processed_results] or [0.0]
    invocation_seconds = sum(invocation.wall_seconds for invocation in invocations)
    return PrefilterCost(
        mean_wall_seconds=sum(walls) / len(walls),
        p90_wall_seconds=percentile(walls, 0.9),
        mean_lean_seconds=sum(result.accounting.lean_seconds for result in processed_results)
        / max(1, len(processed_results)),
        mean_expansions=sum(result.accounting.expansions for result in processed_results)
        / max(1, len(processed_results)),
        invocation_wall_seconds=invocation_seconds,
        statements_per_hour=statements_per_hour(invocations),
    )


def render_markdown(summary: PoolSummary) -> str:
    selection = summary.selection
    selection_rows = [
        [
            source.source,
            f"{source.available:,}",
            f"{source.excluded:,} / {source.checked:,}",
            f"{source.quota:,}",
            f"{source.selected:,}",
        ]
        for source in selection.sources
    ]
    rows = [
        [
            source.source,
            f"{source.candidates:,}",
            f"{source.processed:,}",
            f"{source.load_failed:,} ({source.load_failure_rate:.1%})",
            f"{source.automation_solved:,} ({source.automation_solve_rate:.1%})",
            f"{source.prepared:,}",
        ]
        for source in summary.sources
    ]
    loaded = summary.processed - summary.load_failed
    rows.append(
        [
            "all",
            f"{summary.candidates:,}",
            f"{summary.processed:,}",
            f"{summary.load_failed:,} ({summary.load_failed / max(1, summary.processed):.1%})",
            f"{summary.automation_solved:,} ({summary.automation_solved / max(1, loaded):.1%})",
            f"{summary.prepared:,}",
        ]
    )
    failure_rows = [
        [source.source, category.category.replace("\n", " "), category.statements]
        for source in summary.sources
        for category in source.failure_categories
    ]
    cost = summary.cost
    sections = [
        f"# Expert-iteration statement pool `{summary.name}`",
        f"Finalized {summary.finalized} (git {summary.git_revision[:10]}). Candidates: per source the first statements "
        f"of a seeded hash order (seed `{selection.config.seed}`) of `{selection.config.statements}` (decontaminated "
        "against miniF2F), leaving out statements with a proof in "
        f"{', '.join(f'`{path}`' for path in selection.config.excluded_proofs)} (the policy was trained on them; "
        "exclusion is checked only for statements that could still be selected), interleaved so that every prefix "
        f"holds the sources in proportion. {selection.headers_rewritten:,} headers had `import Mathlib` alone and now "
        "also import Aesop (Mathlib imports it), so every REPL process imports Mathlib once.",
        markdown_table(["Source", "Available", "Excluded / checked", "Quota", "Selected"], selection_rows),
        "## Load check and automation pre-filter",
        f"Each candidate is searched with the automation sweep only (`{summary.prefilter_config}`: at most "
        f"{summary.max_expansions} expansions, {summary.max_wall_seconds:g} s, {summary.concurrency} REPLs); a failed "
        "start is a load failure. Prepared = loaded and not solved by automation: the rounds search these. The "
        f"longest prefix of candidates that all have a result is classified ({summary.processed:,} of "
        f"{summary.candidates:,}).",
        markdown_table(
            ["Source", "Candidates", "Processed", "Load failures", "Solved by automation (of loaded)", "Prepared"],
            rows,
        ),
        f"Cost: {cost.mean_wall_seconds:.1f} s wall per statement (p90 {cost.p90_wall_seconds:.1f} s), "
        f"{cost.mean_lean_seconds:.1f} Lean s, {cost.mean_expansions:.1f} expansions; "
        f"{cost.statements_per_hour:,.0f} statements per hour over {cost.invocation_wall_seconds / 3600:.2f} h of "
        "finished pre-filter runs (alongside the tracing job).",
        "## Load failures by first error line",
        markdown_table(["Source", "Category", "Statements"], failure_rows),
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    config = load_pool_config(arguments.config)
    output_directory = DATA_DIRECTORY / "expert_iteration" / arguments.name
    paths = PoolRunPaths(RUNS_DIRECTORY / f"phase6_{arguments.name}_prefilter")
    match arguments.step:
        case Step.SELECT:
            select(config, output_directory)
        case Step.PREFILTER:
            prefilter(config, output_directory, paths, arguments.limit)
        case Step.FINALIZE:
            finalize(config, output_directory, paths)


if __name__ == "__main__":
    main()
