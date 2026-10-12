"""The steps of one expert-iteration round, each a separate command: print them, or run one on the node.

    python experiments/phase6_orchestrate.py --config experiments/configs/expert_iteration/round_0.toml
    deployment/on_node.sh 'python experiments/phase6_orchestrate.py --config ... --run search'

Run steps with --run on the node (the printed commands are for reading; some quote their own patterns); `fetch` runs
locally. Long steps start detached and log to $LEAN_SEARCH_RUNS/<run>/log.txt. Every step can be repeated: the
search resumes where it stopped (also after the round's slices grew), the data build is deterministic, training
restarts from its initial adapter, and finished evaluations are skipped. Order: finalize_pool -> serve_search ->
pause_tracing -> search -> stop_servers -> resume_tracing -> data -> policy_sft and value (one GPU each, in parallel)
-> policy_dpo -> serve_evaluation -> evaluate -> stop_servers -> fetch.
"""

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from lean_search.expert_iteration.config import (
    AdapterReference,
    RoundConfig,
    TracingJob,
    adapter_mismatches,
    load_round_config,
    unserved_adapters,
)
from lean_search.search import RunConfig, load_run_config

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
SERVER_NAME_PREFIX = "search-gpu"
# Anchored, so the pattern matches the pre-filter itself and never a shell or ssh command that names it.
PREFILTER_PATTERN = "^python experiments/phase6_pool.py"
TIMESTAMP = "$(date -u +%FT%TZ)"


class Step(StrEnum):
    FINALIZE_POOL = "finalize_pool"
    SERVE_SEARCH = "serve_search"
    PAUSE_TRACING = "pause_tracing"
    SEARCH = "search"
    STOP_SERVERS = "stop_servers"
    RESUME_TRACING = "resume_tracing"
    DATA = "data"
    POLICY_SFT = "policy_sft"
    VALUE = "value"
    POLICY_DPO = "policy_dpo"
    SERVE_EVALUATION = "serve_evaluation"
    EVALUATE = "evaluate"
    FETCH = "fetch"


@dataclass(frozen=True)
class Command:
    step: Step
    text: str
    note: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run", type=Step, choices=list(Step), help="run this step's command here")
    return parser.parse_args()


def detached(run_name: str, command: str, environment: str = "") -> str:
    log = f"$LEAN_SEARCH_RUNS/{run_name}/log.txt"
    prefix = f"{environment} " if environment else ""
    return f"mkdir -p $LEAN_SEARCH_RUNS/{run_name} && {prefix}setsid nohup {command} >> {log} 2>&1 < /dev/null &"


def serve_commands(config: RoundConfig, run_config: RunConfig, adapters: Sequence[AdapterReference]) -> list[str]:
    modules = " ".join(f"{adapter.name}={adapter.path}" for adapter in adapters)
    return [
        f"deployment/serve_model.sh {SERVER_NAME_PREFIX}{gpu} {config.base_model} {gpu} {urlparse(url).port} "
        f"--served-model-name {run_config.policy.model} --lora-modules {modules}"
        for gpu, url in enumerate(run_config.policy.server_urls)
    ]


def stop_command(run_config: RunConfig) -> str:
    names = " ".join(f"{SERVER_NAME_PREFIX}{gpu}" for gpu in range(len(run_config.policy.server_urls)))
    return f"deployment/stop_model.sh {names}"


def pause_tracing_command(job: TracingJob, log: str) -> str:
    """SIGTERM to the job's own process only (its REPLs die with it), waiting until it is gone; logged."""
    pattern = shlex.quote(job.process_pattern)
    return (
        f'mkdir -p "$(dirname {log})"; pids=$(pgrep -f {pattern}); '
        f'if [ -z "$pids" ]; then echo "{TIMESTAMP} no tracing process matches {job.process_pattern}" >> {log}; '
        "else for pid in $pids; do "
        f'echo "{TIMESTAMP} SIGTERM to tracing pid $pid: $(tr "\\0" " " < /proc/$pid/cmdline)" >> {log}; '
        "kill -TERM $pid; done; for pid in $pids; do while kill -0 $pid 2>/dev/null; do sleep 2; done; "
        f'echo "{TIMESTAMP} tracing pid $pid exited" >> {log}; done; fi; tail -n 4 {log}'
    )


