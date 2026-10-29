"""Cheap test (DESIGN.md "Order of work", step 3): single-step GRPO on held-out states, per-tactic vs sequence credit.

    python experiments/grpo_single_step.py --config experiments/configs/grpo/single_step.toml run --arm per_tactic
    python experiments/grpo_single_step.py --config ... run --arm sequence
    python experiments/grpo_single_step.py --config ... report

Each arm starts from the starting policy (`policy_adapter` on `policy_base_model`) and runs `rounds` rounds: serve
the arm's current weights on the policy servers (its adapter merged on the CPU, swapped in place), sample n blocks on
every training state and every disjoint state (one request each, executed in Lean from the rebuilt state;
src/lean_search/rl/single_step.py), record the per-sample success on both sets, then train one GRPO phase (two passes)
on the training states' root groups, with the arm's phase config (per-tactic or sequence credit), continuing the arm's
last adapter. A last measurement follows the last round. Round 0's samples are the starting policy's and shared by the
arms. Run it on the training GPU (CUDA_VISIBLE_DEVICES), with policy servers on the others serving as `policy.model`;
or, with `release_servers_while_training`, one arm per GPU next to its own sleep-mode server, all arms side by side.
Outputs in $LEAN_SEARCH_RUNS/<name>/: start/ (round 0 trees and merged weights), <arm>/round_<r>/{train,disjoint}/trees,
<arm>/round_<r>/ adapter and merged weights, <arm>/curve.jsonl (one line per round: steps so far, success on both
sets) and report.md.
Resumable: trees and adapters already written are kept.
"""

import argparse
import asyncio
import dataclasses
import datetime
import gc
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import torch
import transformers

from lean_search.policy.adapters import merge_adapter
from lean_search.policy.server_control import is_sleeping, publish_weights, release_gpu, restore_gpu
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.single_step import (
    SampleSuccess,
    SingleStepArm,
    SingleStepConfig,
    StateProblem,
    sample_success,
    search_states,
    single_step_phase_data,
    single_step_run_config,
    state_problem,
    total_success,
)
from lean_search.rl.training_phase import PhaseInputs, TrainingPhaseConfig, append_json_line, train_policy_phase
from lean_search.search import RunConfig, TreeRecord, load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])


@dataclass(frozen=True)
class CurvePoint:
    round: int
    # Optimizer steps the arm took before this round's samples.
    steps: int
    train: SampleSuccess
    disjoint: SampleSuccess


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--arm", required=True)
    commands.add_parser("report")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def load_states(relative: str) -> list[StateProblem]:
    return [state_problem(state) for state in read_records(RUNS_DIRECTORY / relative, ReasoningState)]


def success(records: list[TreeRecord], states: list[StateProblem]) -> SampleSuccess:
    return total_success(
        [sample_success(record, state.reference_keys) for record, state in zip(records, states, strict=True)]
    )


async def serve(weights: Path, config: RunConfig) -> None:
    for server_url in config.policy.server_urls:
        if await is_sleeping(server_url):
            await restore_gpu(server_url, weights)
        else:
            await publish_weights(server_url, weights)
    log(f"Serving {weights}")


async def release_servers(config: RunConfig) -> None:
    for server_url in config.policy.server_urls:
        await release_gpu(server_url)
    log("Servers released for training")


def round_directory(directory: Path, arm: SingleStepArm, round_index: int) -> Path:
    return directory / arm.name / f"round_{round_index}"


def sample_directory(directory: Path, arm: SingleStepArm, round_index: int) -> Path:
    return directory / "start" if round_index == 0 else round_directory(directory, arm, round_index)


