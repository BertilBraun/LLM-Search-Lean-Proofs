"""Fine-tune the policy (LoRA or full) on a built SFT data set, evaluate on held-out steps, merge the adapter."""

import argparse
import dataclasses
import datetime
import importlib.util
import json
import os
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.policy.adapters import merge_adapter
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft import (
    DistributedContext,
    EvaluationRecord,
    FineTuningMethod,
    SftConfig,
    StepRecord,
    TrainingResult,
    distributed_context,
    train,
)
from lean_search.training.sft_data import read_examples, tokenize_example

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "sft"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


@dataclass(frozen=True)
class RunSummary:
    run_name: str
    started: str
    git_revision: str
    config: SftConfig
    world_size: int
    flash_linear_attention: bool
    train_examples: int
    train_tokens: int
    validation_examples: int
    tokenization_seconds: float
    result: TrainingResult
    trained_model_directory: str
    merged_directory: str
    merge_seconds: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--model", help="overrides the config's model")
    parser.add_argument("--max-steps", type=int, help="overrides optimization.max_steps")
    parser.add_argument("--no-merge", action="store_true")
    return parser.parse_args()


def load_config(arguments: argparse.Namespace) -> SftConfig:
    config = from_json_object(SftConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    if arguments.model:
        config = dataclasses.replace(config, model=arguments.model)
    if arguments.max_steps is not None:
        config = dataclasses.replace(
            config, optimization=dataclasses.replace(config.optimization, max_steps=arguments.max_steps)
        )
    if arguments.no_merge:
        config = dataclasses.replace(config, merge=False)
    return config


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def append_json_line(path: Path, record: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def render_markdown(summary: RunSummary) -> str:
    config = summary.config
    optimization = config.optimization
    result = summary.result
    method = (
        f"LoRA rank {config.lora.rank}, alpha {config.lora.alpha}, dropout {config.lora.dropout:g}"
        if optimization.method == FineTuningMethod.LORA
        else "full fine-tuning (fp32 master weights)"
    )
    settings = [
        ["Model", f"`{config.model}`"],
        ["Data", f"`{config.data}`: {summary.train_examples:,} examples, {summary.train_tokens:,} tokens"],
        ["Method", method],
        [
            "Optimization",
            f"AdamW, learning rate {optimization.learning_rate:g}, warmup {optimization.warmup_fraction:g}, cosine "
            f"to {optimization.minimum_learning_rate_ratio:g}, weight decay {optimization.weight_decay:g}, "
            f"clip {optimization.max_gradient_norm:g}, {optimization.epochs} epoch(s)",
        ],
        [
            "Batching",
            f"{optimization.micro_batch_tokens:,} padded tokens per micro-batch, {optimization.micro_batches_per_step} "
            f"micro-batches per step per GPU, {summary.world_size} GPU(s), length-grouped, gradient checkpointing "
            f"{'on' if optimization.gradient_checkpointing else 'off'}",
        ],
        ["Kernels", "flash-linear-attention" if summary.flash_linear_attention else "PyTorch reference (slow)"],
    ]
    throughput = [
        ["Steps", f"{result.steps:,}"],
        ["Examples", f"{result.examples:,}"],
        ["Tokens (prompt + completion)", f"{result.tokens:,}"],
        ["Completion tokens", f"{result.completion_tokens:,}"],
        ["Padding overhead", f"{result.padded_tokens / max(1, result.tokens) - 1:.1%}"],
        ["Training time", f"{result.training_seconds / 60:.1f} min"],
        ["Tokens/s", f"{result.tokens_per_second:,.0f}"],
        ["Peak GPU memory", f"{result.peak_memory_gib:.1f} GiB"],
        ["Trainable parameters", f"{result.trainable_parameters:,}"],
        ["Merge", f"{summary.merge_seconds:.0f} s" if summary.merged_directory else "not merged"],
    ]
    evaluations = [
        [
            evaluation.step,
            f"{evaluation.validation_loss:.4f}",
            f"{evaluation.teacher_forced_exact_match:.1%}",
            f"{evaluation.generation_exact_match:.1%}",
            f"{evaluation.evaluation_seconds:.0f}",
        ]
        for evaluation in result.evaluations
    ]
    final = result.evaluations[-1]
    mismatches = "\n\n".join(
        f"- target `{sample.target}`, generated `{sample.generated}`" for sample in final.mismatches[:5]
    )
    merged = f", merged `{summary.merged_directory}`" if summary.merged_directory else ""
    sections = [
        f"# SFT run `{summary.run_name}`",
        markdown_table(["Setting", "Value"], settings),
        "## Throughput",
        markdown_table(["Quantity", "Value"], throughput),
        "## Validation",
        f"Loss is the mean completion-token loss over {final.validation_examples:,} held-out steps; teacher-forced "
        "exact match counts steps whose every target token is the argmax; generation exact match compares "
        f"greedy generations on the first {final.generation_examples} of them with the normalized target.",
        markdown_table(
            ["Step", "Validation loss", "Teacher-forced exact match", "Generation exact match", "Seconds"],
            evaluations,
        ),
        "Final mismatches (first five):\n\n" + mismatches,
        f"Started {summary.started}, git {summary.git_revision[:10]}; checkpoint "
        f"`{summary.trained_model_directory}`{merged}.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    config = load_config(arguments)
    context: DistributedContext = distributed_context()
    run_directory = RUNS_DIRECTORY / arguments.run_name
    checkpoint_directory = CHECKPOINTS_DIRECTORY / arguments.run_name
    if context.is_main:
        (run_directory / "summary").mkdir(parents=True, exist_ok=True)
        for name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / name).unlink(missing_ok=True)
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    tokenization_start = time.perf_counter()
    data_directory = DATA_DIRECTORY / config.data
    train_examples = [tokenize_example(tokenizer, example) for example in read_examples(data_directory / "train.jsonl")]
    validation_examples = [
        tokenize_example(tokenizer, example) for example in read_examples(data_directory / "validation.jsonl")
    ]
    tokenization_seconds = time.perf_counter() - tokenization_start
    if context.is_main:
        print(
            f"Tokenized {len(train_examples):,} train and {len(validation_examples):,} validation examples "
            f"in {tokenization_seconds:.0f} s",
            flush=True,
        )

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        print(
            f"evaluation step {record.step}: loss {record.validation_loss:.4f}, teacher-forced exact "
            f"{record.teacher_forced_exact_match:.3f}, generation exact {record.generation_exact_match:.3f} "
            f"({record.evaluation_seconds:.0f} s)",
            flush=True,
        )

    trained_directory = checkpoint_directory / (
        "adapter" if config.optimization.method == FineTuningMethod.LORA else "model"
    )
    result = train(
        config, tokenizer, train_examples, validation_examples, context, trained_directory, on_step, on_evaluation
    )
    if not context.is_main:
        return
    merged_directory = ""
    merge_seconds = 0.0
    if config.merge and config.optimization.method == FineTuningMethod.LORA:
        merge_start = time.perf_counter()
        merge_adapter(config.model, trained_directory, checkpoint_directory / "merged")
        merge_seconds = time.perf_counter() - merge_start
        merged_directory = str(checkpoint_directory / "merged")
    summary = RunSummary(
        run_name=arguments.run_name,
        started=started,
        git_revision=git_revision(),
        config=config,
        world_size=context.world_size,
        flash_linear_attention=importlib.util.find_spec("fla") is not None,
        train_examples=len(train_examples),
        train_tokens=sum(example.token_count for example in train_examples),
        validation_examples=len(validation_examples),
        tokenization_seconds=tokenization_seconds,
        result=result,
        trained_model_directory=str(trained_directory),
        merged_directory=merged_directory,
        merge_seconds=merge_seconds,
    )
    (run_directory / "summary" / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (run_directory / "summary" / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


if __name__ == "__main__":
    main()
