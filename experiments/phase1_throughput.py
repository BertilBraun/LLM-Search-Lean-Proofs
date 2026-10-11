import argparse
import asyncio
import importlib.metadata
import itertools
import json
import os
import random
import re
import statistics
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple

import httpx
from transformers import AutoTokenizer, PreTrainedTokenizerBase

from lean_search.policy import PolicyClient
from lean_search.policy.adapters import create_zero_adapter, merge_adapter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase1_throughput"
CHECKPOINT_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"]) / "phase1_throughput"
SERVER_LOG_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "servers"

SAMPLE_COUNT = 16
ADAPTER_RANK = 64
PROMPT_POOL_SIZE = 6000
INSTRUCTION = (
    "You are proving a theorem in Lean 4 with Mathlib. Below is the current proof state. "
    "Write the next tactic block that makes progress on the goal. Output only Lean code."
)


class CandidateModel(NamedTuple):
    name: str
    repository: str
    max_model_len: int


CANDIDATE_MODELS = {
    model.name: model
    for model in [
        CandidateModel("qwen3.5-0.8b", "Qwen/Qwen3.5-0.8B", 8192),
        CandidateModel("qwen3.5-2b", "Qwen/Qwen3.5-2B", 8192),
        CandidateModel("qwen3.5-4b", "Qwen/Qwen3.5-4B", 8192),
        CandidateModel("qwen3-1.7b", "Qwen/Qwen3-1.7B", 8192),
        CandidateModel("qwen2.5-math-1.5b", "Qwen/Qwen2.5-Math-1.5B-Instruct", 4096),
    ]
}


class Workload(NamedTuple):
    name: str
    prompt_tokens: int
    max_tokens: int
    enable_thinking: bool


WORKLOADS = {
    workload.name: workload
    for workload in [
        Workload("prompt600-short", 600, 96, False),
        Workload("prompt600-thinking", 600, 512, True),
        Workload("prompt1500-short", 1500, 96, False),
        Workload("prompt1500-thinking", 1500, 512, True),
    ]
}


class LoadSettings(NamedTuple):
    concurrency: int
    warmup_seconds: float
    window_seconds: float


class ServerSettings(NamedTuple):
    gpu: int
    port: int
    max_num_seqs: int | None
    max_num_batched_tokens: int | None


@dataclass(frozen=True)
class ServerCounters:
    timestamp: float
    generation_tokens: float
    computed_prompt_tokens: float
    cached_prompt_tokens: float
    preemptions: float


@dataclass(frozen=True)
class ServerGauges:
    running_requests: float
    waiting_requests: float
    kv_cache_usage: float


@dataclass(frozen=True)
class CompletedRequest:
    end: float
    prompt_tokens: int


@dataclass(frozen=True)
class Measurement:
    model: str
    variant: str
    workload: str
    prompt_tokens_target: int
    max_tokens: int
    enable_thinking: bool
    sample_count: int
    concurrency: int
    max_num_seqs: int | None
    max_num_batched_tokens: int | None
    window_seconds: float
    generated_tokens_per_second: float
    samples_per_second: float
    requests_per_second: float
    mean_prompt_tokens: float
    prompt_tokens_per_second: float
    computed_prompt_tokens_per_second: float
    prefix_cache_hit_rate: float | None
    preemptions: float
    mean_running_requests: float
    mean_waiting_requests: float
    mean_kv_cache_usage: float
    peak_gpu_memory_mib: int


@dataclass(frozen=True)
class ServerStart:
    model: str
    variant: str
    startup_seconds: float
    weights_gib: float
    kv_cache_gib: float
    kv_cache_tokens: int
    max_num_seqs: int | None
    max_num_batched_tokens: int | None


@dataclass(frozen=True)
class AdapterTiming:
    model: str
    adapter_creation_seconds: float
    base_request_seconds: float
    load_adapter_seconds: float
    first_adapter_request_seconds: float
    swap_adapter_seconds: float
    first_request_after_swap_seconds: float
    merge_seconds: float
    stop_server_seconds: float
    merged_server_startup_seconds: float
    first_merged_request_seconds: float


