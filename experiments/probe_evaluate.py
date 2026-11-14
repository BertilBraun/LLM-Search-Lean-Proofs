"""The probe set searched with any checkpoint, outside a loop (src/lean_search/rl/probe_evaluation.py).

    python experiments/probe_evaluate.py --config experiments/configs/grpo/followup/probe_evaluation.toml \
        --name v0_value_v0_run1 --arm v0 --phase 0 \
        --policy-adapter /workspace/checkpoints/data_rewrite_sft_numbered/adapter --value v0 \
        [--search-config experiments/configs/grpo/search/<other>.toml] [--problems 200] [--keep-merge]
    --value none             no value model: best-first on the path's mean step log-probability per block (the
                             config's [value_free_priority]; the search config's other priority settings kept)
    --value v0               the loop config's [initial] value_adapter (value version 0)
    --value PATH             a value adapter (give --value-version, the rating's label)

Servers: the loop config's policy servers (and, with a value model, its value servers) must be up, as
deployment/grpo_loop.sh servers starts them (any version). The command refuses while a loop under $LEAN_SEARCH_RUNS
runs (its loop.pid or a job it started) or another probe evaluation holds
$LEAN_SEARCH_CHECKPOINTS/<output>/serving.lock, and checks the loops again before it records the run. It merges the
adapters on the CPU once per content (under $LEAN_SEARCH_CHECKPOINTS/<output>/weights/), swaps them into the servers
in place, as the loop does at a publish, and deletes the merges after the run unless --keep-merge. A loop started
later serves its own current version again when it starts.

The run goes to $LEAN_SEARCH_RUNS/<output>/probe_<name>/: results.jsonl (one per statement), summary.json, trees and
config.toml as a loop's probe run, checkpoint.json (the checkpoint, its identity for the rating, the run config's
digest, concurrency, wall cap and budget; a rerun resumes, another checkpoint or setting under the name is refused) and
run.json: wall-clock stops in total and per stratum against the maximum, accepted or not, and the node, Lean
toolchain, vLLM and torch. A run with max_wall_clock_stop_share or more stopped on the wall clock is rejected (exit
status 3; repeat it with the cap doubled under another name); probe_rating.finished_probe_runs rates accepted runs only.
"""

