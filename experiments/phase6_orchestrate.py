"""The steps of one expert-iteration round, each a separate command: print them, or run one on the node.

    python experiments/phase6_orchestrate.py --config experiments/configs/expert_iteration/round_0.toml
    python experiments/phase6_orchestrate.py --config ... --run search

Printed commands run inside the node's checkout (deployment/on_node.sh '<command>'); `fetch` runs locally. Long steps
start detached and log to $LEAN_SEARCH_RUNS/<run>/log.txt. Every step can be repeated: the search resumes where it
stopped, the data build is deterministic, and training restarts from its initial adapter. Order: serve_search ->
search -> stop_servers -> data -> policy_sft and value (one GPU each, in parallel) -> policy_dpo -> serve_evaluation
-> evaluate -> stop_servers -> fetch.
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
    adapter_mismatches,
    load_round_config,
)
from lean_search.search import RunConfig, load_run_config

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
SERVER_NAME_PREFIX = "search-gpu"


class Step(StrEnum):
    SERVE_SEARCH = "serve_search"
    SEARCH = "search"
    STOP_SERVERS = "stop_servers"
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


def round_commands(config: RoundConfig, config_path: Path) -> list[Command]:
    search_config = load_run_config(REPOSITORY_DIRECTORY / config.search_config)
    evaluation_config = load_run_config(REPOSITORY_DIRECTORY / config.evaluation_config)
    problems = adapter_mismatches(search_config, config.policy, config.value) + adapter_mismatches(
        evaluation_config, config.next_policy, config.next_value
    )
    last_policy_stage = "policy_dpo" if config.policy_dpo_config else "policy_sft"
    if not config.next_policy.path.endswith(f"{config.stage_run_name(last_policy_stage)}/adapter"):
        problems.append(f"next_policy.path should be the {last_policy_stage} adapter: {config.next_policy.path}")
    if not config.next_value.path.endswith(f"{config.stage_run_name('value')}/adapter"):
        problems.append(f"next_value.path should be the value run's adapter: {config.next_value.path}")
    if problems:
        raise ValueError("Inconsistent round configuration: " + "; ".join(problems))
    round_config = shlex.quote(config_path.as_posix())
    sft_run = config.stage_run_name("policy_sft")
    dpo_run = config.stage_run_name("policy_dpo")
    value_run = config.stage_run_name("value")
    evaluation_run = config.stage_run_name("evaluation")
    commands = [
        *(
            Command(Step.SERVE_SEARCH, command, f"GPU server with {config.policy.name} and {config.value.name}")
            for command in serve_commands(config, search_config, (config.policy, config.value))
        ),
        Command(
            Step.SEARCH,
            detached(config.run_name, f"python experiments/phase6_round.py --config {round_config}"),
            f"{config.statement_count:,} statements; resumable. The tracing job pauses only for run_search.py, "
            "so pause it (or accept slower Lean) while this runs.",
        ),
        Command(Step.STOP_SERVERS, stop_command(search_config), "frees both GPUs for training"),
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
    commands += [
        *(
            Command(
                Step.SERVE_EVALUATION,
                command,
                f"GPU server with {config.next_policy.name} and {config.next_value.name}",
            )
            for command in serve_commands(config, evaluation_config, (config.next_policy, config.next_value))
        ),
        Command(
            Step.EVALUATE,
            detached(
                evaluation_run,
                f"python experiments/run_search.py --config {config.evaluation_config} --split valid "
                f"--run-name {evaluation_run}",
            ),
            "miniF2F-valid with row 4's settings; afterwards stop_servers again",
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
                    evaluation_run,
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
    selected = [command for command in commands if command.step == arguments.run]
    for command in selected:
        print(command.text, flush=True)
        completed = subprocess.run(["bash", "-c", command.text], cwd=REPOSITORY_DIRECTORY, check=False)
        if completed.returncode:
            sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
