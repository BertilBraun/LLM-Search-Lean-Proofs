"""The probe set searched with any checkpoint, outside a loop (src/lean_search/rl/probe_evaluation.py).

    python experiments/probe_evaluate.py --config experiments/configs/grpo/followup/probe_evaluation.toml \
        --name v0_value_v0_run1 --arm v0 --phase 0 --anchor \
        --policy-adapter /workspace/checkpoints/data_rewrite_sft_numbered/adapter --value v0 \
        [--search-config experiments/configs/grpo/search/<other>.toml] [--problems 200] [--keep-merge]
    --value none             no value model: best-first on the path's mean step log-probability per block (the
                             config's [value_free_priority]: the policy's step log-probability and its calibrated
                             automation constant; refused for a placeholder; other priority settings kept)
    --value v0               the loop config's [initial] value_adapter (value version 0)
    --value PATH             a value adapter (give --value-version, the rating's label)
    --anchor                 the rating's anchor: the loop config's starting policy and value adapters (checked by
                             content) at the standard settings (no --search-config, no --problems); probe_rating
                             rates every run against it

The budget rule: a run given --search-config searches at that file's own max_expansions (even when it names the
config's default file), every other run at the config's [probe] max_expansions.

Servers: the loop config's policy servers (and, with a value model, its value servers) must be up, as
deployment/grpo_loop.sh servers starts them (any version). The command holds the node's serving lock
($LEAN_SEARCH_CHECKPOINTS/serving.lock: a loop, grpo_evaluate.py and run_search.py refuse to start while it is held)
and refuses while a loop under $LEAN_SEARCH_RUNS runs (its loop.pid, or a job it started; an empty or unreadable
loop.pid counts as not running and is reported). Every session merges the adapters on the CPU once per content (their
weight and config files; under $LEAN_SEARCH_CHECKPOINTS/<output>/weights/) and swaps them into the servers in place,
as the loop does at a publish, so a resumed run never searches with what the servers held before; the merges are
deleted when the run ends, fails or is interrupted (unless --keep-merge), and those a killed run left are deleted at
the next start. A loop started later serves its own current version again when it starts.

The run goes to $LEAN_SEARCH_RUNS/<output>/probe_<name>/: results.jsonl (one per statement), summary.json, trees and
config.toml as a loop's probe run; checkpoint.json (the checkpoint, the run config's digest, concurrency, wall cap and
budget, their identity for the rating, the anchor mark; a rerun resumes, another checkpoint or setting under the name
is refused); sessions.jsonl (each session's starting point and served weights; a session during which a loop came up
is marked spoiled and its results are discarded on resume); and run.json: wall-clock stops in total and per stratum
against the maximum, accepted or not, and the node, Lean toolchain, vLLM and torch. A run with
max_wall_clock_stop_share or more stopped on the wall clock is rejected (exit status 3; repeat it with the cap doubled
under another name); probe_rating.finished_probe_runs rates accepted runs only.
"""

import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.lean.repl import PROJECT_DIRECTORY
from lean_search.policy.adapters import merge_adapter
from lean_search.policy.serving_lock import ServingBusyError, serving_lock, serving_lock_path
from lean_search.rl.evaluation import EvaluationKind, EvaluationPaths, run_problem_set_evaluation
from lean_search.rl.fixed_targets import first_problems_by_stratum, probe_problems
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunStart,
    ServersDownError,
    adapter_digest,
    anchor_problem,
    checkpoint_merges,
    default_value_version,
    discard_spoiled_results,
    keep_merges,
    mark_spoiled,
    probe_run_config,
    remove_merges,
    remove_stale_merges,
    resolve_value_adapter,
    run_config_sha256,
    run_directory,
    run_environment,
    run_identity,
    run_record,
    running_loops,
    serve_checkpoint,
    start_session,
    stops_by_stratum,
)
from lean_search.rl.study_configs import resolved_toml
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
    parser.add_argument(
        "--search-config",
        type=Path,
        help="in place of the config's; the run then searches at this file's own max_expansions",
    )
    parser.add_argument("--problems", type=int, default=0, help="only the first N, strata in turn (a pilot)")
    parser.add_argument("--anchor", action="store_true", help="the rating's anchor (v0 with value v0, standard)")
    parser.add_argument("--keep-merge", action="store_true", help="keep the merged weights after the run")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def load_config(path: Path) -> ProbeEvaluationConfig:
    """The file over its `base` evaluation config, if it names one (the study's configs inherit the probe's)."""
    return from_json_object(ProbeEvaluationConfig, resolved_toml(path, REPOSITORY_DIRECTORY))


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
    chosen = ProbeCheckpoint(
        arm=arguments.arm,
        phase=arguments.phase,
        policy_adapter=str(arguments.policy_adapter.absolute()),
        policy_digest=adapter_digest(arguments.policy_adapter),
        value_adapter=value_adapter,
        value_digest=adapter_digest(Path(value_adapter)) if value_adapter else "",
        problems=arguments.problems,
        policy_version=arguments.phase,
        value_version=value_version,
    )
    if arguments.anchor:
        problem = anchor_problem(
            chosen,
            adapter_digest(Path(loop.initial.policy_adapter)),
            adapter_digest(Path(loop.initial.value_adapter)),
            arguments.search_config is not None,
        )
        if problem is not None:
            raise SystemExit(f"--anchor refused: {problem}.")
    return chosen


