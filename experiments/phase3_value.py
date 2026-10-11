"""Train the value model (a LoRA adapter) on a built value data set and evaluate it on held-out states.

    python experiments/phase3_value.py --config experiments/configs/training/phase3_value_v0.toml \
        --run-name phase3_value_v0 [--model M] [--max-steps N]

Reads $LEAN_SEARCH_DATA/value/<data>/{train,validation}.jsonl; writes the adapter to
$LEAN_SEARCH_CHECKPOINTS/<run-name>/adapter, steps.jsonl and evaluations.jsonl to $LEAN_SEARCH_RUNS/<run-name>/ and
summary/{summary.json,README.md} there. Serve the adapter with `--lora-modules <name>=<adapter directory>` and set
value.adapter = "<name>" in the search config.
"""

import argparse
import dataclasses
import datetime
import importlib.util
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
from lean_search.training.sft import FineTuningMethod
from lean_search.value.bins import STEP_BIN_COUNT
from lean_search.value.labels import read_examples
from lean_search.value.training import (
    TokenizedValueExample,
    ValueEvaluationRecord,
    ValueStepRecord,
    ValueTrainingConfig,
    ValueTrainingResult,
    tokenize_value_example,
    train_value_model,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "value"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
VALIDATION_SEED = 0


@dataclass(frozen=True)
class ValueRunSummary:
    run_name: str
    started: str
    git_revision: str
    config: ValueTrainingConfig
    flash_linear_attention: bool
    train_examples: int
    train_over_length: int
    validation_examples: int
    validation_over_length: int
    tokenization_seconds: float
    result: ValueTrainingResult
    adapter_directory: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--model", help="overrides the config's model")
    parser.add_argument("--max-steps", type=int, help="overrides optimization.max_steps")
    return parser.parse_args()


def load_config(arguments: argparse.Namespace) -> ValueTrainingConfig:
    config = from_json_object(ValueTrainingConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    if config.optimization.method != FineTuningMethod.LORA:
        raise ValueError("The value model is served as a LoRA adapter next to the policy: use method = lora.")
    if arguments.model:
        config = dataclasses.replace(config, model=arguments.model)
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
    tokenizer: transformers.PreTrainedTokenizerBase, path: Path, max_prompt_tokens: int
) -> tuple[list[TokenizedValueExample], int]:
    """The examples whose prompts fit, and how many did not."""
    tokenized = [tokenize_value_example(tokenizer, example) for example in read_examples(path)]
    kept = [example for example in tokenized if example.token_count <= max_prompt_tokens]
    return kept, len(tokenized) - len(kept)


def optional(value: float | None, format_specification: str) -> str:
    return "–" if value is None else format(value, format_specification)


def render_markdown(summary: ValueRunSummary) -> str:
    config = summary.config
    optimization = config.optimization
    result = summary.result
    settings = [
        ["Model", f"`{config.model}`"],
        [
            "Data",
            f"`{config.data}`: {summary.train_examples:,} train states ({summary.train_over_length:,} over "
            f"{config.max_prompt_tokens:,} prompt tokens dropped), {summary.validation_examples:,} validation states",
        ],
        ["LoRA", f"rank {config.lora.rank}, alpha {config.lora.alpha}, dropout {config.lora.dropout:g}"],
        [
            "Optimization",
            f"AdamW, learning rate {optimization.learning_rate:g}, warmup {optimization.warmup_fraction:g}, cosine "
            f"to {optimization.minimum_learning_rate_ratio:g}, clip {optimization.max_gradient_norm:g}, "
            f"{optimization.epochs} epoch(s), {optimization.micro_batch_tokens:,} padded tokens per micro-batch, "
            f"{optimization.micro_batches_per_step} micro-batches per step",
        ],
        [
            "Loss",
            f"Gaussian smoothing sigma {config.loss.smoothing_sigma:g} bins, bin-mass weight "
            f"{config.loss.bin_mass_weight:g}",
        ],
        [
            "Readout",
            f"8+ = {config.readout.eight_or_more_steps:g} steps, dead = {config.readout.dead_steps:g} steps",
        ],
        ["Kernels", "flash-linear-attention" if summary.flash_linear_attention else "PyTorch reference (slow)"],
    ]
    throughput = [
        ["Steps", f"{result.steps:,}"],
        ["Examples", f"{result.examples:,}"],
        ["Tokens", f"{result.tokens:,}"],
        ["Padding overhead", f"{result.padded_tokens / max(1, result.tokens) - 1:.1%}"],
        ["Training time", f"{result.training_seconds / 60:.1f} min"],
        ["Tokens/s", f"{result.tokens_per_second:,.0f}"],
        ["Peak GPU memory", f"{result.peak_memory_gib:.1f} GiB"],
        ["Trainable parameters", f"{result.trainable_parameters:,}"],
    ]
    evaluations = [
        [
            evaluation.step,
            f"{evaluation.value_loss:.4f}",
            optional(evaluation.metrics.bin_accuracy, ".1%"),
            optional(evaluation.metrics.alive_mean_absolute_error, ".3f"),
            optional(evaluation.metrics.spearman, ".3f"),
            optional(evaluation.metrics.dead_auc, ".3f"),
            f"{evaluation.bin_mass:.3f}",
            f"{evaluation.served_h_error:.4f}",
        ]
        for evaluation in result.evaluations
    ]
    final = result.evaluations[-1]
    bin_names = [str(steps) for steps in range(1, STEP_BIN_COUNT)] + [f"{STEP_BIN_COUNT}+", "dead"]
    confusion = [[name, *row] for name, row in zip(bin_names, final.metrics.confusion, strict=True)]
    sections = [
        f"# Value run `{summary.run_name}`",
        markdown_table(["Setting", "Value"], settings),
        "## Throughput",
        markdown_table(["Quantity", "Value"], throughput),
        "## Validation",
        f"On {final.examples:,} held-out states. Bin accuracy: the most likely of the nine bins is the label's bin. "
        "MAE: expected steps given alive against the label (8+ read out as in the readout). Spearman: h against the "
        "exact remaining steps. Dead AUC: p_dead separating dead from exact labels. Bin mass: full-vocabulary "
        f"probability of the nine bin tokens. Served h error: mean |h read from the "
        f"top-{config.evaluation.served_top_k} logprobs vLLM returns (bins outside them at the smallest returned "
        "logprob) − h from all nine bins|.",
        markdown_table(
            ["Step", "Loss", "Bin accuracy", "MAE", "Spearman", "Dead AUC", "Bin mass", "Served h error"],
            evaluations,
        ),
        "Final confusion (rows: label bin, columns: most likely bin):",
        markdown_table(["Label", *bin_names], confusion),
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
    train_examples, train_over_length = tokenized_split(
        tokenizer, data_directory / "train.jsonl", config.max_prompt_tokens
    )
    validation_examples, validation_over_length = tokenized_split(
        tokenizer, data_directory / "validation.jsonl", config.max_prompt_tokens
    )
    random.Random(VALIDATION_SEED).shuffle(validation_examples)
    tokenization_seconds = time.perf_counter() - tokenization_start
    print(
        f"Tokenized {len(train_examples):,} train and {len(validation_examples):,} validation states "
        f"in {tokenization_seconds:.0f} s",
        flush=True,
    )

    def on_step(record: ValueStepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: ValueEvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        metrics = record.metrics
        print(
            f"evaluation step {record.step}: loss {record.value_loss:.4f}, bin accuracy "
            f"{optional(metrics.bin_accuracy, '.3f')}, MAE {optional(metrics.alive_mean_absolute_error, '.3f')}, "
            f"Spearman {optional(metrics.spearman, '.3f')}, dead AUC {optional(metrics.dead_auc, '.3f')}, bin mass "
            f"{record.bin_mass:.3f}, served h error {record.served_h_error:.4f} ({record.seconds:.0f} s)",
            flush=True,
        )

    adapter_directory = CHECKPOINTS_DIRECTORY / arguments.run_name / "adapter"
    result = train_value_model(
        config,
        tokenizer,
        train_examples,
        validation_examples,
        torch.device("cuda"),
        adapter_directory,
        on_step,
        on_evaluation,
    )
    summary = ValueRunSummary(
        run_name=arguments.run_name,
        started=started,
        git_revision=git_revision(),
        config=config,
        flash_linear_attention=importlib.util.find_spec("fla") is not None,
        train_examples=len(train_examples),
        train_over_length=train_over_length,
        validation_examples=len(validation_examples),
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
