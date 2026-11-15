"""The 512 held-out states sampled with any policy adapter, outside a loop: step 2's ranking of learning rates
(experiments/rank_learning_rates.py; DESIGN.md, "Follow-up study: controlled arms", "Step 2").

    BACKGROUND_CPUS=52 deployment/background.sh python experiments/held_out_evaluate.py --name v0 --arm v0 --phase 0 \
        --policy-adapter /workspace/checkpoints/data_rewrite_sft_numbered/adapter
    BACKGROUND_CPUS=52 deployment/background.sh python experiments/held_out_evaluate.py --name step2_A_5e-5 \
        --arm step2_A_5e-5 --phase 1 --policy-adapter $LEAN_SEARCH_CHECKPOINTS/step2_A_5e-5/policy/adapter

One request per state, no value model, as a loop's held-out evaluation at its pause: the loop config's (default the
follow-up base) [evaluation] held_out_states target (its one held-out concurrency, 56), held_out_states_file and
sampling search config, on its policy servers, which must be up (deployment/grpo_loop.sh servers). It runs only pinned
through deployment/background.sh (the study's Load rule) and records the CPUs per session in pinning.jsonl. Step 2
compares every variant with this tool's own v0 run on this node, never with the old node's held-out numbers (another
node, quota and pinning).

The run holds the node's serving lock and refuses while a loop runs, merges the adapter on the CPU (probe_evaluate.py's
merges, deleted afterwards unless a server runs from one) and puts it on the policy servers as probe_evaluate.py does
(the loop config's serving.swap, the skip where a server provably holds it, the check requests and the fingerprint),
with its tolerance of server failures (failures.jsonl, sessions.jsonl; a state left without a tree is named in
summary.json's `dropped`, exit status 4 after the restarts are used up). Results in
$LEAN_SEARCH_RUNS/held_out_evaluations/held_out_<name>/: summary.json (once every state is sampled), trees/ (one per
state), pinning.jsonl and checkpoint.json (the adapter, the states file's sha256 and the concurrency); a rerun resumes
the states without a tree, and another adapter, states file or concurrency under the name is refused.
"""

