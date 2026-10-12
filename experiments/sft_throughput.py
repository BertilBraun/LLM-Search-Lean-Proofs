"""SFT training throughput on a random subset of a built SFT data set, and the packed-sequence leakage check.

    python experiments/sft_throughput.py benchmark --config experiments/configs/training/phase2_sft_v2.toml \
        --run-name sft_throughput_baseline --steps 30 [--packing] [--micro-batch-tokens 32768] [--profile]
    torchrun --nproc-per-node 2 experiments/sft_throughput.py benchmark ...
    python experiments/sft_throughput.py check-packing --config experiments/configs/training/phase2_sft_v2.toml

`benchmark` trains `--steps` optimizer steps without evaluation and reports tokens/s over the steps after the
first `--warmup-steps` (Triton autotuning); `--profile` records two steps with the torch profiler.
`check-packing` scores real examples padded and packed, and packed next to changed neighbours.
"""

import argparse
import dataclasses
import json
import os
import random
import time
import tomllib
from pathlib import Path

import torch
import transformers

from lean_search.search.records import from_json_object
from lean_search.training.sft import (
    CompletionLoss,
    SftConfig,
    StepRecord,
    collate,
    distributed_context,
    load_trainable_model,
    pack,
    train,
)
from lean_search.training.sft_data import TokenizedExample, read_examples, tokenize_example

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "sft"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


@dataclasses.dataclass(frozen=True)
class BenchmarkResult:
    run_name: str
    world_size: int
    packing: bool
    micro_batch_tokens: int
    micro_batches_per_step: int
    gradient_checkpointing: bool
    compile_layers: bool
    measured_steps: int
    tokens: int
    padded_tokens: int
    seconds: float
    tokens_per_second: float
    padding_overhead: float
    peak_memory_gib: float


@dataclasses.dataclass(frozen=True)
class PackingCheck:
    examples: int
    completion_tokens: int
    # Per completion token, packed against padded (kernels and summation order differ).
    max_absolute_difference: float
    mean_absolute_difference: float
    mean_padded_loss: float
    mean_packed_loss: float
    # The same packed row with every other example's tokens changed: no leakage leaves these losses identical.
    max_difference_after_changing_neighbours: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--config", type=Path, required=True)
    benchmark.add_argument("--run-name", required=True)
    benchmark.add_argument("--examples", type=int, default=40000)
    benchmark.add_argument("--steps", type=int, default=30)
    benchmark.add_argument("--warmup-steps", type=int, default=5)
    benchmark.add_argument("--packing", action=argparse.BooleanOptionalAction)
    benchmark.add_argument("--micro-batch-tokens", type=int)
    benchmark.add_argument("--micro-batches-per-step", type=int)
    benchmark.add_argument("--gradient-checkpointing", action=argparse.BooleanOptionalAction)
    benchmark.add_argument("--compile-layers", action=argparse.BooleanOptionalAction)
    benchmark.add_argument("--profile", action="store_true")
    check = commands.add_parser("check-packing")
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--examples", type=int, default=64)
    return parser.parse_args()


