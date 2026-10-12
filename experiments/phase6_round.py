"""Search one expert-iteration round's slice of the prepared statement pool with the current policy and value model.

    python experiments/phase6_round.py --config experiments/configs/expert_iteration/round_0.toml [--limit N]
    python experiments/phase6_round.py --config ... --summarize-only

Takes the round's slice of each source's prepared statements in $LEAN_SEARCH_DATA/<pool>/prepared.jsonl
(experiments/phase6_pool.py), interleaved in proportion, and searches them with the round's run config, whose policy
and value adapters must be served. Writes the standard run
layout to $LEAN_SEARCH_RUNS/phase6_round_<index>/: config.toml, round.toml, results.jsonl, trees/<problem>.json.gz
for every statement, statistics/{policy,value}_<invocation>.json, invocations.jsonl. Re-running resumes: finished
statements are skipped, so the run can be stopped (kill) and restarted at any time; --limit searches only the first N
statements of the slice. The summary (solve rates by source, costs, throughput) goes to
summary/{summary.json,README.md}.
"""

import argparse
import asyncio
import dataclasses
import datetime
import json
import os
import signal
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.corpora.records import StatementRecord, read_statement_records
from lean_search.expert_iteration.config import RoundConfig, adapter_mismatches, load_round_config
from lean_search.expert_iteration.pool import SourceSlice, pool_problem, sliced_statements
from lean_search.expert_iteration.pool_search import (
    Invocation,
    ModelThroughput,
    PoolRunPaths,
    SourceSolveRate,
    TreeSelection,
    append_invocation,
    model_throughput,
    pending_problems,
    read_completed_results,
    read_invocations,
    search_pool,
    source_solve_rates,
)
from lean_search.search import RunConfig, load_run_config
from lean_search.search.summary import RunMetadata, RunSummary, markdown_table, summarize

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])


@dataclass(frozen=True)
class RoundThroughput:
    statements: int
    invocation_hours: float
    statements_per_hour: float
    models: ModelThroughput


@dataclass(frozen=True)
class RoundSearchSummary:
    round_index: int
    pool: str
    statements: tuple[SourceSlice, ...]
    policy_adapter: str
    value_adapter: str
    sources: tuple[SourceSolveRate, ...]
    throughput: RoundThroughput
    invocations: tuple[Invocation, ...]
    search: RunSummary


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="search only the first N statements of the round's slice")
    parser.add_argument("--summarize-only", action="store_true")
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


def round_statements(config: RoundConfig) -> list[StatementRecord]:
    prepared = read_statement_records(DATA_DIRECTORY / config.pool / "prepared.jsonl")
    return sliced_statements(list(prepared), config.statements)


def write_run_files(paths: PoolRunPaths, config_path: Path, search_config_path: Path) -> None:
    paths.directory.mkdir(parents=True, exist_ok=True)
    for source, destination in ((search_config_path, paths.config), (config_path, paths.directory / "round.toml")):
        text = source.read_text(encoding="utf-8")
        if destination.exists() and destination.read_text(encoding="utf-8") != text:
            raise ValueError(f"{destination} differs from {source}: a resumed round must keep its configuration.")
        destination.write_text(text, encoding="utf-8")


def search_round(config: RoundConfig, search_config: RunConfig, paths: PoolRunPaths, limit: int | None) -> None:
    problems = [pool_problem(statement) for statement in round_statements(config)][:limit]
    pending = pending_problems(problems, read_completed_results(paths.results))
    invocation = len(read_invocations(paths.invocations))
    revision, dirty = git_state()
    log(f"Round {config.index}: {len(pending):,} of {len(problems):,} statements pending, invocation {invocation}")
    started_at = now()
    started = time.monotonic()
    # A plain kill then unwinds like Ctrl-C, so the REPLs close and the invocation is recorded.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        asyncio.run(search_pool(pending, search_config, paths, TreeSelection.ALL, invocation, log))
    finally:
        completed = len(pending) - len(pending_problems(pending, read_completed_results(paths.results)))
        append_invocation(
            paths.invocations,
            Invocation(invocation, started_at, revision, dirty, len(pending), completed, time.monotonic() - started),
        )