def random_term(randomness: random.Random, variables: list[str], depth: int) -> str:
    if depth == 0 or randomness.random() < 0.25:
        return randomness.choice([*variables, str(randomness.randint(0, 99))])
    match randomness.randrange(4):
        case 0 | 1:
            operator = randomness.choice(["+", "-", "*", "/"])
            left = random_term(randomness, variables, depth - 1)
            right = random_term(randomness, variables, depth - 1)
            return f"({left} {operator} {right})"
        case 2:
            function = randomness.choice(["f", "g", "Real.sqrt", "Real.log", "|", "Real.exp"])
            argument = random_term(randomness, variables, depth - 1)
            return f"|{argument}|" if function == "|" else f"{function} {argument}"
        case _:
            return f"{random_term(randomness, variables, depth - 1)} ^ {randomness.randint(2, 5)}"


def synthetic_proof_state(randomness: random.Random, hypothesis_count: int) -> str:
    variables = randomness.sample(
        ["a", "b", "c", "d", "x", "y", "z", "n", "m", "k", "p", "q"], randomness.randint(3, 7)
    )
    relations = ["≤", "<", "=", "≠"]
    lines = [f"{' '.join(variables)} : ℝ", "f g : ℝ → ℝ", "hf : ∀ (t : ℝ), 0 < t → f t = g (t + 1) - 2 * t"]
    for index in range(hypothesis_count):
        left = random_term(randomness, variables, 3)
        right = random_term(randomness, variables, 2)
        lines.append(f"h{index} : {left} {randomness.choice(relations)} {right}")
    goal_left = random_term(randomness, variables, 4)
    goal_right = random_term(randomness, variables, 3)
    lines.append(f"⊢ {goal_left} {randomness.choice(relations)} {goal_right}")
    return "\n".join(lines)


def render_prompt(tokenizer: PreTrainedTokenizerBase, proof_state: str, enable_thinking: bool) -> str:
    messages = [{"role": "user", "content": f"{INSTRUCTION}\n\n```lean\n{proof_state}\n```"}]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=enable_thinking
    )


def build_prompts(tokenizer: PreTrainedTokenizerBase, workload: Workload, seed: int) -> list[str]:
    randomness = random.Random(seed)

    def mean_token_count(hypothesis_count: int) -> float:
        prompts = [
            render_prompt(tokenizer, synthetic_proof_state(randomness, hypothesis_count), workload.enable_thinking)
            for _ in range(20)
        ]
        return statistics.mean(len(tokenizer(prompt, add_special_tokens=False).input_ids) for prompt in prompts)

    small, large = mean_token_count(10), mean_token_count(50)
    tokens_per_hypothesis = (large - small) / 40
    hypothesis_count = max(1, round(10 + (workload.prompt_tokens - small) / tokens_per_hypothesis))
    return [
        render_prompt(tokenizer, synthetic_proof_state(randomness, hypothesis_count), workload.enable_thinking)
        for _ in range(PROMPT_POOL_SIZE)
    ]


