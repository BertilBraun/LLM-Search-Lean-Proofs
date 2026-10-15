"""DPO of the policy adapter on an expert-iteration round's preference pairs, on one GPU.

    python experiments/phase6_dpo.py --config experiments/configs/expert_iteration/round_0_policy_dpo.toml \
        --run-name phase6_round_0_policy_dpo [--max-steps N]

Reads $LEAN_SEARCH_DATA/<data>/{train,validation}.jsonl (experiments/phase6_data.py) and starts from
initial_adapter, whose frozen copy is the reference. Writes the adapter to $LEAN_SEARCH_CHECKPOINTS/<run-name>/adapter,
steps.jsonl and evaluations.jsonl to $LEAN_SEARCH_RUNS/<run-name>/ and summary/{summary.json,README.md} there.
"""

import argparse
import dataclasses
import datetime
import json
import os
import random
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import torch
import transformers

from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.dpo import (
    DpoConfig,
    DpoEvaluationRecord,
    DpoMetrics,
    DpoStepRecord,
    DpoTrainingResult,
    train_dpo,
)
from lean_search.training.dpo_data import TokenizedPair, fits, read_pairs, tokenize_pair
from lean_search.training.sft import FineTuningMethod

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
VALIDATION_SEED = 0


@dataclass(frozen=True)
class DpoRunSummary:
    run_name: str
    started: str
    git_revision: str
    config: DpoConfig
    train_pairs: int
    train_over_length: int
    validation_pairs: int
    validation_over_length: int
    tokenization_seconds: float
    result: DpoTrainingResult
    adapter_directory: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--max-steps", type=int, help="overrides optimization.max_steps")
    return parser.parse_args()


