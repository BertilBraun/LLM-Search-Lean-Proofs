"""Score labelled states through the served value adapter: held-out traced states or the nodes of a run's trees.

    python experiments/phase3_value_served.py --run-name phase3_value_v0 --data v0 --model search-qwen3.5-2b \
        --tokenizer Qwen/Qwen3.5-2B --adapter value-v0 --server-urls http://127.0.0.1:8100/v1
    python experiments/phase3_value_served.py --run-name phase3_astar_v0 --trees-run phase2_sft_v1_search ...

Held-out states check that serving (vLLM's top-k logprobs, renormalized over the bin tokens) reproduces the
training-time evaluation on the same states (prompts of at most --max-prompt-tokens tokens). Tree nodes, labelled
by the tree labeler, give the value model's calibration on states a search reached; miniF2F trees are only scored,
never trained on. Writes $LEAN_SEARCH_RUNS/<run-name>/summary/served_<source>.{json,md}.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from lean_search.search import read_tree
from lean_search.search.summary import markdown_table
from lean_search.value.bins import DEAD_BIN
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import ValueModelEstimator, ValueStatistics, open_value_estimator
from lean_search.value.labels import (
    LABEL_GROUPS,
    TreeLabelConfig,
    ValueExample,
    label_group,
    read_examples,
    tree_examples,
)
from lean_search.value.metrics import ValueMetrics, value_metrics
from lean_search.value.prompts import render_value_prompt

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "value"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CONCURRENT_REQUESTS = 128


@dataclass(frozen=True)
class GroupScores:
    label: str
    states: int
    mean_h: float
    median_h: float
    mean_dead_probability: float


@dataclass(frozen=True)
class ServedEvaluation:
    source: str
    adapter: str
    server_urls: tuple[str, ...]
    examples: int
    seconds: float
    metrics: ValueMetrics
    mean_h: float
    mean_dead_probability: float
    groups: tuple[GroupScores, ...]
    statistics: ValueStatistics


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", help="a value data set: its validation split")
    source.add_argument("--trees-run", help="a search run: every labelled node of its trees")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--server-urls", nargs="+", required=True)
    parser.add_argument("--max-prompt-tokens", type=int, default=2048)
    return parser.parse_args()


def source_name(arguments: argparse.Namespace) -> str:
    return f"validation_{arguments.data}" if arguments.data else f"trees_{arguments.trees_run}"


def labelled_examples(arguments: argparse.Namespace) -> list[ValueExample]:
    if arguments.data:
        return list(read_examples(DATA_DIRECTORY / arguments.data / "validation.jsonl"))
    paths = sorted((RUNS_DIRECTORY / arguments.trees_run / "trees").glob("*.json.gz"))
    return [
        example for path in paths for example in tree_examples(read_tree(path), arguments.trees_run, TreeLabelConfig())
    ]


async def score_all(estimator: ValueModelEstimator, examples: list[ValueExample]) -> list[tuple[float, ...]]:
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    async def score(example: ValueExample) -> tuple[float, ...]:
        async with semaphore:
            return (await estimator.score(example.goals)).probabilities

    return list(await asyncio.gather(*(score(example) for example in examples)))


def group_scores(
    examples: list[ValueExample], distributions: list[tuple[float, ...]], config: ValueConfig
) -> tuple[GroupScores, ...]:
    groups = []
    for label in LABEL_GROUPS:
        members = [
            distribution
            for example, distribution in zip(examples, distributions, strict=True)
            if label_group(example) == label
        ]
        if members:
            steps = [config.readout.remaining_steps(distribution) for distribution in members]
            groups.append(
                GroupScores(
                    label,
                    len(members),
                    statistics.fmean(steps),
                    statistics.median(steps),
                    statistics.fmean(distribution[DEAD_BIN] for distribution in members),
                )
            )
    return tuple(groups)


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
            for example in labelled_examples(arguments)
            if len(tokenizer.encode(render_value_prompt(tokenizer, example.goals), add_special_tokens=False))
            <= arguments.max_prompt_tokens
        ]
        started = time.perf_counter()
        distributions = await score_all(estimator, examples)
        seconds = time.perf_counter() - started
    return ServedEvaluation(
        source=source_name(arguments),
        adapter=arguments.adapter,
        server_urls=config.server_urls,
        examples=len(examples),
        seconds=seconds,
        metrics=value_metrics(distributions, examples, config.readout),
        mean_h=statistics.fmean(config.readout.remaining_steps(distribution) for distribution in distributions),
        mean_dead_probability=statistics.fmean(distribution[DEAD_BIN] for distribution in distributions),
        groups=group_scores(examples, distributions, config),
        statistics=estimator.statistics,
    )


def optional(value: float | None, format_specification: str) -> str:
    return "–" if value is None else format(value, format_specification)


def render(evaluation: ServedEvaluation) -> str:
    metrics = evaluation.metrics
    served = evaluation.statistics
    rows = [
        ["States", f"{evaluation.examples:,}"],
        ["Bin accuracy (exact and dead labels)", optional(metrics.bin_accuracy, ".1%")],
        ["MAE of expected steps given alive (exact labels)", optional(metrics.alive_mean_absolute_error, ".3f")],
        ["Spearman of h with exact remaining steps", optional(metrics.spearman, ".3f")],
        ["Dead AUC of p_dead (dead vs exact)", optional(metrics.dead_auc, ".3f")],
        ["Mean P(at least n or dead) on censored labels", optional(metrics.at_least_probability, ".3f")],
        ["Mean h / mean p_dead", f"{evaluation.mean_h:.2f} / {evaluation.mean_dead_probability:.2e}"],
        ["Bin tokens outside the top-k per request", f"{served.missing_bin_tokens / served.requests:.2f}"],
        ["Prompts too long", served.prompts_too_long],
        ["States/s", f"{evaluation.examples / evaluation.seconds:.0f}"],
        ["Mean request seconds", f"{served.request_seconds / served.requests:.3f}"],
        ["Prompt cache hit rate", f"{served.cached_prompt_tokens / served.prompt_tokens:.1%}"],
    ]
    groups = [
        [
            group.label,
            f"{group.states:,}",
            f"{group.mean_h:.2f}",
            f"{group.median_h:.2f}",
            f"{group.mean_dead_probability:.2e}",
        ]
        for group in evaluation.groups
    ]
    sections = [
        f"# Served value adapter `{evaluation.adapter}` on `{evaluation.source}`",
        f"Scored through vLLM ({len(evaluation.server_urls)} server(s)) and read out as the search does: top-k "
        "logprobs renormalized over the nine bin tokens, h = Σ p_k·steps_k.",
        markdown_table(["Quantity", "Value"], rows),
        "## By label",
        markdown_table(["Label", "States", "Mean h", "Median h", "Mean p_dead"], groups),
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    evaluation = asyncio.run(evaluate(arguments))
    summary = RUNS_DIRECTORY / arguments.run_name / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    name = f"served_{evaluation.source}"
    (summary / f"{name}.json").write_text(
        json.dumps(dataclasses.asdict(evaluation), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render(evaluation)
    (summary / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