def load_config(path: Path) -> SftConfig:
    return from_json_object(SftConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def sample_examples(config: SftConfig, count: int) -> list[TokenizedExample]:
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    examples = list(read_examples(DATA_DIRECTORY / config.data / "train.jsonl"))
    selected = random.Random(0).sample(examples, min(count, len(examples)))
    return [tokenize_example(tokenizer, example) for example in selected]


def benchmark(arguments: argparse.Namespace) -> None:
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    config = load_config(arguments.config)
    overrides = {
        "max_steps": arguments.steps,
        "packing": arguments.packing,
        "micro_batch_tokens": arguments.micro_batch_tokens,
        "micro_batches_per_step": arguments.micro_batches_per_step,
        "gradient_checkpointing": arguments.gradient_checkpointing,
        "compile_layers": arguments.compile_layers,
    }
    optimization = dataclasses.replace(
        config.optimization, **{name: value for name, value in overrides.items() if value is not None}
    )
    config = dataclasses.replace(
        config,
        optimization=optimization,
        evaluation=dataclasses.replace(config.evaluation, validation_examples=0),
        merge=False,
    )
    context = distributed_context()
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    examples = sample_examples(config, arguments.examples)
    run_directory = RUNS_DIRECTORY / "sft_throughput" / arguments.run_name
    run_directory.mkdir(parents=True, exist_ok=True)
    records: list[StepRecord] = []
    step_finished: list[float] = []
    profiler = (
        torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
            schedule=torch.profiler.schedule(wait=arguments.warmup_steps, warmup=1, active=2, repeat=1),
        )
        if arguments.profile and context.is_main
        else None
    )
    if profiler is not None:
        profiler.start()

    def on_step(record: StepRecord) -> None:
        records.append(record)
        step_finished.append(time.perf_counter())
        print(json.dumps(dataclasses.asdict(record) | {"unix_time": time.time()}), flush=True)
        if profiler is not None:
            profiler.step()

    result = train(config, tokenizer, examples, [], context, run_directory / "adapter", on_step, lambda _: None)
    if not context.is_main:
        return
    if profiler is not None:
        profiler.stop()
        table = profiler.key_averages().table(sort_by="cuda_time_total", row_limit=40)
        (run_directory / "profile.txt").write_text(table, encoding="utf-8")
        profiler.export_chrome_trace(str(run_directory / "trace.json"))
        print(table)
    measured = records[arguments.warmup_steps :]
    seconds = step_finished[-1] - step_finished[arguments.warmup_steps - 1]
    tokens = sum(record.tokens for record in measured)
    padded_tokens = sum(record.padded_tokens for record in measured)
    summary = BenchmarkResult(
        run_name=arguments.run_name,
        world_size=context.world_size,
        packing=optimization.packing,
        micro_batch_tokens=optimization.micro_batch_tokens,
        micro_batches_per_step=optimization.micro_batches_per_step,
        gradient_checkpointing=optimization.gradient_checkpointing,
        compile_layers=optimization.compile_layers,
        measured_steps=len(measured),
        tokens=tokens,
        padded_tokens=padded_tokens,
        seconds=seconds,
        tokens_per_second=tokens / seconds,
        padding_overhead=padded_tokens / tokens - 1,
        peak_memory_gib=result.peak_memory_gib,
    )
    (run_directory / "summary.json").write_text(json.dumps(dataclasses.asdict(summary), indent=1), encoding="utf-8")
    print(json.dumps(dataclasses.asdict(summary), indent=1), flush=True)


@torch.no_grad()
def per_example_losses(
    loss_module: CompletionLoss, batch_examples: list[TokenizedExample], packed: bool
) -> torch.Tensor:
    device = torch.device("cuda")
    batch = pack(batch_examples, device) if packed else collate(batch_examples, 0, device)
    with torch.autocast("cuda", dtype=torch.bfloat16):
        token_losses, _, _ = loss_module(
            batch.input_ids, batch.attention_mask, batch.labels, batch.position_ids, batch.sequence_starts
        )
    return token_losses.float()


def check_packing(arguments: argparse.Namespace) -> None:
    config = load_config(arguments.config)
    examples = sample_examples(config, arguments.examples)
    optimization = dataclasses.replace(config.optimization, packing=True, gradient_checkpointing=False)
    _, causal_model = load_trainable_model(config.model, optimization, config.lora, torch.device("cuda"))
    causal_model.eval()
    loss_module = CompletionLoss(causal_model)
    padded = torch.cat([per_example_losses(loss_module, [example], packed=False) for example in examples])
    packed = per_example_losses(loss_module, examples, packed=True)
    changed = [
        example if index % 2 else dataclasses.replace(example, input_ids=tuple(reversed(example.input_ids)))
        for index, example in enumerate(examples)
    ]
    packed_changed = per_example_losses(loss_module, changed, packed=True)
    kept = torch.cat(
        [torch.full((example.completion_token_count,), index % 2 == 1) for index, example in enumerate(examples)]
    ).cuda()
    differences = (packed - padded).abs()
    check = PackingCheck(
        examples=len(examples),
        completion_tokens=len(padded),
        max_absolute_difference=differences.max().item(),
        mean_absolute_difference=differences.mean().item(),
        mean_padded_loss=padded.mean().item(),
        mean_packed_loss=packed.mean().item(),
        max_difference_after_changing_neighbours=(packed_changed[kept] - packed[kept]).abs().max().item(),
    )
    print(json.dumps(dataclasses.asdict(check), indent=1), flush=True)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "benchmark":
            benchmark(arguments)
        case "check-packing":
            check_packing(arguments)


if __name__ == "__main__":
    main()
