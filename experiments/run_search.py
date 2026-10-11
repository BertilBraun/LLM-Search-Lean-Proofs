"""Best-first proof search on miniF2F from a TOML config; writes everything to $LEAN_SEARCH_RUNS/<run-name>/.

    python experiments/run_search.py --config experiments/configs/phase0_automation_baseline.toml \
        --split valid --run-name phase0_automation_baseline [--limit N] [--problems name,...]

Outputs: config.toml and run.json (git revision, metadata), results.jsonl (one SearchResult per theorem),
trees/<theorem>.json.gz (one TreeRecord per theorem), policy.json (PolicyStatistics, for policy expanders),
value.json (ValueStatistics, with a value model) and
summary/{summary.json,summary.md,config.toml,policy.json,value.json}.
"""

import argparse
import asyncio
import contextlib
import datetime
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from lean_search.data import Problem, Split, load_minif2f
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.policy.expander import PolicyExpander, open_policy_expander
from lean_search.search import (
    CompletedSearch,
    Expander,
    RunConfig,
    ValueEstimator,
    build_expander,
    build_priority_function,
    load_run_config,
    read_results,
    search_problems,
    tree_record,
    write_tree,
)
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import RunMetadata, render_markdown, summarize
from lean_search.value.estimator import ValueModelEstimator, open_value_estimator

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RunPaths:
    directory: Path

    @property
    def config(self) -> Path:
        return self.directory / "config.toml"

    @property
    def metadata(self) -> Path:
        return self.directory / "run.json"

    @property
    def results(self) -> Path:
        return self.directory / "results.jsonl"

    @property
    def trees(self) -> Path:
        return self.directory / "trees"

    @property
    def summary(self) -> Path:
        return self.directory / "summary"

    @property
    def policy_statistics(self) -> Path:
        return self.directory / "policy.json"

    @property
    def value_statistics(self) -> Path:
        return self.directory / "value.json"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", type=Split, choices=list(Split), required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--problems", help="comma-separated theorem names")
    parser.add_argument("--allow-test", action="store_true", help="miniF2F-test is reserved for the final ladder")
    parser.add_argument("--summarize-only", action="store_true", help="rebuild the summary from results.jsonl")
    return parser.parse_args()


def select_problems(split: Split, names: str | None, limit: int | None) -> list[Problem]:
    problems = load_minif2f(split)
    if names is not None:
        wanted = [name.strip() for name in names.split(",") if name.strip()]
        known = {problem.name for problem in problems}
        unknown = [name for name in wanted if name not in known]
        if unknown:
            raise ValueError(f"Unknown problems in {split}: {unknown}")
        problems = [problem for problem in problems if problem.name in set(wanted)]
    return problems if limit is None else problems[:limit]


def git_state() -> tuple[str, bool]:
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
        ).stdout.strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


