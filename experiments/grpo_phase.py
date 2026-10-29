"""One search-tree GRPO training phase: GRPO of the policy and/or the value model on labelled trees, on one GPU or
data-parallel on several under torchrun (each optimizer step equals the one-GPU step on the same batch).

    [torchrun --standalone --nproc-per-node 4] experiments/grpo_phase.py --config experiments/configs/grpo/phase.toml \
        --trees runs/<run>/trees --run-name grpo_phase_0001 [--part policy|value] [--value-trees <directories>] \
        [--merge-adapters] [--metrics-run runs/<loop> --phase 12 --sampling-seconds 1500]

Writes the adapters to $LEAN_SEARCH_CHECKPOINTS/<run-name>/{policy,value}/adapter, the step records next to them and
the phase's outcome (data metrics, training results, the value gate, the job's timings) to phase.json there. With
--merge-adapters the new policy adapter and an accepted value adapter are also merged into their bases on the GPUs
(<adapter>/../merged), which the GRPO loop's publisher takes over. The policy texts come from the tree records
(`TreeRecord.expansions`). The value model trains on --value-trees (the loop's window of recent phases, --trees among
them; default --trees), which only the main rank reads (without the other phases' texts) and turns into the value data
it sends to the other ranks. The replay files and the value benchmark are optional. With --metrics-run the policy
outcome is appended to that run's dashboard metrics (the grpo family).
"""

import argparse
import dataclasses
import os
import tomllib
from pathlib import Path

import torch
import transformers

from lean_search.monitoring.store import LoopContext, MetricsWriter
from lean_search.reasoning.dataset import read_examples as read_reasoning_examples
from lean_search.rl.training_phase import PhaseInputs, TrainingPhaseConfig, grpo_phase_record, run_training_phase
from lean_search.search import TreeRecord, read_tree
from lean_search.search.records import from_json_object
from lean_search.training.data_parallel import start_process_group, stop_process_group
from lean_search.training.math_data import read_solutions
from lean_search.value.benchmark import read_benchmark
from lean_search.value.labels import read_examples as read_value_examples

CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--trees", nargs="+", type=Path, required=True)
    parser.add_argument("--value-trees", nargs="+", type=Path, default=[], help="the value model's tree directories")
    parser.add_argument("--lean-replay", type=Path, help="reasoning data set JSON lines (Lean SFT replay)")
    parser.add_argument("--math-replay", type=Path, help="math solutions JSON lines")
    parser.add_argument("--value-replay", type=Path, help="v0 value examples JSON lines")
    parser.add_argument("--value-benchmark", type=Path, help="a value benchmark; without it no value model is accepted")
    parser.add_argument("--part", choices=("policy", "value"), help="train only this model")
    parser.add_argument("--merge-adapters", action="store_true", help="merge the new adapters on the GPUs")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--metrics-run", type=Path, help="a loop run directory whose dashboard metrics get the phase")
    parser.add_argument("--sampling-seconds", type=float, help="the search time behind the phase's trees")
    parser.add_argument("--phase", type=int, help="the loop phase the metrics line belongs to")
    return parser.parse_args()


def load_config(arguments: argparse.Namespace) -> TrainingPhaseConfig:
    config = from_json_object(TrainingPhaseConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    match arguments.part:
        case "policy":
            return dataclasses.replace(config, value=None)
        case "value":
            return dataclasses.replace(config, policy=None)
        case _:
            return config


def value_records(arguments: argparse.Namespace, phase_records: list[TreeRecord]) -> list[TreeRecord]:
    """The window's trees; those of other phases without their texts, which only the policy needs."""
    records = list(phase_records) if set(arguments.trees) & set(arguments.value_trees) else []
    for directory in arguments.value_trees:
        if directory not in arguments.trees:
            records += [read_tree(path, texts=False) for path in sorted(directory.glob("*.json.gz"))]
    return records


def main() -> None:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    device = torch.device("cuda", int(os.environ.get("LOCAL_RANK", "0")))
    torch.cuda.set_device(device)
    ranks = start_process_group("nccl")
    config = load_config(arguments)
    records = [read_tree(path) for directory in arguments.trees for path in sorted(directory.glob("*.json.gz"))]
    inputs = PhaseInputs(
        records=records,
        lean_replay=list(read_reasoning_examples(arguments.lean_replay)) if arguments.lean_replay else [],
        math_replay=list(read_solutions(arguments.math_replay)) if arguments.math_replay else [],
        value_replay=list(read_value_examples(arguments.value_replay)) if arguments.value_replay else [],
        value_benchmark=read_benchmark(arguments.value_benchmark) if arguments.value_benchmark else None,
        value_records=value_records(arguments, records)
        if config.value and arguments.value_trees and ranks.is_main
        else [],
    )
    policy_tokenizer = transformers.AutoTokenizer.from_pretrained(config.policy.model) if config.policy else None
    value_tokenizer = transformers.AutoTokenizer.from_pretrained(config.value.model) if config.value else None
    output_directory = CHECKPOINTS_DIRECTORY / arguments.run_name
    output_directory.mkdir(parents=True, exist_ok=True)
    outcome = run_training_phase(
        config, inputs, policy_tokenizer, value_tokenizer, device, output_directory, ranks, arguments.merge_adapters
    )
    stop_process_group(ranks)
    if not ranks.is_main:
        return
    print(f"{outcome.trees} trees, {outcome.groups} groups", flush=True)
    if outcome.policy is not None:
        print(f"policy: {outcome.policy.data}\n{outcome.policy.result}", flush=True)
        if arguments.metrics_run is not None:
            writer = MetricsWriter(arguments.metrics_run, LoopContext(phase=arguments.phase))
            writer.write(grpo_phase_record(outcome.policy, arguments.sampling_seconds))
    if outcome.value is not None:
        accepted = "accepted" if outcome.value.accepted else "not accepted"
        print(f"value ({accepted}): {outcome.value.result}", flush=True)
        if outcome.value.gate is not None:
            print(f"gate: {outcome.value.gate.reasons or 'passed'}", flush=True)
            for warning in outcome.value.gate.warnings:
                print(f"gate warning: {warning}", flush=True)


if __name__ == "__main__":
    main()