def resume_tracing_command(job: TracingJob, log: str) -> str:
    pattern = shlex.quote(job.process_pattern)
    command = job.restart_command.strip().removesuffix("&").rstrip()
    return (
        f'mkdir -p "$(dirname {log})"; if [ -n "$(pgrep -f {pattern})" ]; then '
        f'echo "{TIMESTAMP} tracing is already running, not restarted" >> {log}; '
        f'else {command} & echo "{TIMESTAMP} tracing restarted as pid $!" >> {log}; fi; tail -n 2 {log}'
    )


def evaluation_command(config: RoundConfig) -> str:
    """The evaluations one after another (each holds both GPUs' servers and 40 REPLs), finished ones skipped."""
    steps = []
    for evaluation in config.evaluations:
        run = config.stage_run_name(f"evaluation_{evaluation.name}")
        steps.append(
            f'[ -f "$LEAN_SEARCH_RUNS/{run}/summary/summary.json" ] || python experiments/run_search.py '
            f"--config {evaluation.config} --split valid --run-name {run}"
        )
    return detached(config.stage_run_name("evaluation"), f"bash -c {shlex.quote('; '.join(steps))}")


def configuration_problems(config: RoundConfig) -> list[str]:
    search_config = load_run_config(REPOSITORY_DIRECTORY / config.search_config)
    problems = adapter_mismatches(search_config, config.policy, config.value)
    served = (config.policy, config.value, config.next_policy, config.next_value)
    for evaluation in config.evaluations:
        evaluation_config = load_run_config(REPOSITORY_DIRECTORY / evaluation.config)
        problems += [f"{evaluation.name}: {problem}" for problem in unserved_adapters(evaluation_config, served)]
    last_policy_stage = "policy_dpo" if config.policy_dpo_config else "policy_sft"
    if not config.next_policy.path.endswith(f"{config.stage_run_name(last_policy_stage)}/adapter"):
        problems.append(f"next_policy.path should be the {last_policy_stage} adapter: {config.next_policy.path}")
    if not config.next_value.path.endswith(f"{config.stage_run_name('value')}/adapter"):
        problems.append(f"next_value.path should be the value run's adapter: {config.next_value.path}")
    return problems