def write_summary(paths: RunPaths, metadata: RunMetadata, config: RunConfig) -> None:
    results = read_results(paths.results)
    summary = summarize(results, metadata, config.search)
    paths.summary.mkdir(parents=True, exist_ok=True)
    (paths.summary / "summary.json").write_text(
        json.dumps(asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    title = f"Proof search: {metadata.run_name}"
    (paths.summary / "summary.md").write_text(render_markdown(summary, title), encoding="utf-8")
    (paths.summary / "config.toml").write_text(paths.config.read_text(encoding="utf-8"), encoding="utf-8")
    if paths.policy_statistics.exists():
        shutil.copyfile(paths.policy_statistics, paths.summary / "policy.json")
    if paths.value_statistics.exists():
        shutil.copyfile(paths.value_statistics, paths.summary / "value.json")
    print(f"Solved {summary.solved}/{summary.problems} ({summary.solve_rate:.1%}); summary in {paths.summary}")


async def run_searches(problems: list[Problem], config: RunConfig, paths: RunPaths) -> None:
    async with contextlib.AsyncExitStack() as stack:
        policy: PolicyExpander | None = None
        if config.expander.kind.uses_policy:
            policy = await stack.enter_async_context(open_policy_expander(config.policy, config.search.forbidden_steps))
        value_estimator: ValueModelEstimator | None = None
        if config.value.model:
            value_estimator = await stack.enter_async_context(open_value_estimator(config.value))
        try:
            await search_with_expander(problems, config, paths, build_expander(config, policy), value_estimator)
        finally:
            if policy is not None:
                paths.policy_statistics.write_text(to_json(policy.statistics), encoding="utf-8")
            if value_estimator is not None:
                paths.value_statistics.write_text(to_json(value_estimator.statistics), encoding="utf-8")


async def search_with_expander(
    problems: list[Problem],
    config: RunConfig,
    paths: RunPaths,
    expander: Expander,
    value_estimator: ValueEstimator | None,
) -> None:
    priority_function = build_priority_function(config.priority, value_estimator)
    statements = {problem.name: problem.formal_statement for problem in problems}
    completed_count = 0
    solved_count = 0

    async def on_completed(completed: CompletedSearch) -> None:
        nonlocal completed_count, solved_count
        result = completed.result
        completed_count += 1
        solved_count += result.proved
        with paths.results.open("a", encoding="utf-8") as results_file:
            results_file.write(to_json(result) + "\n")
        if completed.tree is not None:
            statement = statements[result.problem_name]
            record = tree_record(completed.tree, statement, result)
            await asyncio.to_thread(write_tree, paths.trees / f"{result.problem_name}.json.gz", record)
        accounting = result.accounting
        print(
            f"[{completed_count}/{len(problems)}] {result.problem_name}: {result.stop_reason}"
            f" steps={len(result.proof_steps)} expansions={accounting.expansions} nodes={accounting.nodes}"
            f" lean={accounting.lean_seconds:.1f}s wall={accounting.wall_seconds:.1f}s"
            f" | solved {solved_count}/{completed_count}",
            flush=True,
        )

    async with LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction) as pool:
        started = time.monotonic()
        await pool.start(sorted({problem.header for problem in problems}))
        print(f"Pool of {config.lean.pool_size} ready in {time.monotonic() - started:.1f}s", flush=True)
        await search_problems(
            problems, pool, expander, priority_function, config.search, config.lean.concurrency, on_completed
        )


def main() -> None:
    arguments = parse_arguments()
    paths = RunPaths(Path(os.environ["LEAN_SEARCH_RUNS"]) / arguments.run_name)
    if arguments.summarize_only:
        metadata = from_json_object(RunMetadata, json.loads(paths.metadata.read_text(encoding="utf-8")))
        write_summary(paths, metadata, load_run_config(paths.config))
        return
    if arguments.split == Split.TEST and not arguments.allow_test:
        raise ValueError("miniF2F-test is reserved for the final ladder; pass --allow-test to use it.")
    if paths.results.exists():
        raise ValueError(f"{paths.results} exists; choose another --run-name.")
    config = load_run_config(arguments.config)
    problems = select_problems(arguments.split, arguments.problems, arguments.limit)
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(arguments.config.read_text(encoding="utf-8"), encoding="utf-8")
    revision, dirty = git_state()
    metadata = RunMetadata(
        run_name=arguments.run_name,
        split=str(arguments.split),
        git_revision=revision,
        git_dirty=dirty,
        config_file=arguments.config.as_posix(),
        started_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        run_wall_seconds=0.0,
        cpu_count=int(os.environ.get("LEAN_SEARCH_CPU_COUNT", os.cpu_count() or 1)),
        load_average_at_start=os.getloadavg()[0],
    )
    paths.metadata.write_text(to_json(metadata), encoding="utf-8")
    print(f"{len(problems)} problems from miniF2F-{arguments.split}, git {revision[:10]}, run {paths.directory}")
    started = time.monotonic()
    asyncio.run(run_searches(problems, config, paths))
    metadata = replace(metadata, run_wall_seconds=time.monotonic() - started)
    paths.metadata.write_text(to_json(metadata), encoding="utf-8")
    write_summary(paths, metadata, config)


if __name__ == "__main__":
    main()
