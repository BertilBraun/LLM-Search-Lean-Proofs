"""The whole probe set searched with any checkpoint, outside a loop (src/lean_search/rl/probe_evaluation.py).

    python experiments/probe_evaluate.py --config experiments/configs/grpo/followup/probe_evaluation.toml \
        --name arm_a_phase_08 --policy-adapter /workspace/checkpoints/<loop>_phase_0008/policy/adapter \
        --policy-version 8 --value v0 [--search-config experiments/configs/grpo/search/<other>.toml]
    --value none             no value model: best-first on the policy's log-probabilities (priority kind
                             cumulative_log_probability, the search config's other priority settings kept)
    --value v0               the loop config's [initial] value_adapter (value version 0)
    --value PATH             a value adapter (give --value-version, the rating's label)

Servers: the loop config's policy servers (and, with a value model, its value servers) must be up, as
deployment/grpo_loop.sh servers starts them (any version). With no loop running on them, the command merges the
adapters on the CPU (once per adapter path, under $LEAN_SEARCH_CHECKPOINTS/<output>/weights/) and swaps the merged
weights into those servers in place, as the loop does at a publish; `--value none` leaves the value servers as they
are. A loop started later serves its own current version again when it starts.

The run goes to $LEAN_SEARCH_RUNS/<output>/probe_<name>/: results.jsonl (one per statement), summary.json, trees,
config.toml as a loop's probe run (probe_rating.finished_probe_runs(<output>) rates them all), and run.json with the
checkpoint and the share of searches stopped on the wall clock; above the config's max_wall_clock_stop_share the run
counts as rejected (run.json accepted = false, exit status 1). Rerunning the same command resumes; another checkpoint
or search config under the same name is refused (checkpoint.json, written at the start).
"""

import argparse
import asyncio
import datetime
import json
import os
import tomllib
from pathlib import Path

from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.policy.adapters import merge_adapter
from lean_search.policy.server_control import is_healthy
from lean_search.rl.evaluation import EvaluationKind, EvaluationPaths, run_problem_set_evaluation
from lean_search.rl.fixed_targets import probe_problems
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.loop_services import VllmServers
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunStart,
    default_value_version,
    merged_weights_directory,
    probe_run_config,
    resolve_value_adapter,
    run_directory,
    run_record,
)
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True, help="the run's directory: <output>/probe_<name>")
    parser.add_argument("--policy-adapter", type=Path, required=True)
    parser.add_argument("--policy-version", type=int, required=True, help="the rating's label of the policy")
    parser.add_argument("--value", required=True, help='"none", "v0" or a value adapter\'s path')
    parser.add_argument("--value-version", type=int, help="the rating's label of a value adapter given by path")
    parser.add_argument("--search-config", type=Path, help="in place of the config's search_config")
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
    by_path = default_value_version(arguments.value) is None
    adapters = [arguments.policy_adapter, *([Path(arguments.value)] if by_path else [])]
    missing = [str(adapter) for adapter in adapters if not adapter.is_dir()]
    if missing:
        raise SystemExit(f"No adapter directory at {missing}.")
    return ProbeCheckpoint(
        policy_adapter=str(arguments.policy_adapter.absolute()),
        value_adapter=resolve_value_adapter(arguments.value, loop.initial.value_adapter),
        policy_version=arguments.policy_version,
        value_version=value_version,
    )


async def serve(loop: GrpoLoopConfig, config: ProbeEvaluationConfig, chosen: ProbeCheckpoint) -> None:
    """Merges the adapters (or reuses their merges) and swaps them into the running servers."""
    serving = loop.serving
    weights_root = CHECKPOINTS_DIRECTORY / config.output / "weights"
    publisher = MergedPublisher(
        serving, weights_root, lambda base, adapter, output: merge_adapter(base, Path(adapter), output)
    )
    servers = VllmServers(serving, (), publisher)
    needed = [*serving.policy_servers, *(serving.value_servers if chosen.value_adapter else ())]
    healthy = await asyncio.gather(*(is_healthy(server.url) for server in needed))
    down = [server.name for server, up in zip(needed, healthy, strict=True) if not up]
    if down:
        raise SystemExit(f"Servers not answering: {down}; start them (deployment/grpo_loop.sh servers).")
    log(f"Merging {chosen.policy_adapter} (and the value adapter) unless merged before")
    policy = await asyncio.to_thread(
        publisher.merged_weights,
        serving.policy_base_model,
        chosen.policy_adapter,
        merged_weights_directory(weights_root, chosen.policy_adapter, "policy"),
    )
    await asyncio.gather(*(servers.serve_weights(server, str(policy)) for server in serving.policy_servers))
    if chosen.value_adapter:
        value = await asyncio.to_thread(
            publisher.merged_weights,
            serving.value_base_model,
            chosen.value_adapter,
            merged_weights_directory(weights_root, chosen.value_adapter, "value"),
        )
        await servers.serve_value(str(value))
    log("The servers serve the checkpoint")


def refuse_another_start(path: Path, start: ProbeRunStart) -> None:
    """A resumed run must search with the checkpoint and search config it began with."""
    if path.exists() and from_json_object(ProbeRunStart, json.loads(path.read_text(encoding="utf-8"))) != start:
        raise SystemExit(f"{path} holds another checkpoint or search config; choose another --name.")


async def evaluate(arguments: argparse.Namespace) -> None:
    config = load_config(arguments.config)
    loop = load_loop_config(REPOSITORY_DIRECTORY / config.loop_config)
    chosen = checkpoint(arguments, loop)
    search_config = str(arguments.search_config or config.search_config)
    directory = run_directory(RUNS_DIRECTORY / config.output, arguments.name)
    paths = EvaluationPaths(directory)
    start = ProbeRunStart(chosen, search_config)
    refuse_another_start(directory / "checkpoint.json", start)
    template = load_run_config(REPOSITORY_DIRECTORY / search_config)
    run_config = probe_run_config(template, loop.serving, config.probe, chosen.value_adapter)
    await serve(loop, config, chosen)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
    problems = probe_problems(DATA_DIRECTORY / config.probe_set)
    log(f"{len(problems)} problems of {config.probe_set} into {directory}")
    versions = (chosen.policy_version, chosen.value_version)
    summary = await run_problem_set_evaluation(
        EvaluationKind.PROBE, directory.name, versions, problems, run_config, paths, log
    )
    record = run_record(chosen, search_config, summary, config.max_wall_clock_stop_share)
    (directory / "run.json").write_text(to_json(record), encoding="utf-8")
    log(
        f"{summary.solved}/{summary.problems} solved; {summary.wall_clock_stops} searches stopped on the wall clock "
        f"({record.wall_clock_stop_share:.1%}, at most {config.max_wall_clock_stop_share:.1%}): "
        f"{'accepted' if record.accepted else 'rejected'}"
    )
    if not record.accepted:
        raise SystemExit(1)


def main() -> None:
    asyncio.run(evaluate(parse_arguments()))


if __name__ == "__main__":
    main()