import argparse
import asyncio
import datetime
import functools
import json
import os
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.policy.adapters import merge_adapter
from lean_search.policy.rotation import RequestFailures
from lean_search.policy.serving_lock import ServingBusyError, serving_lock, serving_lock_path
from lean_search.rl.evaluation import FailureTolerance, ServerRecoveryError
from lean_search.rl.fixed_targets import evaluate_held_out_states
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.loop_services import start_servers
from lean_search.rl.node_pinning import append_pinning, current_pinning, pinned_as_background
from lean_search.rl.probe_evaluation import (
    NO_VALUE_VERSION,
    DeathRule,
    ProbeCheckpoint,
    ProbeServers,
    ServersDownError,
    ServersUnsoundError,
    SessionServing,
    adapter_digest,
    checkpoint_merges,
    merges_in_use,
    read_sessions,
    remove_merges,
    remove_stale_merges,
    restart_allowance,
    running_loops,
    serve_checkpoint,
    server_restarts,
    start_session,
    verify_served,
)
from lean_search.rl.rate_ranking import HeldOutRunStart
from lean_search.rl.search_models import served_run_config
from lean_search.rl.search_options import without_search_options
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
OUTPUT = "held_out_evaluations"
SERVERS_DIRECTORY = RUNS_DIRECTORY / "servers"
# As probe_evaluate.py's defaults (ProbeEvaluationConfig).
SERVER_FAILURE_RETRIES = 3
MAX_SERVER_RESTARTS = 3
# The servers kept dying through the run's restarts: a supervisor must not resume it before someone looked.
RECOVERY_EXIT_STATUS = 4


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="the run's directory: held_out_evaluations/held_out_<name>")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--policy-adapter", type=Path, required=True)
    parser.add_argument("--loop-config", type=Path, default=Path("experiments/configs/grpo/followup/base.toml"))
    parser.add_argument(
        "--allow-restarts",
        type=int,
        default=0,
        help="server restarts granted beyond the config's (after exit status 4, once the servers were looked at)",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


async def evaluate(arguments: argparse.Namespace) -> None:
    if not pinned_as_background(current_pinning()):
        raise SystemExit(
            "Run it pinned: BACKGROUND_CPUS=<n> or BACKGROUND_CPU_LIST=<list> deployment/background.sh python ..."
        )
    loop = load_loop_config(REPOSITORY_DIRECTORY / arguments.loop_config)
    if not arguments.policy_adapter.is_dir():
        raise SystemExit(f"No adapter directory at {arguments.policy_adapter}.")
    chosen = ProbeCheckpoint(
        arguments.arm,
        arguments.phase,
        str(arguments.policy_adapter.absolute()),
        adapter_digest(arguments.policy_adapter),
        "",
        "",
        0,
        arguments.phase,
        NO_VALUE_VERSION,
    )
    states_path = RUNS_DIRECTORY / loop.evaluation.held_out_states_file
    target = loop.evaluation.held_out_states
    start = HeldOutRunStart(chosen, loop.evaluation.held_out_states_file, file_sha256(states_path), target.concurrency)
    directory = RUNS_DIRECTORY / OUTPUT / f"held_out_{arguments.name}"
    record = directory / "checkpoint.json"
    if record.exists() and from_json_object(HeldOutRunStart, json.loads(record.read_text(encoding="utf-8"))) != start:
        raise SystemExit(f"{record} holds another checkpoint, states file or concurrency; choose another --name.")
    template = served_run_config(
        without_search_options(load_run_config(REPOSITORY_DIRECTORY / loop.sampling.search_config)), loop.serving
    )
    weights_root = CHECKPOINTS_DIRECTORY / OUTPUT / "weights"
    try:
        with serving_lock(serving_lock_path(CHECKPOINTS_DIRECTORY)):
            if running_loops(RUNS_DIRECTORY).running:
                raise SystemExit("A loop runs on this node; a held-out evaluation runs with none beside.")
            for stale in remove_stale_merges(weights_root, merges_in_use(SERVERS_DIRECTORY, loop.serving)):
                log(f"Removed {stale}, a merge a dead run left")
            try:
                verify = functools.partial(verify_served, template, log)
                served = await serve_checkpoint(
                    loop.serving, chosen, weights_root, merge_adapter, SERVERS_DIRECTORY, verify, log
                )
                log(f"Weights put on {list(served.swapped)} ({served.swap}); already held by {list(served.skipped)}")
                directory.mkdir(parents=True, exist_ok=True)
                record.write_text(to_json(start), encoding="utf-8")
                append_pinning(directory)
                results = directory / "results.jsonl"
                serving = SessionServing(
                    served.swap,
                    served.swapped,
                    served.skipped,
                    restarts_granted=arguments.allow_restarts,
                    fingerprint_warnings=served.fingerprint_warnings,
                )
                start_session(directory, chosen, results, serving)
                request_failures = RequestFailures()
                servers = ProbeServers(
                    loop.serving,
                    served,
                    chosen,
                    directory,
                    results,
                    verify,
                    functools.partial(start_servers, servers_directory=SERVERS_DIRECTORY, log=log),
                    request_failures,
                    DeathRule(),
                )
                sessions = read_sessions(directory)
                tolerance = FailureTolerance(
                    servers,
                    SERVER_FAILURE_RETRIES,
                    restart_allowance(sessions, MAX_SERVER_RESTARTS),
                    directory / "failures.jsonl",
                    len(server_restarts(sessions)),
                    request_failures,
                )
                summary = await evaluate_held_out_states(
                    states_path,
                    template,
                    target,
                    directory,
                    (chosen.policy_version, chosen.value_version),
                    log,
                    tolerance,
                )
            finally:
                merges = checkpoint_merges(loop.serving, chosen, weights_root)
                for kept in remove_merges(merges, merges_in_use(SERVERS_DIRECTORY, loop.serving)):
                    log(f"Kept {kept}: a server runs from it (removed by the next run once none does)")
            if running_loops(RUNS_DIRECTORY).running:
                raise SystemExit(f"A loop came up during the run: delete {directory} and run it again.")
    except ServerRecoveryError as error:
        log(str(error))
        raise SystemExit(RECOVERY_EXIT_STATUS) from error
    except (ServingBusyError, ServersDownError, ServersUnsoundError) as error:
        raise SystemExit(str(error)) from error
    if summary.dropped:
        log(f"Left without a tree after repeated server failures (rerun under the name): {list(summary.dropped)}")
    log(
        f"{directory}: {summary.samples} samples on {summary.problems} states, valid Lean "
        f"{summary.valid_samples / summary.samples:.1%}, success {summary.solved / summary.samples:.1%}"
    )


def main() -> None:
    asyncio.run(evaluate(parse_arguments()))


if __name__ == "__main__":
    main()
