"""One search-tree GRPO training phase on one GPU: GRPO of the policy and/or the value model on labelled trees.

    python experiments/grpo_phase.py --config experiments/configs/grpo/phase.toml --trees runs/<run>/trees \
        --texts runs/<run>/expansion_texts.jsonl --run-name grpo_phase_0001 [--part policy|value]

Writes the adapters to $LEAN_SEARCH_CHECKPOINTS/<run-name>/{policy,value}/adapter, the step records next to them and
the phase's outcome (data metrics, training results, the value gate) to phase.json there. The replay files and the
value benchmark are optional.
"""

import argparse
import dataclasses
import os
import tomllib
from pathlib import Path

import torch
import transformers

from lean_search.reasoning.dataset import read_examples as read_reasoning_examples
from lean_search.rl.policy_data import read_expansion_texts
from lean_search.rl.training_phase import PhaseInputs, TrainingPhaseConfig, run_training_phase
from lean_search.search import read_tree
from lean_search.search.records import from_json_object
from lean_search.training.math_data import read_solutions
from lean_search.value.benchmark import read_benchmark
from lean_search.value.labels import read_examples as read_value_examples

CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--trees", nargs="+", type=Path, required=True)
    parser.add_argument("--texts", nargs="*", type=Path, default=[])
    parser.add_argument("--lean-replay", type=Path, help="reasoning data set JSON lines (Lean SFT replay)")
    parser.add_argument("--math-replay", type=Path, help="math solutions JSON lines")
    parser.add_argument("--value-replay", type=Path, help="v0 value examples JSON lines")
    parser.add_argument("--value-benchmark", type=Path, help="a value benchmark; without it no value model is accepted")
    parser.add_argument("--part", choices=("policy", "value"), help="train only this model")
    parser.add_argument("--run-name", required=True)
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


def main() -> None:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    config = load_config(arguments)
    inputs = PhaseInputs(
        records=[read_tree(path) for directory in arguments.trees for path in sorted(directory.glob("*.json.gz"))],
        texts=[expansion for path in arguments.texts for expansion in read_expansion_texts(path)],
        lean_replay=list(read_reasoning_examples(arguments.lean_replay)) if arguments.lean_replay else [],
        math_replay=list(read_solutions(arguments.math_replay)) if arguments.math_replay else [],
        value_replay=list(read_value_examples(arguments.value_replay)) if arguments.value_replay else [],
        value_benchmark=read_benchmark(arguments.value_benchmark) if arguments.value_benchmark else None,
    )
    policy_tokenizer = transformers.AutoTokenizer.from_pretrained(config.policy.model) if config.policy else None
    value_tokenizer = transformers.AutoTokenizer.from_pretrained(config.value.model) if config.value else None
    output_directory = CHECKPOINTS_DIRECTORY / arguments.run_name
    output_directory.mkdir(parents=True, exist_ok=True)
    outcome = run_training_phase(
        config, inputs, policy_tokenizer, value_tokenizer, torch.device("cuda"), output_directory
    )
    print(f"{outcome.trees} trees, {outcome.groups} groups", flush=True)
    if outcome.policy is not None:
        print(f"policy: {outcome.policy.data}\n{outcome.policy.result}", flush=True)
    if outcome.value is not None:
        accepted = "accepted" if outcome.value.accepted else "not accepted"
        print(f"value ({accepted}): {outcome.value.result}", flush=True)
        if outcome.value.gate is not None:
            print(f"gate: {outcome.value.gate.reasons or 'passed'}", flush=True)
            for warning in outcome.value.gate.warnings:
                print(f"gate warning: {warning}", flush=True)


if __name__ == "__main__":
    main()