def parse_metrics(text: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        series, _, value = line.rpartition(" ")
        name = series.split("{")[0]
        source = re.search(r'source="([^"]+)"', series)
        totals[f"{name}:{source.group(1)}" if source else name] += float(value)
    return totals


async def read_metrics(http: httpx.AsyncClient, port: int) -> dict[str, float]:
    response = await http.get(f"http://127.0.0.1:{port}/metrics")
    response.raise_for_status()
    return parse_metrics(response.text)


async def read_counters(http: httpx.AsyncClient, port: int) -> ServerCounters:
    metrics = await read_metrics(http, port)
    return ServerCounters(
        timestamp=time.monotonic(),
        generation_tokens=metrics["vllm:generation_tokens_total"],
        computed_prompt_tokens=metrics["vllm:prompt_tokens_by_source_total:local_compute"],
        cached_prompt_tokens=metrics["vllm:prompt_tokens_by_source_total:local_cache_hit"],
        preemptions=metrics["vllm:num_preemptions_total"],
    )


async def read_gauges(http: httpx.AsyncClient, port: int) -> ServerGauges:
    metrics = await read_metrics(http, port)
    return ServerGauges(
        running_requests=metrics["vllm:num_requests_running"],
        waiting_requests=metrics["vllm:num_requests_waiting"],
        kv_cache_usage=metrics["vllm:kv_cache_usage_perc"],
    )


def gpu_memory_used_mib(gpu: int) -> int:
    output = subprocess.run(
        ["nvidia-smi", f"--id={gpu}", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip())


async def measure_throughput(
    model: CandidateModel,
    variant: str,
    workload: Workload,
    prompts: list[str],
    load: LoadSettings,
    server: ServerSettings,
    served_name: str,
    adapter: str | None,
) -> Measurement:
    prompt_cycle = itertools.cycle(prompts)
    completed: list[CompletedRequest] = []
    async with PolicyClient(f"http://127.0.0.1:{server.port}/v1", served_name) as client:

        async def worker() -> None:
            while True:
                generation = await client.generate(
                    next(prompt_cycle),
                    sample_count=SAMPLE_COUNT,
                    max_tokens=workload.max_tokens,
                    temperature=1.0,
                    adapter=adapter,
                    ignore_eos=True,
                )
                completed.append(CompletedRequest(end=time.monotonic(), prompt_tokens=generation.prompt_token_count))

        workers = [asyncio.create_task(worker()) for _ in range(load.concurrency)]
        async with httpx.AsyncClient(timeout=30.0) as http:
            await asyncio.sleep(load.warmup_seconds)
            start = await read_counters(http, server.port)
            gauges: list[ServerGauges] = []
            memory: list[int] = []
            while time.monotonic() < start.timestamp + load.window_seconds:
                await asyncio.sleep(5.0)
                gauges.append(await read_gauges(http, server.port))
                memory.append(await asyncio.to_thread(gpu_memory_used_mib, server.gpu))
            end = await read_counters(http, server.port)
        for task in workers:
            task.cancel()
        outcomes = await asyncio.gather(*workers, return_exceptions=True)

    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    if failures:
        raise failures[0]
    window = end.timestamp - start.timestamp
    in_window = [request for request in completed if start.timestamp <= request.end <= end.timestamp]
    generated_tokens_per_second = (end.generation_tokens - start.generation_tokens) / window
    computed_prompt_tokens = end.computed_prompt_tokens - start.computed_prompt_tokens
    cached_prompt_tokens = end.cached_prompt_tokens - start.cached_prompt_tokens
    prompt_tokens = computed_prompt_tokens + cached_prompt_tokens
    mean_prompt_tokens = statistics.mean(request.prompt_tokens for request in in_window)
    return Measurement(
        model=model.name,
        variant=variant,
        workload=workload.name,
        prompt_tokens_target=workload.prompt_tokens,
        max_tokens=workload.max_tokens,
        enable_thinking=workload.enable_thinking,
        sample_count=SAMPLE_COUNT,
        concurrency=load.concurrency,
        max_num_seqs=server.max_num_seqs,
        max_num_batched_tokens=server.max_num_batched_tokens,
        window_seconds=window,
        generated_tokens_per_second=generated_tokens_per_second,
        samples_per_second=generated_tokens_per_second / workload.max_tokens,
        requests_per_second=len(in_window) / window,
        mean_prompt_tokens=mean_prompt_tokens,
        prompt_tokens_per_second=len(in_window) * mean_prompt_tokens / window,
        computed_prompt_tokens_per_second=computed_prompt_tokens / window,
        prefix_cache_hit_rate=cached_prompt_tokens / prompt_tokens if prompt_tokens else None,
        preemptions=end.preemptions - start.preemptions,
        mean_running_requests=statistics.mean(gauge.running_requests for gauge in gauges),
        mean_waiting_requests=statistics.mean(gauge.waiting_requests for gauge in gauges),
        mean_kv_cache_usage=statistics.mean(gauge.kv_cache_usage for gauge in gauges),
        peak_gpu_memory_mib=max(memory),
    )


def server_arguments(server: ServerSettings, extra_arguments: list[str]) -> list[str]:
    arguments = list(extra_arguments)
    if server.max_num_seqs is not None:
        arguments += ["--max-num-seqs", str(server.max_num_seqs)]
    if server.max_num_batched_tokens is not None:
        arguments += ["--max-num-batched-tokens", str(server.max_num_batched_tokens)]
    return arguments


def start_server(
    model: CandidateModel,
    variant: str,
    served_name: str,
    model_path: str,
    server: ServerSettings,
    extra_arguments: list[str],
) -> ServerStart:
    started = time.monotonic()
    subprocess.run(
        [
            str(REPOSITORY_ROOT / "deployment" / "serve_model.sh"),
            served_name,
            model_path,
            str(server.gpu),
            str(server.port),
            *server_arguments(server, extra_arguments),
        ],
        check=True,
        env=os.environ | {"MAX_MODEL_LEN": str(model.max_model_len)},
    )
    startup_seconds = time.monotonic() - started
    log = (SERVER_LOG_DIRECTORY / f"{served_name}.log").read_text(errors="replace")
    return ServerStart(
        model=model.name,
        variant=variant,
        startup_seconds=startup_seconds,
        weights_gib=float(re.search(r"Model loading took ([\d.]+) GiB", log).group(1)),
        kv_cache_gib=float(re.search(r"Available KV cache memory: ([\d.]+) GiB", log).group(1)),
        kv_cache_tokens=int(re.search(r"GPU KV cache size: ([\d,]+) tokens", log).group(1).replace(",", "")),
        max_num_seqs=server.max_num_seqs,
        max_num_batched_tokens=server.max_num_batched_tokens,
    )


def stop_server(served_name: str) -> float:
    started = time.monotonic()
    subprocess.run([str(REPOSITORY_ROOT / "deployment" / "stop_model.sh"), served_name], check=True)
    return time.monotonic() - started


def append_record(file_name: str, record: Measurement | ServerStart | AdapterTiming) -> None:
    RUN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (RUN_DIRECTORY / file_name).open("a") as file:
        file.write(json.dumps(asdict(record)) + "\n")
    print(json.dumps(asdict(record)), flush=True)


async def measure_workloads(
    model: CandidateModel,
    variant: str,
    workloads: list[Workload],
    load: LoadSettings,
    server: ServerSettings,
    served_name: str,
    adapter: str | None,
) -> None:
    tokenizer = AutoTokenizer.from_pretrained(model.repository)
    for index, workload in enumerate(workloads):
        prompts = build_prompts(tokenizer, workload, seed=index)
        measurement = await measure_throughput(model, variant, workload, prompts, load, server, served_name, adapter)
        append_record("measurements.jsonl", measurement)
        # Requests cancelled at the end of the window are still being aborted by the server.
        await asyncio.sleep(5.0)


async def timed_request(client: PolicyClient, adapter: str | None) -> float:
    started = time.monotonic()
    await client.generate(
        "theorem t (a b : Nat) : a + b = b + a := by\n  ", sample_count=1, max_tokens=8, adapter=adapter
    )
    return time.monotonic() - started


def timed(function: Callable[..., object], *arguments: object) -> float:
    started = time.monotonic()
    function(*arguments)
    return time.monotonic() - started


async def run_sweep(arguments: argparse.Namespace) -> None:
    load = LoadSettings(arguments.concurrency, arguments.warmup_seconds, arguments.window_seconds)
    server = ServerSettings(arguments.gpu, arguments.port, arguments.max_num_seqs, arguments.max_num_batched_tokens)
    workloads = [WORKLOADS[name] for name in arguments.workloads]
    for model_name in arguments.models:
        model = CANDIDATE_MODELS[model_name]
        append_record(
            "server_starts.jsonl",
            start_server(model, arguments.variant, model.name, model.repository, server, arguments.server_argument),
        )
        try:
            await measure_workloads(model, arguments.variant, workloads, load, server, model.name, adapter=None)
        finally:
            stop_server(model.name)


async def run_adapter_comparison(arguments: argparse.Namespace) -> None:
    load = LoadSettings(arguments.concurrency, arguments.warmup_seconds, arguments.window_seconds)
    server = ServerSettings(arguments.gpu, arguments.port, arguments.max_num_seqs, arguments.max_num_batched_tokens)
    workloads = [WORKLOADS[name] for name in arguments.workloads]
    model = CANDIDATE_MODELS[arguments.models[0]]
    adapter_directories = [CHECKPOINT_DIRECTORY / f"{model.name}-zero-r{ADAPTER_RANK}-{index}" for index in range(2)]
    merged_directory = CHECKPOINT_DIRECTORY / f"{model.name}-merged"

    adapter_creation_seconds = timed(create_zero_adapter, model.repository, adapter_directories[0], ADAPTER_RANK)
    create_zero_adapter(model.repository, adapter_directories[1], ADAPTER_RANK)

    append_record(
        "server_starts.jsonl",
        start_server(model, "LoRA server", model.name, model.repository, server, arguments.server_argument),
    )
    async with PolicyClient(f"http://127.0.0.1:{server.port}/v1", model.name) as client:
        await timed_request(client, adapter=None)
        base_request_seconds = await timed_request(client, adapter=None)
        started = time.monotonic()
        await client.load_adapter("adapter-0", str(adapter_directories[0]))
        load_adapter_seconds = time.monotonic() - started
        first_adapter_request_seconds = await timed_request(client, adapter="adapter-0")
    await measure_workloads(model, "LoRA server, base requests", workloads, load, server, model.name, adapter=None)
    await measure_workloads(
        model, "LoRA server, rank-64 adapter", workloads, load, server, model.name, adapter="adapter-0"
    )
    async with PolicyClient(f"http://127.0.0.1:{server.port}/v1", model.name) as client:
        started = time.monotonic()
        await client.unload_adapter("adapter-0")
        await client.load_adapter("adapter-1", str(adapter_directories[1]))
        swap_adapter_seconds = time.monotonic() - started
        first_request_after_swap_seconds = await timed_request(client, adapter="adapter-1")

    merge_seconds = timed(merge_adapter, model.repository, adapter_directories[1], merged_directory)
    stop_server_seconds = stop_server(model.name)
    merged_start = start_server(
        model,
        "merged, LoRA disabled",
        model.name,
        str(merged_directory),
        server,
        ["--no-enable-lora", *arguments.server_argument],
    )
    append_record("server_starts.jsonl", merged_start)
    try:
        async with PolicyClient(f"http://127.0.0.1:{server.port}/v1", model.name) as client:
            first_merged_request_seconds = await timed_request(client, adapter=None)
        await measure_workloads(model, "merged, LoRA disabled", workloads, load, server, model.name, adapter=None)
    finally:
        stop_server(model.name)

    append_record(
        "adapter_timings.jsonl",
        AdapterTiming(
            model=model.name,
            adapter_creation_seconds=adapter_creation_seconds,
            base_request_seconds=base_request_seconds,
            load_adapter_seconds=load_adapter_seconds,
            first_adapter_request_seconds=first_adapter_request_seconds,
            swap_adapter_seconds=swap_adapter_seconds,
            first_request_after_swap_seconds=first_request_after_swap_seconds,
            merge_seconds=merge_seconds,
            stop_server_seconds=stop_server_seconds,
            merged_server_startup_seconds=merged_start.startup_seconds,
            first_merged_request_seconds=first_merged_request_seconds,
        ),
    )


def read_records[Record: (Measurement, ServerStart, AdapterTiming)](
    file_name: str, record_type: type[Record]
) -> list[Record]:
    path = RUN_DIRECTORY / file_name
    return [record_type(**json.loads(line)) for line in path.read_text().splitlines()] if path.exists() else []


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def environment_description() -> dict[str, str]:
    gpu = subprocess.run(
        ["nvidia-smi", "--id=0", "--query-gpu=name,driver_version", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    packages = ["vllm", "torch", "transformers", "peft", "flashinfer-python", "triton"]
    return {"gpu": gpu} | {package: importlib.metadata.version(package) for package in packages}


def write_summary() -> None:
    summary_directory = RUN_DIRECTORY / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    measurements = list(
        {
            (record.model, record.variant, record.workload, record.concurrency): record
            for record in read_records("measurements.jsonl", Measurement)
        }.values()
    )
    server_starts = read_records("server_starts.jsonl", ServerStart)
    adapter_timings = read_records("adapter_timings.jsonl", AdapterTiming)
    environment = environment_description()
    for name, content in [
        ("measurements.json", [asdict(record) for record in measurements]),
        ("server_starts.json", [asdict(record) for record in server_starts]),
        ("adapter_timings.json", [asdict(record) for record in adapter_timings]),
        ("environment.json", environment),
    ]:
        (summary_directory / name).write_text(json.dumps(content, indent=2) + "\n")

    throughput_rows = [
        [
            str(record.model),
            str(record.variant),
            str(record.workload),
            f"{record.mean_prompt_tokens:.0f}",
            f"{record.generated_tokens_per_second:,.0f}",
            f"{record.samples_per_second:.1f}",
            f"{record.requests_per_second:.2f}",
            f"{record.prompt_tokens_per_second:,.0f}",
            f"{record.computed_prompt_tokens_per_second:,.0f}",
            "n/a" if record.prefix_cache_hit_rate is None else f"{record.prefix_cache_hit_rate:.2f}",
            f"{record.mean_running_requests:.0f}",
            f"{record.mean_kv_cache_usage:.2f}",
            f"{record.peak_gpu_memory_mib:,}",
        ]
        for record in measurements
    ]
    server_rows = [
        [
            str(record.model),
            str(record.variant),
            f"{record.startup_seconds:.0f}",
            f"{record.weights_gib:.2f}",
            f"{record.kv_cache_gib:.2f}",
            f"{record.kv_cache_tokens:,}",
            str(record.max_num_seqs or "default"),
            str(record.max_num_batched_tokens or "default"),
        ]
        for record in server_starts
    ]
    adapter_rows = [
        [key, f"{value:.2f}" if isinstance(value, float) else str(value)]
        for record in adapter_timings
        for key, value in asdict(record).items()
    ]
    readme = "\n\n".join(
        [
            "# Phase 1: vLLM throughput at the proof-search prompt shape",
            f"One {environment['gpu'].split(',')[0]} per server; vllm {environment['vllm']}, "
            f"torch {environment['torch']}. Every request asks for n={SAMPLE_COUNT} samples with `ignore_eos`, "
            "so each sample is exactly `max_tokens` long; prompts are unique synthetic Lean proof states rendered "
            "with the model's chat template. Generated tokens/s and computed prompt tokens/s come from the "
            "server's counters over the measurement window; prompt tokens/s counts each request's prompt once.",
            "## Throughput",
            markdown_table(
                [
                    "Model",
                    "Variant",
                    "Workload",
                    "Prompt tokens",
                    "Generated tokens/s",
                    "Samples/s",
                    "Requests/s",
                    "Prompt tokens/s",
                    "Computed prompt tokens/s",
                    "Prefix cache hit rate",
                    "Running requests",
                    "KV cache use",
                    "Peak GPU MiB",
                ],
                throughput_rows,
            ),
            "## Server starts",
            markdown_table(
                [
                    "Model",
                    "Variant",
                    "Startup s",
                    "Weights GiB",
                    "KV cache GiB",
                    "KV cache tokens",
                    "max_num_seqs",
                    "max_num_batched_tokens",
                ],
                server_rows,
            ),
            "## Adapter load, swap and merge timings (seconds)",
            markdown_table(["Quantity", "Value"], adapter_rows),
        ]
    )
    (summary_directory / "README.md").write_text(readme + "\n")
    print(readme)


def main() -> None:
    parser = argparse.ArgumentParser(description="vLLM throughput at the proof-search prompt shape, one GPU.")
    parser.add_argument("mode", choices=["sweep", "adapter", "summarize"])
    parser.add_argument("--models", nargs="+", choices=sorted(CANDIDATE_MODELS), default=sorted(CANDIDATE_MODELS))
    parser.add_argument("--workloads", nargs="+", choices=list(WORKLOADS), default=list(WORKLOADS))
    parser.add_argument("--variant", default="base")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--warmup-seconds", type=float, default=30.0)
    parser.add_argument("--window-seconds", type=float, default=60.0)
    parser.add_argument("--max-num-seqs", type=int)
    parser.add_argument("--max-num-batched-tokens", type=int)
    parser.add_argument("--server-argument", action="append", default=[], help="extra vllm serve argument")
    arguments = parser.parse_args()
    match arguments.mode:
        case "sweep":
            asyncio.run(run_sweep(arguments))
        case "adapter":
            asyncio.run(run_adapter_comparison(arguments))
        case "summarize":
            write_summary()


if __name__ == "__main__":
    main()
