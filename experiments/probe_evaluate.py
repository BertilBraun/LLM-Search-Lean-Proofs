"""The probe set searched with any checkpoint, outside a loop (src/lean_search/rl/probe_evaluation.py).

    deployment/background.sh python experiments/probe_evaluate.py \
        --config experiments/configs/grpo/followup/probe_evaluation.toml \
        --name v0_value_v0_run1 --arm v0 --phase 0 --anchor \
        --policy-adapter /workspace/checkpoints/data_rewrite_sft_numbered/adapter --value v0 \
        [--search-config experiments/configs/grpo/search/<other>.toml] [--problems 200] [--keep-merge] \
        [--allow-restarts N] [--allow-other-pinning]
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

The searches start in the config's submission_order: "file" (the set's order) or "longest_proof_first" (the largest
recorded difficulty first, probe v2's the shortest known proof's characters / 100; ties in the set's order), after a
pilot (--problems) took its statements as in file order. Only the start order changes, never a statement or its
search, so it is not part of the run's identity; each session records its order (sessions.jsonl, run.json). A resumed
run starts the statements without a result in its order.

It runs only pinned through deployment/background.sh (the node environment's BACKGROUND_CPU_LIST) and records each
session's CPUs, layout and cgroup CPU counters in pinning.jsonl (run.json holds the counters at the end); a session on
another layout than the run's first is refused unless --allow-other-pinning (recorded).

Servers: the loop config's policy servers (and, with a value model, its value servers) must be up, as
deployment/grpo_loop.sh servers starts them (any version). The command holds the node's serving lock
($LEAN_SEARCH_CHECKPOINTS/serving.lock: a loop, grpo_evaluate.py and run_search.py refuse to start while it is held) and
refuses while a loop under $LEAN_SEARCH_RUNS runs (its loop.pid, or a job it started; an empty or unreadable loop.pid
counts as not running and is reported). Every session merges the adapters (on the training CPUs) once per content (their
weight and config files; under $LEAN_SEARCH_CHECKPOINTS/<output>/weights/) and puts them on the servers by the loop
config's serving.swap: swapped in place as the loop does at a publish, or the servers restarted from the merges. A
server that provably started from byte-identical weights and never slept or swapped since (its trusted pid file, no
port_<port>.swapped mark, and on vLLM 0.31 its log; probe_evaluation.holds_start_weights) is left as it is. Then each
server answers check requests, and the fixed prompts near its merge's fingerprint (taken from the first server freshly
started from the merge, its root checked; a difference above the tolerance is a warning in the session and run.json,
above 1 nat a failed start; it catches gross mix-ups, not adjacent versions). So a resumed run never searches with what
the servers held before; the merges are deleted when the run ends, fails or is interrupted (unless --keep-merge or a
server runs from one), and those a killed run left are deleted at the next start. SIGTERM cancels the run so that this
clean-up runs (exit status 143). A loop started later serves its own current version again when it starts.

A server failure does not end the run: a statement whose search fails on a server (no answer or a 5xx; any other error
ends the run with its traceback) is searched again from scratch, at most [server_failure_retries] times over all of
the run's processes (failures.jsonl), after the servers were checked with no new search starting. A server is dead
after 5 server errors in a row on its requests and a failed short completion after them, or 3 failed /health
checks 10 s apart (or asleep); a dead one is
restarted from the merges by serve_model.sh, verified and recorded as a new session (before it starts, so a restart
cut off midway counts), at most [max_server_restarts] times over all of the run's processes (sessions.jsonl), plus
what --allow-restarts granted (recorded in its session and run.json); then the run stops with exit status 4, which a
supervisor must not resume before someone looked at the servers and granted more. A statement that still fails is
left without a result, counted as dropped (never as unsolved), and the run is not accepted.

The run goes to $LEAN_SEARCH_RUNS/<output>/probe_<name>/: results.jsonl (one per statement), summary.json, trees and
config.toml as a loop's probe run; checkpoint.json (the checkpoint, the run config's digest, concurrency, wall cap and
budget, their identity for the rating, the anchor mark; a rerun resumes, another checkpoint or setting under the name
is refused); sessions.jsonl (each session's starting point and served weights; a session during which a loop came up
is marked spoiled and its results are discarded on resume; how its weights reached the servers, and the servers it
restarted); and run.json: wall-clock stops in total and per stratum against the maximum, the sessions, the server
restarts, the statements searched again and those left without a result, accepted or not, and the node, Lean
toolchain, vLLM and torch. A run with max_wall_clock_stop_share or more stopped on the wall clock is rejected (exit
status 3; repeat it with the cap doubled under another name), and so is one with a statement left without a result
(rerun it under the same name once the servers are sound: only that statement is searched);
probe_rating.finished_probe_runs rates accepted runs only.
"""