def load_config(arguments: argparse.Namespace) -> DpoConfig:
    config = from_json_object(DpoConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    if config.optimization.method != FineTuningMethod.LORA:
        raise ValueError("DPO trains the policy's LoRA adapter: use method = lora.")
    if arguments.max_steps is not None:
        config = dataclasses.replace(
            config, optimization=dataclasses.replace(config.optimization, max_steps=arguments.max_steps)
        )
    return config


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def append_json_line(path: Path, record: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def tokenized_split(
    tokenizer: transformers.PreTrainedTokenizerBase, path: Path, config: DpoConfig
) -> tuple[list[TokenizedPair], int]:
    """The pairs that fit the length caps, and how many did not."""
    tokenized = [
        tokenize_pair(tokenizer, pair, config.thinking_instruction, config.visible_reasoning)
        for pair in read_pairs(path)
    ]
    kept = [pair for pair in tokenized if fits(pair, config.max_prompt_tokens, config.max_completion_tokens)]
    return kept, len(tokenized) - len(kept)


def metrics_cells(metrics: DpoMetrics) -> list[str]:
    return [
        f"{metrics.loss:.4f}",
        f"{metrics.reward_accuracy:.1%}",
        f"{metrics.reward_margin:.3f}",
        f"{metrics.chosen_reward:.3f}",
        f"{metrics.rejected_reward:.3f}",
        f"{metrics.chosen_preferred:.1%}",
    ]


def render_markdown(summary: DpoRunSummary) -> str:
    config = summary.config
    optimization = config.optimization
    result = summary.result
    settings = [
        ["Model", f"`{config.model}` with the adapter `{config.initial_adapter}` (also the frozen reference)"],
        [
            "Data",
            f"`{config.data}`: {summary.train_pairs:,} train pairs ({summary.train_over_length:,} over the length caps "
            f"dropped), {summary.validation_pairs:,} validation pairs",
        ],
        ["Loss", f"DPO, beta {config.beta:g}; chosen NLL weight {config.chosen_nll_weight:g}"],
        [
            "Optimization",
            f"AdamW, learning rate {optimization.learning_rate:g}, warmup {optimization.warmup_fraction:g}, cosine "
            f"to {optimization.minimum_learning_rate_ratio:g}, clip {optimization.max_gradient_norm:g}, "
            f"{optimization.epochs} epoch(s), {optimization.micro_batch_tokens:,} padded tokens per micro-batch, "
            f"{optimization.micro_batches_per_step} micro-batches per step",
        ],
    ]
    throughput = [
        ["Steps", f"{result.steps:,}"],
        ["Items (pairs)", f"{result.items:,} ({result.pairs:,})"],
        ["Tokens", f"{result.tokens:,}"],
        ["Padding overhead", f"{result.padded_tokens / max(1, result.tokens) - 1:.1%}"],
        ["Reference log-probabilities", f"{result.reference_seconds / 60:.1f} min"],
        ["Training time", f"{result.training_seconds / 60:.1f} min"],
        ["Tokens/s", f"{result.tokens_per_second:,.0f}"],
        ["Peak GPU memory", f"{result.peak_memory_gib:.1f} GiB"],
        ["Trainable parameters", f"{result.trainable_parameters:,}"],
    ]
    evaluations = [
        [evaluation.step, *metrics_cells(evaluation.metrics), f"{evaluation.chosen_nll:.4f}"]
        for evaluation in result.evaluations
    ]
    sections = [
        f"# DPO run `{summary.run_name}`",
        markdown_table(["Setting", "Value"], settings),
        "## Throughput",
        markdown_table(["Quantity", "Value"], throughput),
        "## Validation",
        "Rewards are beta · (log π − log π_ref) of the whole completion; reward accuracy counts pairs whose chosen "
        "reward is the larger, chosen preferred pairs where the policy itself gives the chosen step the higher "
        "log-probability; chosen NLL is the mean token NLL of every chosen step, pairs and chosen-only items.",
        markdown_table(
            [
                "Step",
                "Loss",
                "Reward accuracy",
                "Margin",
                "Chosen reward",
                "Rejected reward",
                "Chosen preferred",
                "Chosen NLL",
            ],
            evaluations,
        ),
        f"Started {summary.started}, git {summary.git_revision[:10]}; adapter `{summary.adapter_directory}`.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    config = load_config(arguments)
    run_directory = RUNS_DIRECTORY / arguments.run_name
    (run_directory / "summary").mkdir(parents=True, exist_ok=True)
    for name in ("steps.jsonl", "evaluations.jsonl"):
        (run_directory / name).unlink(missing_ok=True)
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    tokenization_start = time.perf_counter()
    data_directory = DATA_DIRECTORY / config.data
    train_pairs, train_over_length = tokenized_split(tokenizer, data_directory / "train.jsonl", config)
    validation_pairs, validation_over_length = tokenized_split(tokenizer, data_directory / "validation.jsonl", config)
    random.Random(VALIDATION_SEED).shuffle(validation_pairs)
    tokenization_seconds = time.perf_counter() - tokenization_start
    print(
        f"Tokenized {len(train_pairs):,} train and {len(validation_pairs):,} validation pairs "
        f"in {tokenization_seconds:.0f} s",
        flush=True,
    )

    def on_step(record: DpoStepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: DpoEvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        metrics = record.metrics
        print(
            f"evaluation step {record.step}: loss {metrics.loss:.4f}, reward accuracy {metrics.reward_accuracy:.3f}, "
            f"margin {metrics.reward_margin:.3f}, chosen preferred {metrics.chosen_preferred:.3f} "
            f"({record.seconds:.0f} s)",
            flush=True,
        )

    adapter_directory = CHECKPOINTS_DIRECTORY / arguments.run_name / "adapter"
    result = train_dpo(
        config,
        tokenizer,
        train_pairs,
        validation_pairs,
        torch.device("cuda"),
        adapter_directory,
        on_step,
        on_evaluation,
    )
    summary = DpoRunSummary(
        run_name=arguments.run_name,
        started=started,
        git_revision=git_revision(),
        config=config,
        train_pairs=len(train_pairs),
        train_over_length=train_over_length,
        validation_pairs=len(validation_pairs),
        validation_over_length=validation_over_length,
        tokenization_seconds=tokenization_seconds,
        result=result,
        adapter_directory=str(adapter_directory),
    )
    (run_directory / "summary" / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (run_directory / "summary" / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


if __name__ == "__main__":
    main()
