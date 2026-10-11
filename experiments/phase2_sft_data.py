"""Build an SFT data set from traced proof steps: source mixture, length caps, de-duplication, token statistics."""

import argparse
import dataclasses
import datetime
import json
import os
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft_data import (
    LengthStatistics,
    SftDataConfig,
    SourceStatistics,
    SourceStream,
    TokenizedExample,
    deduplicate,
    length_capped_tokenizer,
    length_statistics,
    ordering_key,
    read_traced_examples,
    select_mixture,
    select_validation,
    source_statistics,
    write_examples,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase2_sft_data"


@dataclass(frozen=True)
class SelectionStatistics:
    examples: int
    prompt_tokens: LengthStatistics
    completion_tokens: LengthStatistics
    total_tokens: LengthStatistics
    examples_by_source: dict[str, int]


@dataclass(frozen=True)
class DataSummary:
    name: str
    built: str
    git_revision: str
    traced_directory: str
    shard_files: int
    seconds: float
    config: SftDataConfig
    sources: tuple[SourceStatistics, ...]
    train: SelectionStatistics
    validation_traced_steps: int
    validation_duplicates: int
    validation: SelectionStatistics


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True, help=f"output directory name under {DATA_DIRECTORY / 'sft'}")
    parser.add_argument("--traced-directory", type=Path, default=DATA_DIRECTORY / "traced")
    return parser.parse_args()


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def selection_statistics(examples: list[TokenizedExample]) -> SelectionStatistics:
    by_source: dict[str, int] = {}
    for example in examples:
        by_source[example.example.source] = by_source.get(example.example.source, 0) + 1
    return SelectionStatistics(
        examples=len(examples),
        prompt_tokens=length_statistics([example.prompt_token_count for example in examples]),
        completion_tokens=length_statistics([example.completion_token_count for example in examples]),
        total_tokens=length_statistics([example.token_count for example in examples]),
        examples_by_source=by_source,
    )


def length_cells(statistics: LengthStatistics) -> list[str]:
    return [
        f"{statistics.mean:.0f}",
        str(statistics.p50),
        str(statistics.p90),
        str(statistics.p99),
        str(statistics.maximum),
    ]


def render_markdown(summary: DataSummary) -> str:
    config = summary.config
    total_tokens = sum(source.total_tokens for source in summary.sources)
    weights = {source.name: source.weight for source in config.sources}
    source_rows = [
        [
            source.source,
            f"{weights[source.source]:g}",
            f"{source.traced_steps:,}",
            f"{source.forbidden_steps:,}",
            f"{source.duplicates:,}",
            f"{source.examined:,}",
            f"{source.over_length:,}",
            f"{source.selected:,}",
            f"{source.total_tokens:,}",
            f"{source.total_tokens / max(1, total_tokens):.1%}",
        ]
        for source in summary.sources
    ]
    length_rows = []
    for name, statistics in (("train", summary.train), ("validation", summary.validation)):
        for kind, length in (
            ("prompt", statistics.prompt_tokens),
            ("completion", statistics.completion_tokens),
            ("total", statistics.total_tokens),
        ):
            length_rows.append([name, kind, f"{length.count:,}", f"{length.total:,}", *length_cells(length)])
    per_source_rows = [
        [
            source.source,
            *length_cells(source.prompt_tokens),
            *length_cells(source.completion_tokens),
        ]
        for source in summary.sources
    ]
    budget = f"{config.token_budget:,} tokens" if config.token_budget else "everything"
    validation_sources = ", ".join(
        f"{source}: {count:,}" for source, count in sorted(summary.validation.examples_by_source.items())
    )
    sections = [
        f"# SFT data `{summary.name}`",
        f"Built {summary.built} from {summary.shard_files} shard files in `{summary.traced_directory}` "
        f"(git {summary.git_revision[:10]}, {summary.seconds:.0f} s). Budget {budget} of "
        f"`{config.reference_tokenizer}` tokens (prompt + completion), caps {config.max_prompt_tokens} prompt "
        f"and {config.max_completion_tokens} completion tokens, seed `{config.seed}`. Each example is one traced "
        "train-split step: the goals before it rendered with the policy prompt (no lemmas, thinking off, "
        "prefilled fence) and the step as the completion. Steps with forbidden tokens are dropped, identical "
        "(goals, step) pairs are kept once, and each source is filled in a fixed pseudo-random order up to its "
        "weighted share of the budget; the shares of exhausted sources go to the others.",
        markdown_table(
            [
                "Source",
                "Weight",
                "Traced train steps",
                "Forbidden",
                "Duplicates",
                "Examined",
                "Over length",
                "Selected",
                "Tokens",
                "Share",
            ],
            source_rows,
        ),
        "## Token lengths",
        markdown_table(["Split", "Part", "Examples", "Tokens", "Mean", "p50", "p90", "p99", "Max"], length_rows),
        markdown_table(
            [
                "Source",
                "Prompt mean",
                "p50",
                "p90",
                "p99",
                "Max",
                "Completion mean",
                "p50",
                "p90",
                "p99",
                "Max",
            ],
            per_source_rows,
        ),
        f"Validation: {summary.validation.examples:,} examples from {summary.validation_traced_steps:,} traced "
        f"validation-split steps (statements held out by hash) after dropping {summary.validation_duplicates:,} "
        f"duplicates or pairs also present in train; by source: {validation_sources}.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    start = time.perf_counter()
    config = from_json_object(SftDataConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    weights = {source.name: source.weight for source in config.sources}
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.reference_tokenizer)
    traced = read_traced_examples(arguments.traced_directory, weights)
    print(f"Read traced steps in {time.perf_counter() - start:.0f} s", flush=True)
    pool = deduplicate(traced.train, config.seed)
    tokenize = length_capped_tokenizer(tokenizer, config.max_prompt_tokens, config.max_completion_tokens)
    streams = {source: SourceStream(pool.examples_by_source[source], tokenize) for source in weights}
    select_mixture(streams, weights, config.token_budget)
    validation_pool = deduplicate(traced.validation, config.seed, excluded_keys=pool.keys)
    validation = select_validation(
        validation_pool.examples_by_source, config.validation_examples, config.seed, tokenize
    )
    train = sorted(
        (example for stream in streams.values() for example in stream.accepted),
        key=lambda example: ordering_key(example.example, config.seed),
    )
    output_directory = DATA_DIRECTORY / "sft" / arguments.name
    write_examples(output_directory / "train.jsonl", (example.example for example in train))
    write_examples(output_directory / "validation.jsonl", (example.example for example in validation))
    summary = DataSummary(
        name=arguments.name,
        built=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=git_revision(),
        traced_directory=str(arguments.traced_directory),
        shard_files=len(list(arguments.traced_directory.glob("shards/*/*.steps.jsonl"))),
        seconds=time.perf_counter() - start,
        config=config,
        sources=tuple(source_statistics(source, traced, pool, streams[source]) for source in weights),
        train=selection_statistics(train),
        validation_traced_steps=sum(len(examples) for examples in traced.validation.values()),
        validation_duplicates=sum(validation_pool.duplicates_by_source.values()),
        validation=selection_statistics(validation),
    )
    summary_json = json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False)
    markdown = render_markdown(summary)
    (output_directory / "summary.json").write_text(summary_json, encoding="utf-8")
    (RUN_DIRECTORY / "summary").mkdir(parents=True, exist_ok=True)
    (RUN_DIRECTORY / "summary" / f"{arguments.name}.json").write_text(summary_json, encoding="utf-8")
    (RUN_DIRECTORY / "summary" / f"{arguments.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