def round_commands(config: RoundConfig, config_path: Path) -> list[Command]:
    if problems := configuration_problems(config):
        raise ValueError("Inconsistent round configuration: " + "; ".join(problems))
    search_config = load_run_config(REPOSITORY_DIRECTORY / config.search_config)
    first_evaluation = load_run_config(REPOSITORY_DIRECTORY / config.evaluations[0].config)
    round_config = shlex.quote(config_path.as_posix())
    sft_run = config.stage_run_name("policy_sft")
    dpo_run = config.stage_run_name("policy_dpo")
    value_run = config.stage_run_name("value")
    tracing_log = f"$LEAN_SEARCH_RUNS/{config.run_name}/tracing.log"
    evaluation_runs = [config.stage_run_name(f"evaluation_{evaluation.name}") for evaluation in config.evaluations]
    commands = [
        Command(
            Step.FINALIZE_POOL,
            f"pkill -TERM -f {shlex.quote(PREFILTER_PATTERN)}; sleep 30; python experiments/phase6_pool.py "
            f"--config {config.pool_config} --name {Path(config.pool).name} --step finalize",
            "stops the CPU pre-filter (it resumes later with --step prefilter) and writes prepared.jsonl from the "
            "statements done so far; the round fails early if a source has too few",
        ),
        *(
            Command(Step.SERVE_SEARCH, command, f"GPU server with {config.policy.name} and {config.value.name}")
            for command in serve_commands(config, search_config, (config.policy, config.value))
        ),
    ]
    if config.tracing is not None:
        commands.append(
            Command(
                Step.PAUSE_TRACING,
                pause_tracing_command(config.tracing, tracing_log),
                "stops the deferred tracing job right before the search (it resumes by shard), logged",
            )
        )
    commands += [
        Command(
            Step.SEARCH,
            detached(config.run_name, f"python experiments/phase6_round.py --config {round_config}"),
            f"{config.statement_count:,} statements; resumable, also after the slices grow (measurement first, "
            "then the full round)",
        ),
        Command(Step.STOP_SERVERS, stop_command(search_config), "frees both GPUs for training"),
    ]
    if config.tracing is not None:
        commands.append(
            Command(
                Step.RESUME_TRACING,
                resume_tracing_command(config.tracing, tracing_log),
                "restarts the tracing job after the search phase unless it runs already, logged",
            )
        )
    commands += [
        Command(
            Step.DATA,
            detached(config.stage_run_name("data"), f"python experiments/phase6_data.py --config {round_config}"),
            f"CPU only: policy_sft, dpo and value data in $LEAN_SEARCH_DATA/expert_iteration/{config.data_name}/",
        ),
        Command(
            Step.POLICY_SFT,
            detached(
                sft_run,
                f"python experiments/phase2_sft.py --config {config.policy_sft_config} --run-name {sft_run} --no-merge",
                "CUDA_VISIBLE_DEVICES=0",
            ),
            f"GPU 0: continues {config.policy.name} on the round's proofs plus replay",
        ),
        Command(
            Step.VALUE,
            detached(
                value_run,
                f"python experiments/phase3_value.py --config {config.value_config} --run-name {value_run}",
                "CUDA_VISIBLE_DEVICES=1",
            ),
            "GPU 1, in parallel with policy_sft: value v1 on the round's tree labels plus v0 replay",
        ),
    ]
    if config.policy_dpo_config:
        commands.append(
            Command(
                Step.POLICY_DPO,
                detached(
                    dpo_run,
                    f"python experiments/phase6_dpo.py --config {config.policy_dpo_config} --run-name {dpo_run}",
                    "CUDA_VISIBLE_DEVICES=0",
                ),
                "GPU 0, after policy_sft: DPO with the SFT adapter as the frozen reference",
            )
        )
    adapters = (config.policy, config.value, config.next_policy, config.next_value)
    commands += [
        *(
            Command(Step.SERVE_EVALUATION, command, "GPU server with the old and the new policy and value adapters")
            for command in serve_commands(config, first_evaluation, adapters)
        ),
        Command(
            Step.EVALUATE,
            evaluation_command(config),
            f"miniF2F-valid at row 4's budget, one after another: {', '.join(evaluation_runs)}; a run that broke off "
            "must be removed before a rerun; afterwards stop_servers again",
        ),
        Command(
            Step.FETCH,
            " && ".join(
                f"deployment/fetch_results.sh {run}"
                for run in (
                    config.run_name,
                    config.stage_run_name("data"),
                    sft_run,
                    *([dpo_run] if config.policy_dpo_config else []),
                    value_run,
                    *evaluation_runs,
                )
            ),
            "locally: copies every summary to results/",
        ),
    ]
    return commands


def main() -> None:
    arguments = parse_arguments()
    config = load_round_config(arguments.config)
    commands = round_commands(config, arguments.config)
    if arguments.run is None:
        print(f"# Expert-iteration round {config.index}: {config.run_name}")
        for command in commands:
            print(f"\n# {command.step}: {command.note}\n{command.text}")
        return
    for command in (command for command in commands if command.step == arguments.run):
        print(command.text, flush=True)
        completed = subprocess.run(["bash", "-c", command.text], cwd=REPOSITORY_DIRECTORY, check=False)
        if completed.returncode:
            sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
