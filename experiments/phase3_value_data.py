"""Build a value data set from traced proofs: every state on a proof with its remaining steps (an upper bound).

    python experiments/phase3_value_data.py --name v0 [--traced-directory DIR] [--tokenizer Qwen/Qwen3.5-2B]

Train and validation follow the traced split (by canonical statement). Within a split, states with the same
normalized goals keep the fewest remaining steps; validation states that also occur in train are dropped. Reads every
finished shard (shards are written atomically), so re-running on the same shards rebuilds the same files. Writes
$LEAN_SEARCH_DATA/value/<name>/{train,validation}.jsonl and summary.json, and the statistics to
$LEAN_SEARCH_RUNS/phase3_value_data_<name>/summary/{summary.json,README.md}.
"""

import argparse
import dataclasses
import datetime
import json
import os
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.corpora.records import DataSplit, read_traced_steps
from lean_search.search.summary import markdown_table
from lean_search.training.sft_data import LengthStatistics, length_statistics
from lean_search.value.bins import STEP_BIN_COUNT
from lean_search.value.labels import (
    LabelCounts,
    ValueExample,
    label_counts,
    merge_duplicates,
    traced_examples,
    write_examples,
)
from lean_search.value.prompts import render_value_prompt

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
MAX_PROMPT_TOKENS = 2048
TOKENIZATION_BATCH = 1024


@dataclass(frozen=True)
class ShardFile:
    path: str
    steps: int


@dataclass(frozen=True)
class SplitStatistics:
    traced_steps: int
    proofs: int
    states: int
    duplicate_steps: int
    # States seen with different remaining counts; the fewest is kept.
    conflicting_states: int
    mean_conflict_spread: float
    dropped_in_train: int
    labels: LabelCounts
    remaining_steps: LengthStatistics
    mean_remaining_steps_eight_or_more: float
    prompt_tokens: LengthStatistics
    prompts_over_max: int
    states_by_source: dict[str, int]


@dataclass(frozen=True)
class ValueDataSummary:
    name: str
    built: str
    git_revision: str
    traced_directory: str
    tokenizer: str
    max_prompt_tokens: int
    shards: tuple[ShardFile, ...]
    seconds: float
    train: SplitStatistics
    validation: SplitStatistics


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help=f"output directory name under {DATA_DIRECTORY / 'value'}")
    parser.add_argument("--traced-directory", type=Path, default=DATA_DIRECTORY / "traced")
    parser.add_argument("--tokenizer", default="Qwen/Qwen3.5-2B", help="for prompt-length statistics only")
    return parser.parse_args()


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def prompt_token_counts(tokenizer: transformers.PreTrainedTokenizerBase, examples: Sequence[ValueExample]) -> list[int]:
    counts: list[int] = []
    for start in range(0, len(examples), TOKENIZATION_BATCH):
        prompts = [
            render_value_prompt(tokenizer, example.goals) for example in examples[start : start + TOKENIZATION_BATCH]
        ]
        counts.extend(len(ids) for ids in tokenizer(prompts, add_special_tokens=False)["input_ids"])
    return counts


def split_statistics(
    traced: Sequence[ValueExample],
    states: Sequence[ValueExample],
    dropped_in_train: int,
    prompt_tokens: Sequence[int],
) -> SplitStatistics:
    remaining_by_key: defaultdict[tuple[str, ...], set[int]] = defaultdict(set)
    for example in traced:
        remaining_by_key[example.goal_key].add(example.steps)
    spreads = [max(remaining) - min(remaining) for remaining in remaining_by_key.values() if len(remaining) > 1]
    long_remaining = [example.steps for example in states if example.steps >= STEP_BIN_COUNT]
    return SplitStatistics(
        traced_steps=len(traced),
        proofs=len({example.identifier for example in traced}),
        states=len(states),
        duplicate_steps=len(traced) - len(remaining_by_key),
        conflicting_states=len(spreads),
        mean_conflict_spread=sum(spreads) / len(spreads) if spreads else 0.0,
        dropped_in_train=dropped_in_train,
        labels=label_counts(states),
        remaining_steps=length_statistics([example.steps for example in states]),
        mean_remaining_steps_eight_or_more=sum(long_remaining) / len(long_remaining) if long_remaining else 0.0,
        prompt_tokens=length_statistics(prompt_tokens),
        prompts_over_max=sum(count > MAX_PROMPT_TOKENS for count in prompt_tokens),
        states_by_source=dict(sorted(Counter(example.source for example in states).items())),
    )


