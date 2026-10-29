"""Set up, run and inspect the search-tree GRPO loop (src/lean_search/rl/loop.py; deployment/README.md, "GRPO loop").

    python experiments/grpo_loop.py --config experiments/configs/grpo/loop.toml init
    python experiments/grpo_loop.py --config ... start-servers       # start the servers not answering, GPUs in parallel
    python experiments/grpo_loop.py --config ... serve-commands      # print every server's start command
    python experiments/grpo_loop.py --config ... check-servers       # one live request per policy server
    python experiments/grpo_loop.py --config ... run                 # the loop; restart it the same way after a crash
    python experiments/grpo_loop.py --config ... status
    python experiments/grpo_loop.py --config ... report              # solve rate per phase (the overfit curve)
    python experiments/grpo_loop.py --config ... request-evaluation --target minif2f

init records version 0 (the [initial] adapters merged into full weights) and refuses an existing loop. run copies the
config to $LEAN_SEARCH_RUNS/<name>/loop.toml (the evaluation jobs read it), resumes an interrupted phase, and writes
the dashboard's metrics under $LEAN_SEARCH_RUNS/<name>/metrics/ (experiments/dashboard.py serve). request-evaluation
asks the running loop to evaluate a fixed target at its next phase pause; without a running loop use
experiments/grpo_evaluate.py.
"""

import argparse
import asyncio
import dataclasses
import datetime
import functools
import json
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from lean_search.expert_iteration.merging import handoff_merge
from lean_search.expert_iteration.serving import (
    MergedPublisher,
    ModelVersion,
    read_current,
    read_versions,
    record_published,
)
from lean_search.monitoring.store import MetricsWriter
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.loop import GrpoLoop, GrpoLoopPaths, read_progress, request_evaluation
from lean_search.rl.loop_config import GrpoLoopConfig, StatementSourceKind, load_loop_config
from lean_search.rl.loop_services import (
    SubprocessEvaluations,
    VllmServers,
    check_policy_server,
    host_memory_text,
    open_trainer,
    open_tree_searcher,
    serve_commands,
)
from lean_search.rl.renaming import load_renamings
from lean_search.rl.search_models import served_run_config
from lean_search.rl.statement_sources import CurriculumStatements, FixedStatements, StatementSource
from lean_search.rl.tree_store import TreeStore
from lean_search.search import RunConfig, load_run_config
from lean_search.training.resident import HostDirectories

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("start-servers")
    commands.add_parser("serve-commands")
    commands.add_parser("check-servers")
    commands.add_parser("run")
    commands.add_parser("status")
    commands.add_parser("report")
    request = commands.add_parser("request-evaluation")
    request.add_argument("--target", type=EvaluationKind, choices=list(EvaluationKind), required=True)
    return parser.parse_args()


def loop_paths(config: GrpoLoopConfig) -> GrpoLoopPaths:
    return GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.name)


def publisher(config: GrpoLoopConfig, paths: GrpoLoopPaths) -> MergedPublisher:
    """Takes over the training jobs' merges: beside the adapter, or handed off in host memory (persistent job)."""
    return MergedPublisher(
        config.serving, paths.weights, handoff_merge(HostDirectories(config.host_directory()).handoff)
    )


def search_run_config(config: GrpoLoopConfig) -> RunConfig:
    """The search template on the loop's servers, one REPL per concurrent search."""
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / config.sampling.search_config), config.serving)
    concurrency = config.sampling.concurrency
    lean = dataclasses.replace(template.lean, pool_size=concurrency, concurrency=concurrency)
    return dataclasses.replace(template, lean=lean)


def statement_source(config: GrpoLoopConfig, paths: GrpoLoopPaths) -> StatementSource:
    statements = config.statements
    match statements.kind:
        case StatementSourceKind.CURRICULUM:
            held_out = {entry.name for path in statements.held_out for entry in read_fixed_set(DATA_DIRECTORY / path)}
            searched = {entry.problem_name for entry in TreeStore(paths.trees).entries}
            return CurriculumStatements(statements.curriculum, DATA_DIRECTORY, paths.curriculum, held_out, searched)
        case StatementSourceKind.FIXED:
            return FixedStatements(read_fixed_set(DATA_DIRECTORY / statements.fixed))


def logger(paths: GrpoLoopPaths) -> Callable[[str], None]:
    paths.directory.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}"
        print(line, flush=True)
        with paths.log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    return log


