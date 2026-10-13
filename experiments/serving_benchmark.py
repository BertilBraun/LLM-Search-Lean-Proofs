"""Closed-loop load on running policy and value servers that mimics a search's request mix, with GPU sampling.

    python experiments/serving_benchmark.py --trees $LEAN_SEARCH_RUNS/phase3_astar_v0_sft_v2/trees \
        --policy-url http://127.0.0.1:8100/v1 --policy-url http://127.0.0.1:8101/v1 --policy-model policy-merged \
        --value-url http://127.0.0.1:8200/v1 --value-url http://127.0.0.1:8201/v1 --value-model value-merged \
        --workers 64 --duration 240 --warmup 60 [--thinking --sample-count 8 --max-tokens 512]

Each worker repeats one expansion's GPU work on a real tree state: a policy request (n samples), then one value
request scoring `--value-states` states. Tokens finished between `--warmup` and `--duration` seconds count.
"""

import argparse
import asyncio
import dataclasses
import itertools
import json
import time
from pathlib import Path

import pynvml

from lean_search.policy.client import PolicyClient
from lean_search.policy.expander import load_tokenizer
from lean_search.policy.prompts import render_prompt, stop_sequences
from lean_search.search import read_tree
from lean_search.value.prompts import render_value_prompt


@dataclasses.dataclass
class Counters:
    policy_requests: int = 0
    generated_tokens: int = 0
    truncated_samples: int = 0
    samples: int = 0
    value_requests: int = 0
    value_prompt_tokens: int = 0


@dataclasses.dataclass(frozen=True)
class BenchmarkResult:
    workers: int
    seconds: float
    generated_tokens_per_second: float
    samples_per_second: float
    policy_requests_per_second: float
    mean_tokens_per_sample: float
    truncated_share: float
    value_prompt_tokens_per_second: float
    gpu_utilization: tuple[float, ...]
    gpu_power_watts: tuple[float, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", type=Path, required=True)
    parser.add_argument("--tokenizer", default="Qwen/Qwen3.5-2B")
    parser.add_argument("--policy-url", action="append", required=True)
    parser.add_argument("--policy-model", required=True)
    parser.add_argument("--value-url", action="append", default=[])
    parser.add_argument("--value-model", default="")
    parser.add_argument("--workers", type=int, default=64)
    parser.add_argument("--duration", type=float, default=240.0)
    parser.add_argument("--warmup", type=float, default=60.0)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--value-states", type=int, default=8)
    return parser.parse_args()


def tree_states(trees: Path) -> list[tuple[str, ...]]:
    states = (node.goals for path in sorted(trees.glob("*.json.gz"))[:80] for node in read_tree(path).nodes)
    return [goals for goals in dict.fromkeys(states) if goals]


async def run(arguments: argparse.Namespace) -> BenchmarkResult:
    tokenizer = load_tokenizer(arguments.tokenizer)
    states = tree_states(arguments.trees)
    policy_prompts = itertools.cycle([render_prompt(tokenizer, goals, thinking=arguments.thinking) for goals in states])
    value_prompts = itertools.cycle([render_value_prompt(tokenizer, goals) for goals in states])
    policy_clients = itertools.cycle([PolicyClient(url, arguments.policy_model) for url in arguments.policy_url])
    value_clients = itertools.cycle([PolicyClient(url, arguments.value_model) for url in arguments.value_url])
    counters = Counters()
    started = time.monotonic()

    def counting() -> bool:
        return arguments.warmup <= time.monotonic() - started <= arguments.duration

    async def worker() -> None:
        while time.monotonic() - started < arguments.duration:
            generation = await next(policy_clients).generate(
                next(policy_prompts),
                sample_count=arguments.sample_count,
                max_tokens=arguments.max_tokens,
                temperature=arguments.temperature,
                stop=stop_sequences(arguments.thinking),
            )
            if counting():
                counters.policy_requests += 1
                counters.generated_tokens += generation.completion_token_count
                counters.samples += len(generation.samples)
                counters.truncated_samples += sum(sample.finish_reason == "length" for sample in generation.samples)
            if arguments.value_url:
                scored = await next(value_clients).score_next_tokens(
                    [next(value_prompts) for _ in range(arguments.value_states)]
                )
                if counting():
                    counters.value_requests += 1
                    counters.value_prompt_tokens += scored.prompt_token_count

    pynvml.nvmlInit()
    handles = [pynvml.nvmlDeviceGetHandleByIndex(index) for index in range(pynvml.nvmlDeviceGetCount())]
    utilization: list[list[int]] = [[] for _ in handles]
    power: list[list[float]] = [[] for _ in handles]

    async def sample_gpus() -> None:
        while time.monotonic() - started < arguments.duration:
            if counting():
                for index, handle in enumerate(handles):
                    utilization[index].append(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
                    power[index].append(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000)
            await asyncio.sleep(1.0)

    await asyncio.gather(sample_gpus(), *(worker() for _ in range(arguments.workers)))
    seconds = arguments.duration - arguments.warmup
    return BenchmarkResult(
        workers=arguments.workers,
        seconds=seconds,
        generated_tokens_per_second=counters.generated_tokens / seconds,
        samples_per_second=counters.samples / seconds,
        policy_requests_per_second=counters.policy_requests / seconds,
        mean_tokens_per_sample=counters.generated_tokens / max(1, counters.samples),
        truncated_share=counters.truncated_samples / max(1, counters.samples),
        value_prompt_tokens_per_second=counters.value_prompt_tokens / seconds,
        gpu_utilization=tuple(sum(values) / max(1, len(values)) for values in utilization),
        gpu_power_watts=tuple(sum(values) / max(1, len(values)) for values in power),
    )


def main() -> None:
    result = asyncio.run(run(parse_arguments()))
    print(json.dumps(dataclasses.asdict(result), indent=1))


if __name__ == "__main__":
    main()