def summarize_round(config: RoundConfig, config_path: Path, search_config: RunConfig, paths: PoolRunPaths) -> None:
    results = read_completed_results(paths.results)
    invocations = read_invocations(paths.invocations)
    revision, dirty = git_state()
    hours = sum(invocation.wall_seconds for invocation in invocations) / 3600
    metadata = RunMetadata(
        run_name=config.run_name,
        split=f"{config.pool} ({config.statement_count:,} statements)",
        git_revision=invocations[0].git_revision if invocations else revision,
        git_dirty=dirty,
        config_file=config.search_config,
        started_at=invocations[0].started_at if invocations else now(),
        run_wall_seconds=hours * 3600,
        cpu_count=int(os.environ.get("LEAN_SEARCH_CPU_COUNT", os.cpu_count() or 1)),
        load_average_at_start=os.getloadavg()[0],
    )
    statistics_files = sorted(paths.statistics.glob("policy_*.json")), sorted(paths.statistics.glob("value_*.json"))
    summary = RoundSearchSummary(
        round_index=config.index,
        pool=config.pool,
        statements=config.statements,
        policy_adapter=f"{config.policy.name} ({config.policy.path})",
        value_adapter=f"{config.value.name} ({config.value.path})",
        sources=source_solve_rates(results),
        throughput=RoundThroughput(
            statements=len(results),
            invocation_hours=hours,
            statements_per_hour=len(results) / hours if hours else 0.0,
            models=model_throughput(*statistics_files),
        ),
        invocations=tuple(invocations),
        search=summarize(results, metadata, search_config.search),
    )
    paths.summary.mkdir(parents=True, exist_ok=True)
    (paths.summary / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (paths.summary / "config.toml").write_text(paths.config.read_text(encoding="utf-8"), encoding="utf-8")
    (paths.summary / "round.toml").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    markdown = render_markdown(summary)
    (paths.summary / "README.md").write_text(markdown, encoding="utf-8")
    log(markdown)


def distribution_rows(summary: RunSummary) -> list[Sequence[object]]:
    return [
        [table.group, table.problems, entry.metric, f"{entry.mean:.1f}", f"{entry.median:.1f}", f"{entry.p90:.1f}"]
        for table in summary.costs
        for entry in table.distributions
        if entry.metric in ("expansions", "wall_seconds", "lean_seconds")
    ]


def render_markdown(summary: RoundSearchSummary) -> str:
    search = summary.search
    throughput = summary.throughput
    models = throughput.models
    loaded = search.problems - search.start_failures
    source_rows = [
        [rate.source, f"{rate.statements:,}", f"{rate.load_failures:,}", f"{rate.solved:,}", f"{rate.solve_rate:.1%}"]
        for rate in summary.sources
    ]
    (expansion_curve, *_) = search.curves
    sections = [
        f"# Expert-iteration round {summary.round_index}: pool search",
        f"Statements of `{summary.pool}/prepared.jsonl` (loaded, not solved by the automation pre-filter): "
        + ", ".join(f"{piece.source} {piece.offset:,}–{piece.offset + piece.count:,}" for piece in summary.statements)
        + f". Policy {summary.policy_adapter}, value "
        f"{summary.value_adapter}; run config `{search.metadata.config_file}` (copied as `config.toml`), git "
        f"`{search.metadata.git_revision[:10]}`.",
        f"**Solved {search.solved:,}/{search.problems:,} ({search.solve_rate:.1%}; "
        f"{search.solved / max(1, loaded):.1%} of the {loaded:,} that loaded).** Verification failures: "
        f"{search.verification_failures}.",
        "## By source",
        markdown_table(["Source", "Statements", "Load failures", "Solved", "Solve rate (of loaded)"], source_rows),
        "## Anytime curve",
        markdown_table(
            [f"{expansion_curve.metric} ≤", *(f"{point.budget:g}" for point in expansion_curve.points)],
            [["solved", *(point.solved for point in expansion_curve.points)]],
        ),
        "## Stop reasons",
        markdown_table(
            ["Stop reason", "Statements"], [(entry.stop_reason, entry.problems) for entry in search.stop_reasons]
        ),
        "## Cost per statement",
        markdown_table(["Group", "Statements", "Quantity", "Mean", "Median", "p90"], distribution_rows(search)),
        "## Throughput",
        f"{throughput.statements:,} statements in {throughput.invocation_hours:.2f} h of search "
        f"({throughput.statements_per_hour:,.0f} per hour). Policy: {models.policy_requests:,} requests, "
        f"{models.policy_samples:,} samples ({models.samples_per_second:.1f} samples/s over the request window), "
        f"{models.generated_tokens:,} generated tokens, {models.truncated_samples:,} truncated samples. Value: "
        f"{models.value_requests:,} requests, {models.value_prompt_tokens:,} prompt tokens.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    config = load_round_config(arguments.config)
    search_config_path = REPOSITORY_DIRECTORY / config.search_config
    search_config = load_run_config(search_config_path)
    if mismatches := adapter_mismatches(search_config, config.policy, config.value):
        raise ValueError(f"{config.search_config} does not request the round's adapters: {'; '.join(mismatches)}")
    paths = PoolRunPaths(RUNS_DIRECTORY / config.run_name)
    if not arguments.summarize_only:
        write_run_files(paths, arguments.config, search_config_path)
        search_round(config, search_config, paths, arguments.limit)
    summarize_round(config, arguments.config, search_config, paths)


if __name__ == "__main__":
    main()