import argparse
import asyncio
import dataclasses
import datetime
import functools
import json
import os
import signal
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.lean.repl import PROJECT_DIRECTORY
from lean_search.monitoring.cgroup import cpu_counters
from lean_search.policy.adapters import merge_adapter_on_training_cpus
from lean_search.policy.rotation import RequestFailures
from lean_search.policy.serving_lock import ServingBusyError, serving_lock, serving_lock_path
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    FailureTolerance,
    ServerRecoveryError,
    in_submission_order,
    read_failures,
    run_problem_set_evaluation,
)
from lean_search.rl.fixed_targets import first_problems_by_stratum, probe_problems
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.loop_services import start_servers
from lean_search.rl.node_pinning import record_session_pinning
from lean_search.rl.probe_evaluation import (
    DeathRule,
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunStart,
    ProbeServers,
    ServersDownError,
    ServersUnsoundError,
    SessionServing,
    adapter_digest,
    anchor_problem,
    checkpoint_merges,
    default_value_version,
    discard_spoiled_results,
    dropped_statements,
    keep_merges,
    mark_spoiled,
    merges_in_use,
    probe_run_config,
    read_sessions,
    remove_merges,
    remove_stale_merges,
    resolve_value_adapter,
    restart_allowance,
    run_config_sha256,
    run_directory,
    run_environment,
    run_identity,
    run_record,
    running_loops,
    serve_checkpoint,
    server_restarts,
    start_session,
    stops_by_stratum,
    verify_served,
)
from lean_search.rl.study_configs import resolved_toml
from lean_search.search import load_run_config, read_results
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
# serve_model.sh's logs and pid files: whether a server still holds the weights it started from.
SERVERS_DIRECTORY = RUNS_DIRECTORY / "servers"
FAILURES_FILE = "failures.jsonl"
REJECTED_EXIT_STATUS = 3
# The servers kept dying through the run's restarts: a supervisor must not resume it before someone looked.
RECOVERY_EXIT_STATUS = 4
TERMINATED_EXIT_STATUS = 143


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
    parser.add_argument(
        "--allow-other-pinning",
        action="store_true",
        help="resume although the CPU layout differs from the run's first session's (recorded in pinning.jsonl)",
    )
    parser.add_argument(
        "--allow-restarts",
        type=int,
        default=0,
        help="server restarts granted beyond the config's (after exit status 4, once the servers were looked at)",
    )
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
    refusals = record_session_pinning(directory, True, arguments.allow_other_pinning)
    if refusals:
        raise SystemExit("\n".join(refusals))
    problems = probe_problems(DATA_DIRECTORY / config.probe_set)
    problems = first_problems_by_stratum(problems, chosen.problems) if chosen.problems else problems
    weights_root = CHECKPOINTS_DIRECTORY / config.output / "weights"
    merges = checkpoint_merges(loop.serving, chosen, weights_root)
    log(f"{start.identity}: {start.max_expansions} expansions (the budget rule), {start.concurrency} REPLs")
    try:
        with serving_lock(serving_lock_path(CHECKPOINTS_DIRECTORY)):
            refuse_while_loops_run()
            for stale in remove_stale_merges(weights_root, merges_in_use(SERVERS_DIRECTORY, loop.serving)):
                log(f"Removed {stale}, a merge a dead run left")
            discarded = discard_spoiled_results(directory, paths.results, paths.trees)
            if discarded:
                log(f"Discarded {discarded} results of a session a loop spoiled; they are searched again")
            try:
                verify = functools.partial(verify_served, run_config, log)
                served = await serve_checkpoint(
                    loop.serving, chosen, weights_root, merge_adapter_on_training_cpus, SERVERS_DIRECTORY, verify, log
                )
                log(f"Weights put on {list(served.swapped)} ({served.swap}); already held by {list(served.skipped)}")
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
                serving = SessionServing(
                    served.swap,
                    served.swapped,
                    served.skipped,
                    restarts_granted=arguments.allow_restarts,
                    fingerprint_warnings=served.fingerprint_warnings,
                )
                session = start_session(directory, chosen, paths.results, serving, config.submission_order)
                request_failures = RequestFailures()
                servers = ProbeServers(
                    loop.serving,
                    served,
                    chosen,
                    directory,
                    paths.results,
                    verify,
                    functools.partial(start_servers, servers_directory=SERVERS_DIRECTORY, log=log),
                    request_failures,
                    DeathRule(),
                    config.submission_order,
                )
                sessions = read_sessions(directory)
                tolerance = FailureTolerance(
                    servers,
                    config.server_failure_retries,
                    restart_allowance(sessions, config.max_server_restarts),
                    directory / FAILURES_FILE,
                    len(server_restarts(sessions)),
                    request_failures,
                )
                log(
                    f"{len(problems)} problems of {config.probe_set} into {directory}, started in "
                    f"{config.submission_order} order"
                )
                summary = await run_problem_set_evaluation(
                    EvaluationKind.PROBE,
                    directory.name,
                    (chosen.policy_version, chosen.value_version),
                    in_submission_order(problems, config.submission_order),
                    run_config,
                    paths,
                    log,
                    tolerance=tolerance,
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
                    for kept in remove_merges(merges, merges_in_use(SERVERS_DIRECTORY, loop.serving)):
                        log(f"Kept {kept}: a server runs from it (removed by the next run once none does)")
    except ServerRecoveryError as error:
        log(str(error))
        return RECOVERY_EXIT_STATUS
    except (ServingBusyError, ServersDownError, ServersUnsoundError) as error:
        raise SystemExit(str(error)) from error
    results = read_results(paths.results)
    by_stratum = stops_by_stratum(problems, results)
    record = run_record(
        start,
        run_environment(PROJECT_DIRECTORY),
        summary,
        by_stratum,
        config.max_wall_clock_stop_share,
        read_sessions(directory),
        read_failures(directory / FAILURES_FILE),
        dropped_statements(problems, results),
    )
    record = dataclasses.replace(record, cpu_counters=cpu_counters())
    (directory / "run.json").write_text(to_json(record), encoding="utf-8")
    log(
        f"{summary.solved}/{summary.problems} solved; {summary.wall_clock_stops} searches stopped on the wall clock "
        f"({record.wall_clock_stop_share:.2%}, accepted below {config.max_wall_clock_stop_share:.2%}; by stratum "
        f"{[(stratum.stratum, stratum.wall_clock_stops) for stratum in by_stratum]}); "
        f"{len(record.retried_statements)} statements searched again after a server failure, "
        f"{len(record.server_restarts)} server restarts, left without a result: {list(record.dropped_statements)}: "
        f"{'accepted' if record.accepted else 'rejected'}"
    )
    return 0 if record.accepted else REJECTED_EXIT_STATUS


async def evaluate_until_terminated(arguments: argparse.Namespace) -> int:
    """SIGTERM cancels the run, so that its clean-up (the merges, a server start in progress) runs."""
    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    return await evaluate(arguments)


def main() -> None:
    try:
        status = asyncio.run(evaluate_until_terminated(parse_arguments()))
    except asyncio.CancelledError:
        status = TERMINATED_EXIT_STATUS
    raise SystemExit(status)


if __name__ == "__main__":
    main()
