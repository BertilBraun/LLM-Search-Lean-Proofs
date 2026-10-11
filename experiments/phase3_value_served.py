"""Score held-out value states through the served value adapter and compute the validation metrics.

    python experiments/phase3_value_served.py --run-name phase3_value_v0 --data v0 --model search-qwen3.5-2b \
        --tokenizer Qwen/Qwen3.5-2B --adapter value-v0 --server-urls http://127.0.0.1:8100/v1

Checks that serving (vLLM's top-k logprobs, renormalized over the bin tokens) reproduces the training-time
evaluation, on the same states (prompts of at most --max-prompt-tokens tokens). Writes
$LEAN_SEARCH_RUNS/<run-name>/summary/served.{json,md}.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from lean_search.search.summary import markdown_table
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import ValueModelEstimator, ValueStatistics, open_value_estimator
from lean_search.value.labels import ValueExample, read_examples
from lean_search.value.metrics import ValueMetrics, value_metrics
from lean_search.value.prompts import render_value_prompt

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "value"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CONCURRENT_REQUESTS = 128


@dataclass(frozen=True)
class ServedEvaluation:
    adapter: str
    server_urls: tuple[str, ...]
    examples: int
    seconds: float
    metrics: ValueMetrics
    mean_h: float
    statistics: ValueStatistics


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--server-urls", nargs="+", required=True)
    parser.add_argument("--max-prompt-tokens", type=int, default=2048)
    return parser.parse_args()


async def score_all(estimator: ValueModelEstimator, examples: list[ValueExample]) -> list[tuple[float, ...]]:
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    async def score(example: ValueExample) -> tuple[float, ...]:
        async with semaphore:
            return (await estimator.score(example.goals)).probabilities

    return list(await asyncio.gather(*(score(example) for example in examples)))


async def evaluate(arguments: argparse.Namespace) -> ServedEvaluation:
    config = ValueConfig(
        model=arguments.model,
        tokenizer=arguments.tokenizer,
        server_urls=tuple(arguments.server_urls),
        adapter=arguments.adapter,
    )
    async with open_value_estimator(config) as estimator:
        tokenizer = estimator.tokenizer
        examples = [
            example
            for example in read_examples(DATA_DIRECTORY / arguments.data / "validation.jsonl")
            if len(tokenizer.encode(render_value_prompt(tokenizer, example.goals), add_special_tokens=False))
            <= arguments.max_prompt_tokens
        ]
        started = time.perf_counter()
        distributions = await score_all(estimator, examples)
        seconds = time.perf_counter() - started
        readout = config.readout
        return ServedEvaluation(
            adapter=arguments.adapter,
            server_urls=config.server_urls,
            examples=len(examples),
            seconds=seconds,
            metrics=value_metrics(distributions, examples, readout),
            mean_h=sum(readout.remaining_steps(distribution) for distribution in distributions) / len(examples),
            statistics=estimator.statistics,
        )


def render(evaluation: ServedEvaluation) -> str:
    metrics = evaluation.metrics
    statistics = evaluation.statistics
    rows = [
        ["States", f"{evaluation.examples:,}"],
        ["Bin accuracy", f"{metrics.bin_accuracy:.1%}"],
        ["MAE (alive)", f"{metrics.alive_mean_absolute_error:.3f}"],
        ["Spearman", f"{metrics.spearman:.3f}"],
        ["Mean h", f"{evaluation.mean_h:.2f}"],
        ["Bin tokens outside the top-k per request", f"{statistics.missing_bin_tokens / statistics.requests:.2f}"],
        ["Prompts too long", statistics.prompts_too_long],
        ["States/s", f"{evaluation.examples / evaluation.seconds:.0f}"],
        ["Mean request seconds", f"{statistics.request_seconds / statistics.requests:.3f}"],
        ["Prompt cache hit rate", f"{statistics.cached_prompt_tokens / statistics.prompt_tokens:.1%}"],
    ]
    return (
        "\n\n".join(
            [
                f"# Served value adapter `{evaluation.adapter}`",
                f"Held-out states scored through vLLM ({len(evaluation.server_urls)} server(s)), read out as the "
                "search does: top-k logprobs renormalized over the nine bin tokens.",
                markdown_table(["Quantity", "Value"], rows),
            ]
        )
        + "\n"
    )


def main() -> None:
    arguments = parse_arguments()
    evaluation = asyncio.run(evaluate(arguments))
    summary = RUNS_DIRECTORY / arguments.run_name / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    (summary / "served.json").write_text(
        json.dumps(dataclasses.asdict(evaluation), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render(evaluation)
    (summary / "served.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
