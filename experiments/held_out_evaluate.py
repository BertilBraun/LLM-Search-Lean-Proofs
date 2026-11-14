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
merges, deleted afterwards) and swaps it into the servers. Results in
$LEAN_SEARCH_RUNS/held_out_evaluations/held_out_<name>/: summary.json (once every state is sampled), trees/ (one per
state), pinning.jsonl and checkpoint.json (the adapter, the states file's sha256 and the concurrency); a rerun resumes
the states without a tree, and another adapter, states file or concurrency under the name is refused.
"""

import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.policy.adapters import merge_adapter
from lean_search.policy.serving_lock import ServingBusyError, serving_lock, serving_lock_path
from lean_search.rl.fixed_targets import evaluate_held_out_states
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.node_pinning import append_pinning, current_pinning, pinned_as_background
from lean_search.rl.probe_evaluation import (
    NO_VALUE_VERSION,
    ProbeCheckpoint,
    ServersDownError,
    adapter_digest,
    checkpoint_merges,
    remove_merges,
    remove_stale_merges,
    running_loops,
    serve_checkpoint,
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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="the run's directory: held_out_evaluations/held_out_<name>")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--policy-adapter", type=Path, required=True)
    parser.add_argument("--loop-config", type=Path, default=Path("experiments/configs/grpo/followup/base.toml"))
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


async def evaluate(arguments: argparse.Namespace) -> None:
    if not pinned_as_background(current_pinning()):
        raise SystemExit("Run it pinned: BACKGROUND_CPUS=<n> deployment/background.sh python experiments/...")
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
            remove_stale_merges(weights_root)
            try:
                await serve_checkpoint(loop.serving, chosen, weights_root, merge_adapter)
                directory.mkdir(parents=True, exist_ok=True)
                record.write_text(to_json(start), encoding="utf-8")
                append_pinning(directory)
                summary = await evaluate_held_out_states(
                    states_path, template, target, directory, (chosen.policy_version, chosen.value_version), log
                )
            finally:
                remove_merges(checkpoint_merges(loop.serving, chosen, weights_root))
            if running_loops(RUNS_DIRECTORY).running:
                raise SystemExit(f"A loop came up during the run: delete {directory} and run it again.")
    except (ServingBusyError, ServersDownError) as error:
        raise SystemExit(str(error)) from error
    log(
        f"{directory}: {summary.samples} samples on {summary.problems} states, valid Lean "
        f"{summary.valid_samples / summary.samples:.1%}, success {summary.solved / summary.samples:.1%}"
    )


def main() -> None:
    asyncio.run(evaluate(parse_arguments()))


if __name__ == "__main__":
    main()