def render_markdown(summary: ValueDataSummary) -> str:
    splits = {"train": summary.train, "validation": summary.validation}
    overview = [
        [
            name,
            f"{statistics.traced_steps:,}",
            f"{statistics.proofs:,}",
            f"{statistics.duplicate_steps:,}",
            f"{statistics.conflicting_states:,}",
            f"{statistics.mean_conflict_spread:.2f}",
            f"{statistics.dropped_in_train:,}",
            f"{statistics.states:,}",
        ]
        for name, statistics in splits.items()
    ]
    bin_names = [str(steps) for steps in range(1, STEP_BIN_COUNT)] + [f"{STEP_BIN_COUNT}+"]
    bins = [
        [name, *(f"{count:,} ({count / statistics.states:.1%})" for count in statistics.labels.exact_bins)]
        for name, statistics in splits.items()
    ]
    lengths = [
        [
            f"{name} {quantity}",
            f"{values.mean:.1f}",
            values.p50,
            values.p90,
            values.p99,
            values.maximum,
        ]
        for name, statistics in splits.items()
        for quantity, values in (
            ("remaining steps", statistics.remaining_steps),
            ("prompt tokens", statistics.prompt_tokens),
        )
    ]
    sources = sorted(set(summary.train.states_by_source) | set(summary.validation.states_by_source))
    by_source = [
        [
            source,
            f"{summary.train.states_by_source.get(source, 0):,}",
            f"{summary.validation.states_by_source.get(source, 0):,}",
        ]
        for source in sources
    ]
    shard_steps = sum(shard.steps for shard in summary.shards)
    sections = [
        f"# Value data set `{summary.name}`",
        f"Built {summary.built} by `experiments/phase3_value_data.py` (git {summary.git_revision[:10]}) from "
        f"{len(summary.shards)} finished tracing shards ({shard_steps:,} traced steps) in "
        f"`{summary.traced_directory}`, {summary.seconds:.0f} s. One example per state on a traced complete proof, "
        "labelled with its remaining steps (an upper bound: the proof's own length from there). Train and validation "
        "follow the traced split (by canonical statement). States with the same normalized goals keep the fewest "
        "remaining steps; validation states that also occur in train are dropped. Token counts are prompt tokens of "
        f"`{summary.tokenizer}` with the value prompt; training drops prompts over {summary.max_prompt_tokens:,} "
        "tokens.",
        markdown_table(
            [
                "Split",
                "Traced steps",
                "Proofs",
                "Duplicate steps",
                "States with conflicting counts",
                "Mean spread of conflicts",
                "Dropped (in train)",
                "States",
            ],
            overview,
        ),
        "## Remaining-step bins",
        markdown_table(["Split", *bin_names], bins),
        f"Mean remaining steps of the {STEP_BIN_COUNT}+ states: train "
        f"{summary.train.mean_remaining_steps_eight_or_more:.1f}, validation "
        f"{summary.validation.mean_remaining_steps_eight_or_more:.1f}. Prompts over {summary.max_prompt_tokens:,} "
        f"tokens: train {summary.train.prompts_over_max:,}, validation {summary.validation.prompts_over_max:,}.",
        "## Distributions",
        markdown_table(["Quantity", "Mean", "p50", "p90", "p99", "Max"], lengths),
        "## States by source",
        markdown_table(["Source", "Train", "Validation"], by_source),
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    start = time.perf_counter()
    shard_paths = sorted(arguments.traced_directory.glob("shards/*/*.steps.jsonl"))
    shards: list[ShardFile] = []
    traced_by_split: dict[DataSplit, list[ValueExample]] = {DataSplit.TRAIN: [], DataSplit.VALIDATION: []}
    for path in shard_paths:
        shard_steps = list(read_traced_steps(path))
        shards.append(ShardFile(str(path.relative_to(arguments.traced_directory)), len(shard_steps)))
        for step, example in zip(shard_steps, traced_examples(shard_steps), strict=True):
            traced_by_split[step.split].append(example)
    print(f"Read {sum(shard.steps for shard in shards):,} steps from {len(shards)} shards", flush=True)
    train = merge_duplicates(traced_by_split[DataSplit.TRAIN])
    train_keys = {example.goal_key for example in train}
    validation_merged = merge_duplicates(traced_by_split[DataSplit.VALIDATION])
    validation = [example for example in validation_merged if example.goal_key not in train_keys]
    tokenizer = transformers.AutoTokenizer.from_pretrained(arguments.tokenizer)
    train_tokens = prompt_token_counts(tokenizer, train)
    validation_tokens = prompt_token_counts(tokenizer, validation)
    output_directory = DATA_DIRECTORY / "value" / arguments.name
    write_examples(output_directory / "train.jsonl", train)
    write_examples(output_directory / "validation.jsonl", validation)
    summary = ValueDataSummary(
        name=arguments.name,
        built=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=git_revision(),
        traced_directory=str(arguments.traced_directory),
        tokenizer=arguments.tokenizer,
        max_prompt_tokens=MAX_PROMPT_TOKENS,
        shards=tuple(shards),
        seconds=time.perf_counter() - start,
        train=split_statistics(traced_by_split[DataSplit.TRAIN], train, 0, train_tokens),
        validation=split_statistics(
            traced_by_split[DataSplit.VALIDATION],
            validation,
            len(validation_merged) - len(validation),
            validation_tokens,
        ),
    )
    summary_json = json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False)
    markdown = render_markdown(summary)
    (output_directory / "summary.json").write_text(summary_json, encoding="utf-8")
    summary_directory = RUNS_DIRECTORY / f"phase3_value_data_{arguments.name}" / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.json").write_text(summary_json, encoding="utf-8")
    (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