def init(config: GrpoLoopConfig, config_text: str, paths: GrpoLoopPaths) -> None:
    if paths.models.current.exists():
        raise SystemExit(f"{paths.directory} already holds a loop; choose another name.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(config_text, encoding="utf-8")
    version = ModelVersion(
        version=0,
        policy_adapter=config.initial.policy_adapter,
        value_adapter=config.initial.value_adapter,
        published_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        trigger="initial",
    )
    prepared = publisher(config, paths).prepare(version)
    record_published(paths.models, prepared)
    print(f"Version 0 recorded in {paths.models.current}. Start the servers:")
    for command in serve_commands(config, publisher(config, paths), prepared):
        print(command)


async def start_servers(config: GrpoLoopConfig, paths: GrpoLoopPaths) -> None:
    servers = VllmServers(config.serving, config.released_servers(), publisher(config, paths))
    down = await servers.unhealthy()
    print(f"Starting {down} on version {read_current(paths.models).version}; the others answer", flush=True)
    await servers.restart(down, read_current(paths.models))


async def check_servers(config: GrpoLoopConfig) -> None:
    policy = search_run_config(config).policy
    for server in config.serving.policy_servers:
        check = await check_policy_server(policy, server.url)
        print(json.dumps(dataclasses.asdict(check), ensure_ascii=False, indent=1))
        if not (check.tokens_recorded and check.tokens_decode_to_text and check.usable_blocks):
            raise SystemExit(f"{server.url}: the response lacks what the search or the trainer needs (above).")


async def run(config: GrpoLoopConfig, paths: GrpoLoopPaths) -> None:
    log = logger(paths)
    stop = asyncio.Event()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(signal_number, stop.set)
    statements = statement_source(config, paths)
    merged = publisher(config, paths)
    servers = VllmServers(config.serving, config.released_servers(), merged)
    evaluations = SubprocessEvaluations(
        paths, config.evaluation.command_prefix, lambda: read_current(paths.models).version
    )
    writer = MetricsWriter(paths.directory)
    log(f"Loop {config.name}: version {read_current(paths.models).version}, {read_progress(paths.progress)}")
    renamings = load_renamings(config.renaming, DATA_DIRECTORY)
    host_memory = functools.partial(host_memory_text, config)
    async with (
        open_tree_searcher(search_run_config(config), statements.headers(), renamings) as searcher,
        open_trainer(paths, config, log) as trainer,
    ):
        phase_template = (REPOSITORY_DIRECTORY / config.training.phase_config).read_text(encoding="utf-8")
        loop = GrpoLoop(
            config,
            paths,
            statements,
            searcher,
            trainer,
            servers,
            merged,
            evaluations,
            writer,
            log,
            phase_template,
            host_memory=host_memory,
        )
        await loop.run(stop)


def status(paths: GrpoLoopPaths) -> None:
    versions = read_versions(paths.models)
    store = TreeStore(paths.trees)
    progress = read_progress(paths.progress)
    print(f"progress: {progress}")
    print(f"versions: {len(versions)}, current {versions[-1] if versions else None}")
    phase_entries = store.phase_entries(progress.phase)
    print(
        f"trees: {len(store.entries)} ({sum(entry.proved for entry in store.entries)} solved); phase "
        f"{progress.phase}: {len(phase_entries)} ({sum(entry.proved for entry in phase_entries)} solved)"
    )
    if paths.phases.exists():
        lines = paths.phases.read_text(encoding="utf-8").splitlines()
        print(f"last phase: {lines[-1] if lines else None}")
    requests = sorted(path.name for path in paths.requests.glob("*")) if paths.requests.exists() else []
    print(f"requested evaluations: {requests}")


def report(paths: GrpoLoopPaths) -> None:
    """Solve rate per phase over the trees each phase trained on (the overfit test's curve), to report.md."""
    store = TreeStore(paths.trees)
    rows = ["| phase | trees | solved | solve rate | proofs | statements |", "|---|---|---|---|---|---|"]
    for phase in sorted({entry.phase for entry in store.entries}):
        entries = store.phase_entries(phase)
        solved = sum(entry.proved for entry in entries)
        rows.append(
            f"| {phase} | {len(entries)} | {solved} | {solved / len(entries):.1%} | "
            f"{sum(entry.proofs for entry in entries)} | {len({entry.problem_name for entry in entries})} |"
        )
    text = f"# {paths.name}: solve rate per phase\n\n" + "\n".join(rows) + "\n"
    (paths.directory / "report.md").write_text(text, encoding="utf-8")
    print(text)


def main() -> None:
    arguments = parse_arguments()
    config_text = arguments.config.read_text(encoding="utf-8")
    config = load_loop_config(arguments.config)
    paths = loop_paths(config)
    match arguments.command:
        case "init":
            init(config, config_text, paths)
        case "start-servers":
            asyncio.run(start_servers(config, paths))
        case "serve-commands":
            for command in serve_commands(config, publisher(config, paths), read_current(paths.models)):
                print(command)
        case "check-servers":
            asyncio.run(check_servers(config))
        case "run":
            paths.config.write_text(config_text, encoding="utf-8")
            asyncio.run(run(config, paths))
        case "status":
            status(paths)
        case "report":
            report(paths)
        case "request-evaluation":
            request_evaluation(paths, arguments.target)
            print(f"The loop evaluates {arguments.target} at its next phase pause.")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
