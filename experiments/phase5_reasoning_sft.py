"""Fine-tune the policy adapter on rejection-sampled reasoning data (thinking on) mixed with non-thinking replay.

    torchrun --nproc-per-node 2 experiments/phase5_reasoning_sft.py \
        --config experiments/configs/reasoning/phase5_sft_r1.toml --run-name phase5_sft_r1

The config is an SftConfig whose `data` names $LEAN_SEARCH_DATA/reasoning/<data>/{train,validation}.jsonl (built by
phase5_reasoning_data.py select) and whose `initial_adapter` is usually the SFT policy adapter, so training continues
it. The trainer is lean_search.training.sft; the adapter goes to $LEAN_SEARCH_CHECKPOINTS/<run>/adapter and the
summary to $LEAN_SEARCH_RUNS/<run>/summary/{summary.json,README.md}.
"""

import argparse
import dataclasses
import datetime
import importlib.util
import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

import transformers

from lean_search.reasoning.dataset import read_examples, tokenize_reasoning_example
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft import (
    EvaluationRecord,
    SftConfig,
    SftRunSummary,
    StepRecord,
    distributed_context,
    train,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data")) / "reasoning"
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--max-steps", type=int, help="overrides optimization.max_steps")
    return parser.parse_args()


def load_config(arguments: argparse.Namespace) -> SftConfig:
    config = from_json_object(SftConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
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


def render_markdown(summary: SftRunSummary) -> str:
    config = summary.config
    optimization = config.optimization
    result = summary.result
    settings = [
        ["Model", f"`{config.model}` + adapter `{config.initial_adapter or 'new'}`"],
        ["Data", f"`reasoning/{config.data}`: {summary.train_examples:,} examples, {summary.train_tokens:,} tokens"],
        [
            "Optimization",
            f"learning rate {optimization.learning_rate:g}, warmup {optimization.warmup_fraction:g}, cosine to "
            f"{optimization.minimum_learning_rate_ratio:g}, {optimization.epochs} epoch(s), "
            f"{optimization.micro_batch_tokens:,} padded tokens x {optimization.micro_batches_per_step} micro-batches "
            f"per GPU, {summary.world_size} GPU(s)",
        ],
        ["Steps / tokens / time", f"{result.steps:,} / {result.tokens:,} / {result.training_seconds / 60:.1f} min"],
        ["Tokens/s, peak memory", f"{result.tokens_per_second:,.0f}, {result.peak_memory_gib:.1f} GiB"],
    ]
    evaluations = [
        [
            evaluation.step,
            f"{evaluation.validation_loss:.4f}",
            f"{evaluation.teacher_forced_exact_match:.1%}",
            f"{evaluation.generation_exact_match:.1%}",
        ]
        for evaluation in result.evaluations
    ]
    sections = [
        f"# Reasoning SFT run `{summary.run_name}`",
        markdown_table(["Setting", "Value"], settings),
        "Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of "
        "them and tracks the non-thinking mode; the loss covers both kinds.",
        markdown_table(
            ["Step", "Validation loss", "Teacher-forced exact match", "Non-thinking greedy exact match"], evaluations
        ),
        f"Started {summary.started}, git {summary.git_revision[:10]}; adapter `{summary.trained_model_directory}`.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    config = load_config(arguments)
    context = distributed_context()
    run_directory = RUNS_DIRECTORY / arguments.run_name
    if context.is_main:
        (run_directory / "summary").mkdir(parents=True, exist_ok=True)
        for name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / name).unlink(missing_ok=True)
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    tokenization_start = time.perf_counter()
    data_directory = DATA_DIRECTORY / config.data
    train_examples = [
        tokenize_reasoning_example(tokenizer, example) for example in read_examples(data_directory / "train.jsonl")
    ]
    validation_examples = [
        tokenize_reasoning_example(tokenizer, example) for example in read_examples(data_directory / "validation.jsonl")
    ]
    tokenization_seconds = time.perf_counter() - tokenization_start

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        print(
            f"evaluation step {record.step}: loss {record.validation_loss:.4f}, non-thinking generation exact "
            f"{record.generation_exact_match:.3f} ({record.evaluation_seconds:.0f} s)",
            flush=True,
        )

    adapter_directory = CHECKPOINTS_DIRECTORY / arguments.run_name / "adapter"
    result = train(
        config, tokenizer, train_examples, validation_examples, context, adapter_directory, on_step, on_evaluation
    )
    if not context.is_main:
        return
    summary = SftRunSummary(
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
        trained_model_directory=str(adapter_directory),
        merged_directory="",
        merge_seconds=0.0,
    )
    (run_directory / "summary" / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (run_directory / "summary" / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


if __name__ == "__main__":
    main()