def train_round(
    config: SingleStepConfig,
    arm: SingleStepArm,
    records: list[TreeRecord],
    states: list[StateProblem],
    initial_adapter: str,
    output: Path,
) -> int:
    """Trains the round's root groups; returns the optimizer steps."""
    phase_text = (REPOSITORY_DIRECTORY / arm.phase_config).read_text(encoding="utf-8")
    phase = from_json_object(TrainingPhaseConfig, tomllib.loads(phase_text))
    assert phase.policy is not None, arm.phase_config
    optimization = phase.policy.optimization
    if arm.learning_rate is not None:
        optimization = dataclasses.replace(optimization, learning_rate=arm.learning_rate)
    grpo = dataclasses.replace(
        phase.policy,
        model=config.policy_base_model,
        initial_adapter=initial_adapter,
        reference_adapter=config.policy_adapter,
        optimization=optimization,
    )
    labelled = single_step_phase_data(records, states, phase.reward)
    inputs = PhaseInputs(records=records)
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.policy_base_model)
    log(f"{arm.name}: training on {len(labelled.groups)} groups from {initial_adapter or 'a fresh adapter'}")
    outcome = train_policy_phase(
        dataclasses.replace(phase, policy=grpo),
        grpo,
        labelled,
        inputs,
        tokenizer,
        torch.device("cuda"),
        output,
        lambda record: append_json_line(output / "steps.jsonl", record),
    )
    (output / "outcome.json").write_text(to_json(outcome), encoding="utf-8")
    torch.cuda.empty_cache()
    return outcome.result.steps


def trained_steps(output: Path) -> int:
    with (output / "steps.jsonl").open(encoding="utf-8") as lines:
        return sum(1 for line in lines if line.strip())


async def run_arm(config: SingleStepConfig, arm: SingleStepArm) -> None:
    directory = RUNS_DIRECTORY / config.name
    template = load_run_config(REPOSITORY_DIRECTORY / config.search_config)
    search = single_step_run_config(template)
    if config.policy_server_urls:
        search = dataclasses.replace(
            search, policy=dataclasses.replace(search.policy, server_urls=config.policy_server_urls)
        )
    search = dataclasses.replace(
        search, lean=dataclasses.replace(search.lean, pool_size=config.concurrency, concurrency=config.concurrency)
    )
    train_states = load_states(config.train_states)
    disjoint_states = load_states(config.disjoint_states)
    curve_path = directory / arm.name / "curve.jsonl"
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    curve_path.write_text("", encoding="utf-8")
    adapter = config.policy_adapter
    steps = 0
    for round_index in range(config.rounds + 1):
        samples = sample_directory(directory, arm, round_index)
        weights = Path(config.policy_base_model)
        if adapter:
            weights = samples / "merged"
            if not weights.exists():
                merge_adapter(config.policy_base_model, Path(adapter), weights)
        await serve(weights, search)
        train_records = await search_states(train_states, search, samples / "train" / "trees", log)
        disjoint_records = await search_states(disjoint_states, search, samples / "disjoint" / "trees", log)
        point = CurvePoint(
            round_index, steps, success(train_records, train_states), success(disjoint_records, disjoint_states)
        )
        with curve_path.open("a", encoding="utf-8") as handle:
            handle.write(to_json(point) + "\n")
        log(
            f"{arm.name} round {round_index} after {steps} steps: train {point.train.rate:.3f}, "
            f"disjoint {point.disjoint.rate:.3f}"
        )
        if round_index == config.rounds:
            break
        output = round_directory(directory, arm, round_index + 1) / "training"
        if (output / "adapter" / "adapter_config.json").exists():
            steps += trained_steps(output)
        else:
            if config.release_servers_while_training:
                await release_servers(search)
            steps += train_round(config, arm, train_records, train_states, adapter, output)
            # The woken server needs the memory the trainer's caching allocator still holds.
            gc.collect()
            torch.cuda.empty_cache()
        adapter = str(output / "adapter")


def report(config: SingleStepConfig) -> None:
    directory = RUNS_DIRECTORY / config.name
    lines = ["| arm | round | steps | train states | disjoint states |", "|---|---|---|---|---|"]
    for arm in config.arms:
        path = directory / arm.name / "curve.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            point = from_json_object(CurvePoint, json.loads(line))
            lines.append(
                f"| {arm.name} | {point.round} | {point.steps} | {point.train.rate:.3f} ({point.train.samples}) "
                f"| {point.disjoint.rate:.3f} ({point.disjoint.samples}) |"
            )
    text = "# Single-step GRPO: per-sample success\n\n" + "\n".join(lines) + "\n"
    (directory / "report.md").write_text(text, encoding="utf-8")
    print(text)


def load_config(path: Path) -> SingleStepConfig:
    return from_json_object(SingleStepConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def main() -> None:
    arguments = parse_arguments()
    config = load_config(arguments.config)
    match arguments.command:
        case "run":
            (arm,) = (arm for arm in config.arms if arm.name == arguments.arm)
            asyncio.run(run_arm(config, arm))
        case "report":
            report(config)


if __name__ == "__main__":
    main()