def refuse_while_loops_run() -> None:
    activity = running_loops(RUNS_DIRECTORY)
    for note in activity.notes:
        log(note)
    if activity.running:
        raise SystemExit(f"Loops run on this node: {list(activity.running)}; a probe evaluation runs with none beside.")


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
    try:
        run_config = probe_run_config(
            template, loop.serving, config.probe, value_free, arguments.search_config is not None
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    digest = run_config_sha256(run_config)
    start = ProbeRunStart(
        identity=run_identity(chosen, run_config),
        anchor=arguments.anchor,
        checkpoint=chosen,
        search_config=search_config,
        run_config_sha256=digest,
        concurrency=run_config.lean.concurrency,
        max_wall_seconds=run_config.search.max_wall_seconds,
        max_expansions=run_config.search.max_expansions,
        probe_set=config.probe_set,
        probe_set_sha256=file_sha256(DATA_DIRECTORY / config.probe_set),
    )
    directory = run_directory(RUNS_DIRECTORY / config.output, arguments.name)
    paths = EvaluationPaths(directory)
    refuse_another_start(directory / "checkpoint.json", start)
    problems = probe_problems(DATA_DIRECTORY / config.probe_set)
    problems = first_problems_by_stratum(problems, chosen.problems) if chosen.problems else problems
    weights_root = CHECKPOINTS_DIRECTORY / config.output / "weights"
    merges = checkpoint_merges(loop.serving, chosen, weights_root)
    log(f"{start.identity}: {start.max_expansions} expansions (the budget rule), {start.concurrency} REPLs")
    try:
        with serving_lock(serving_lock_path(CHECKPOINTS_DIRECTORY)):
            refuse_while_loops_run()
            for stale in remove_stale_merges(weights_root):
                log(f"Removed {stale}, a merge a dead run left")
            discarded = discard_spoiled_results(directory, paths.results, paths.trees)
            if discarded:
                log(f"Discarded {discarded} results of a session a loop spoiled; they are searched again")
            try:
                await serve_checkpoint(loop.serving, chosen, weights_root, merge_adapter)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
                session = start_session(directory, chosen, paths.results)
                log(f"{len(problems)} problems of {config.probe_set} into {directory}")
                summary = await run_problem_set_evaluation(
                    EvaluationKind.PROBE,
                    directory.name,
                    (chosen.policy_version, chosen.value_version),
                    problems,
                    run_config,
                    paths,
                    log,
                )
                activity = running_loops(RUNS_DIRECTORY)
                if activity.running:
                    mark_spoiled(directory, session)
                    raise SystemExit(
                        f"Loops came up during the run: {list(activity.running)}; this session's results are "
                        "discarded when the run resumes."
                    )
            finally:
                if arguments.keep_merge:
                    keep_merges([merge for merge in merges if merge.is_dir()])
                else:
                    remove_merges(merges)
    except (ServingBusyError, ServersDownError) as error:
        raise SystemExit(str(error)) from error
    by_stratum = stops_by_stratum(problems, read_results(paths.results))
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