import argparse
import asyncio
import datetime
import json
import os
import tomllib
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.lean.repl import PROJECT_DIRECTORY
from lean_search.policy.adapters import merge_adapter
from lean_search.rl.evaluation import EvaluationKind, EvaluationPaths, run_problem_set_evaluation
from lean_search.rl.fixed_targets import first_problems_by_stratum, probe_problems
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunStart,
    ServersDownError,
    ServingBusyError,
    default_value_version,
    directory_digest,
    probe_run_config,
    remove_merges,
    resolve_value_adapter,
    run_config_sha256,
    run_directory,
    run_environment,
    run_record,
    running_loops,
    serve_checkpoint,
    serving_lock,
    stops_by_stratum,
)
from lean_search.search import load_run_config, read_results
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
REJECTED_EXIT_STATUS = 3


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True, help="the run's directory: <output>/probe_<name>")
    parser.add_argument("--arm", required=True, help='the series, e.g. "v0", "A", "step2_B2_5e-5"')
    parser.add_argument("--phase", type=int, required=True, help="the checkpoint's phase in its arm (0: v0)")
    parser.add_argument("--policy-adapter", type=Path, required=True)
    parser.add_argument("--value", required=True, help='"none", "v0" or a value adapter\'s path')
    parser.add_argument("--value-version", type=int, help="the rating's label of a value adapter given by path")
    parser.add_argument("--search-config", type=Path, help="in place of the config's, with its own expansion budget")
    parser.add_argument("--problems", type=int, default=0, help="only the first N, strata in turn (a pilot)")
    parser.add_argument("--keep-merge", action="store_true", help="keep the merged weights after the run")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def load_config(path: Path) -> ProbeEvaluationConfig:
    return from_json_object(ProbeEvaluationConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def checkpoint(arguments: argparse.Namespace, loop: GrpoLoopConfig) -> ProbeCheckpoint:
    value_version = default_value_version(arguments.value)
    value_version = arguments.value_version if value_version is None else value_version
    if value_version is None:
        raise SystemExit("--value with an adapter's path needs --value-version.")
    value_adapter = resolve_value_adapter(arguments.value, loop.initial.value_adapter)
    adapters = [arguments.policy_adapter, *([Path(value_adapter)] if value_adapter else [])]
    missing = [str(adapter) for adapter in adapters if not adapter.is_dir()]
    if missing:
        raise SystemExit(f"No adapter directory at {missing}.")
    return ProbeCheckpoint(
        arm=arguments.arm,
        phase=arguments.phase,
        policy_adapter=str(arguments.policy_adapter.absolute()),
        policy_digest=directory_digest(arguments.policy_adapter),
        value_adapter=value_adapter,
        value_digest=directory_digest(Path(value_adapter)) if value_adapter else "",
        problems=arguments.problems,
        policy_version=arguments.phase,
        value_version=value_version,
    )


def refuse_while_busy() -> None:
    running = running_loops(RUNS_DIRECTORY)
    if running:
        raise SystemExit(f"Loops run on this node: {running}; a probe evaluation runs with none beside it.")


def refuse_another_start(path: Path, start: ProbeRunStart) -> None:
    """A resumed run must search the checkpoint with the settings it began with."""
    if path.exists() and from_json_object(ProbeRunStart, json.loads(path.read_text(encoding="utf-8"))) != start:
        raise SystemExit(f"{path} holds another checkpoint or setting; choose another --name.")


async def evaluate(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    loop = load_loop_config(REPOSITORY_DIRECTORY / config.loop_config)
    chosen = checkpoint(arguments, loop)
    search_config = str(arguments.search_config or config.search_config)
    template = load_run_config(REPOSITORY_DIRECTORY / search_config)
    value_free = None if chosen.value_adapter else config.value_free_priority
    run_config = probe_run_config(template, loop.serving, config.probe, value_free, arguments.search_config is not None)
    start = ProbeRunStart(
        identity=chosen.identity,
        checkpoint=chosen,
        search_config=search_config,
        run_config_sha256=run_config_sha256(run_config),
        concurrency=run_config.lean.concurrency,
        max_wall_seconds=run_config.search.max_wall_seconds,
        max_expansions=run_config.search.max_expansions,
        probe_set=config.probe_set,
        probe_set_sha256=file_sha256(DATA_DIRECTORY / config.probe_set),
    )
    directory = run_directory(RUNS_DIRECTORY / config.output, arguments.name)
    refuse_another_start(directory / "checkpoint.json", start)
    problems = probe_problems(DATA_DIRECTORY / config.probe_set)
    problems = first_problems_by_stratum(problems, chosen.problems) if chosen.problems else problems
    try:
        with serving_lock(CHECKPOINTS_DIRECTORY / config.output / "serving.lock"):
            refuse_while_busy()
            log(f"Serving {chosen.identity}: merging unless merged before, then swapping into the servers")
            served = await serve_checkpoint(
                loop.serving, chosen, CHECKPOINTS_DIRECTORY / config.output / "weights", merge_adapter
            )
            try:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
                log(f"{len(problems)} problems of {config.probe_set} into {directory}")
                summary = await run_problem_set_evaluation(
                    EvaluationKind.PROBE,
                    directory.name,
                    (chosen.policy_version, chosen.value_version),
                    problems,
                    run_config,
                    EvaluationPaths(directory),
                    log,
                )
            finally:
                if not arguments.keep_merge:
                    remove_merges(served)
            refuse_while_busy()
    except (ServingBusyError, ServersDownError) as error:
        raise SystemExit(str(error)) from error
    by_stratum = stops_by_stratum(problems, read_results(EvaluationPaths(directory).results))
    record = run_record(
        start, run_environment(PROJECT_DIRECTORY), summary, by_stratum, config.max_wall_clock_stop_share
    )
    (directory / "run.json").write_text(to_json(record), encoding="utf-8")
    log(
        f"{summary.solved}/{summary.problems} solved; {summary.wall_clock_stops} searches stopped on the wall clock "
        f"({record.wall_clock_stop_share:.2%}, accepted below {config.max_wall_clock_stop_share:.2%}; by stratum "
        f"{[(stratum.stratum, stratum.wall_clock_stops) for stratum in by_stratum]}): "
        f"{'accepted' if record.accepted else 'rejected'}"
    )
    return 0 if record.accepted else REJECTED_EXIT_STATUS


def main() -> None:
    raise SystemExit(asyncio.run(evaluate(parse_arguments())))


if __name__ == "__main__":
    main()
