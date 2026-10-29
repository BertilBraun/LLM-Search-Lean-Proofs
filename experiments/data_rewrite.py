"""Rewritten SFT data for the gentle fine-tune before GRPO: flat proofs in chunks of mixed length, flattened reasoning
examples, numbered and descriptive hypothesis names (the naming A/B).

    python experiments/data_rewrite.py rewrite \
        --config experiments/configs/data_rewrite/rewrite_visible_student_v2.toml \
        --run-name data_rewrite_v1            # the Lean pass, resumable by shard; ends with the summary
    python experiments/data_rewrite.py explain --config experiments/configs/data_rewrite/explain_chunks.toml \
        --build-config experiments/configs/data_rewrite/build_named.toml   # the teacher, resumable by shard
    python experiments/data_rewrite.py summary --run-name data_rewrite_v1
    python experiments/data_rewrite.py build --config experiments/configs/data_rewrite/build_numbered.toml \
        --name visible_student_v3_numbered    # and build_named.toml --name visible_student_v3_named

`rewrite` flattens each selected proof (`flatten_proof`), replays it step by step (nested proofs must keep to their
goal), renames its numbered hypotheses (namer: the configured model, rule-based fallback) and replays the renamed
proof; the reasoning examples' blocks get the same treatment on their rebuilt states. Records in
$LEAN_SEARCH_RUNS/<run>/{proofs,examples}/<shard>.jsonl, the summary (kept and dropped per reason) in
$LEAN_SEARCH_RUNS/<run>/summary/. `explain` plans the build's chunks (either build config: both plan the same) and has
the served namer model write a visible-mode explanation for each chunk planned for the visible mode, into
$LEAN_SEARCH_RUNS/<run>/explanations/<shard>.jsonl. `build` writes
$LEAN_SEARCH_DATA/reasoning/<name>/{train,validation,math}.jsonl (the format phase5_reasoning_sft.py trains on) plus
chunks_{train,validation}.jsonl with the chunks' end states and explanations.
"""

import argparse
import asyncio
import dataclasses
import json
import os
import shutil
import time
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import transformers

from lean_search.corpora.records import read_proof_records
from lean_search.data_rewrite.dataset import (
    BuildConfig,
    BuiltData,
    ChunkPosition,
    TokenCounts,
    build_data,
    chunk_training_example,
    plan_chunks,
)
from lean_search.data_rewrite.explanations import (
    ExplainConfig,
    explain_chunks,
    explanation_request,
    few_shot_explanations,
    open_teacher,
)
from lean_search.data_rewrite.model_namer import open_namer
from lean_search.data_rewrite.records import ChunkExplanation, ExplanationOutcome
from lean_search.data_rewrite.rewrite import (
    RewriteConfig,
    RewriteDirectory,
    RewriteRun,
    read_states,
    reasoning_items,
    run_rewrite,
    select_proofs,
)
from lean_search.data_rewrite.statistics import (
    TokenStatistics,
    build_summary,
    render_build_summary,
    render_rewrite_summary,
    rewrite_summary,
)
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.identifiers import environment_names
from lean_search.policy.prompts import render_completion, render_prompt
from lean_search.reasoning.dataset import ReasoningExample, read_examples, tokenize_reasoning_example, write_examples
from lean_search.reasoning.records import write_records
from lean_search.search.records import from_json_object
from lean_search.training.sft_data import length_statistics
from lean_search.training.sft_data import read_examples as read_sft_examples

DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
COMMAND_TIMEOUT_SECONDS = 120.0


def keep_config(path: Path, directory: Path) -> None:
    text = path.read_text(encoding="utf-8")
    kept = directory / "config.toml"
    if kept.exists() and kept.read_text(encoding="utf-8") != text:
        raise ValueError(f"{kept} differs from {path}; a run keeps one configuration.")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")


def load_rewrite_config(path: Path) -> RewriteConfig:
    return from_json_object(RewriteConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def load_build_config(path: Path) -> BuildConfig:
    return from_json_object(BuildConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def reasoning_examples(name: str, split: str) -> list[ReasoningExample]:
    path = DATA_DIRECTORY / "reasoning" / name / f"{split}.jsonl"
    return list(read_examples(path)) if path.exists() else []


def most_common_header(headers: list[str]) -> str:
    return Counter(headers).most_common(1)[0][0]


def token_counts(tokenizer: transformers.PreTrainedTokenizerBase) -> TokenCounts:
    prompt_tokens: dict[tuple[str, ...], int] = {}

    def count_prompt(goals: tuple[str, ...]) -> int:
        if goals not in prompt_tokens:
            prompt_tokens[goals] = len(tokenizer.encode(render_prompt(tokenizer, goals), add_special_tokens=False))
        return prompt_tokens[goals]

    def count_completion(block: str) -> int:
        return len(tokenizer.encode(render_completion(block), add_special_tokens=False))

    return TokenCounts(count_prompt, count_completion)


async def rewrite(arguments: argparse.Namespace, config: RewriteConfig, directory: RewriteDirectory) -> None:
    identifiers = (
        frozenset(
            example.proof_identifier
            for name in config.proof_data
            for split in ("train", "validation")
            for example in read_sft_examples(DATA_DIRECTORY / "sft" / name / f"{split}.jsonl")
        )
        if config.proof_data
        else None
    )
    records_path = arguments.proof_records or DATA_DIRECTORY / config.proof_records
    proofs = select_proofs(read_proof_records(records_path), identifiers, config.max_proofs, config.seed)
    train, validation = (reasoning_examples(config.reasoning_data, split) for split in ("train", "validation"))
    items = reasoning_items(train, validation)
    items = items[: config.max_examples] if config.max_examples else items
    states = read_states(RUNS_DIRECTORY / run / "states.jsonl" for run in config.state_runs)
    print(f"{len(proofs):,} proofs, {len(items):,} reasoning examples, {len(states):,} states", flush=True)
    header = most_common_header([record.header for record in proofs] + [step.header for step in states.values()])
    repl_config = LeanReplConfig(
        tactic_heartbeats=config.heartbeats,
        tactic_timeout_seconds=config.timeout_seconds,
        command_timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )
    started = time.monotonic()
    async with LeanReplPool(config.pool_size, repl_config) as pool:
        await pool.start([header])
        async with pool.acquire() as repl:
            names = await environment_names(repl, header)
        reserved = frozenset(name for name in names.constants if "." not in name) | names.keywords
        async with open_namer(config.namer, config.naming) as namer:
            run = RewriteRun(config, directory, pool, namer, reserved)

            def on_shard(name: str) -> None:
                progress = run.progress
                print(
                    f"{name} done after {time.monotonic() - started:.0f} s: proofs {progress['kept_proofs']:,}/"
                    f"{progress['proofs']:,} kept, examples {progress['kept_examples']:,}/{progress['examples']:,}",
                    flush=True,
                )

            await run_rewrite(run, proofs, items, states, on_shard)


def command_rewrite(arguments: argparse.Namespace) -> None:
    config = load_rewrite_config(arguments.config)
    overrides = {
        name: value
        for name, value in (
            ("max_proofs", arguments.max_proofs),
            ("max_examples", arguments.max_examples),
            ("pool_size", arguments.pool_size),
        )
        if value is not None
    }
    config = dataclasses.replace(config, **overrides)
    directory = RewriteDirectory(RUNS_DIRECTORY / arguments.run_name)
    keep_config(arguments.config, directory.path)
    asyncio.run(rewrite(arguments, config, directory))
    write_rewrite_summary(arguments.run_name)


def command_explain(arguments: argparse.Namespace) -> None:
    config = from_json_object(ExplainConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    build_config = load_build_config(arguments.build_config)
    directory = RewriteDirectory(RUNS_DIRECTORY / build_config.rewrite_run)
    # The shard plan holds the chunks, so a rerun with the other arm's build config resumes the same work.
    keep_config(arguments.config, directory.explanation_directory)
    tokenizer = transformers.AutoTokenizer.from_pretrained(build_config.tokenizer)
    examples = directory.read_examples()
    plan = plan_chunks(directory.read_proofs(), examples, build_config, token_counts(tokenizer))
    requests = [explanation_request(planned) for planned in plan.visible]
    few_shots = few_shot_explanations(examples, config)
    print(
        f"{len(requests):,} chunks to explain ({sum(p.visible for p in plan.train):,} train), "
        f"{len(few_shots)} few-shot examples",
        flush=True,
    )
    started = time.monotonic()
    explained: Counter[ExplanationOutcome] = Counter()

    def on_shard(index: int, records: Sequence[ChunkExplanation]) -> None:
        explained.update(record.outcome for record in records)
        print(
            f"shard {index} done after {time.monotonic() - started:.0f} s: "
            + ", ".join(f"{outcome} {count:,}" for outcome, count in explained.most_common()),
            flush=True,
        )

    async def explain() -> None:
        async with open_teacher(config, few_shots) as teacher:
            await explain_chunks(teacher, requests, directory, on_shard)

    asyncio.run(explain())
    write_rewrite_summary(build_config.rewrite_run)


def command_summary(arguments: argparse.Namespace) -> None:
    write_rewrite_summary(arguments.run_name)


def write_rewrite_summary(run_name: str) -> None:
    directory = RewriteDirectory(RUNS_DIRECTORY / run_name)
    config = load_rewrite_config(directory.path / "config.toml")
    replaced = sum(
        example.reasoning is None
        for split in ("train", "validation")
        for example in reasoning_examples(config.reasoning_data, split)
    )
    summary = rewrite_summary(
        run_name, directory.read_proofs(), directory.read_examples(), replaced, directory.read_explanations()
    )
    directory.summary.mkdir(parents=True, exist_ok=True)
    (directory.summary / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_rewrite_summary(summary)
    (directory.summary / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


def token_statistics(
    tokenizer: transformers.PreTrainedTokenizerBase, part: str, examples: Sequence[ReasoningExample]
) -> TokenStatistics:
    tokenized = [tokenize_reasoning_example(tokenizer, example) for example in examples]
    return TokenStatistics(
        part,
        length_statistics([example.prompt_token_count for example in tokenized]),
        length_statistics([example.completion_token_count for example in tokenized]),
    )


def command_build(arguments: argparse.Namespace) -> None:
    config = load_build_config(arguments.config)
    output = DATA_DIRECTORY / "reasoning" / arguments.name
    if output.exists():
        raise ValueError(f"{output} exists; data sets are built once.")
    directory = RewriteDirectory(RUNS_DIRECTORY / config.rewrite_run)
    rewrite_config = load_rewrite_config(directory.path / "config.toml")
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.tokenizer)
    explanations = {
        ChunkPosition(record.proof_identifier, record.start, record.tactics): record
        for record in directory.read_explanations()
    }
    data: BuiltData = build_data(
        directory.read_proofs(), directory.read_examples(), config, token_counts(tokenizer), explanations
    )
    write_examples(output / "train.jsonl", data.train)
    write_examples(output / "validation.jsonl", data.validation)
    write_records(output / "chunks_train.jsonl", data.train_chunks)
    write_records(output / "chunks_validation.jsonl", data.validation_chunks)
    math = DATA_DIRECTORY / "reasoning" / rewrite_config.reasoning_data / "math.jsonl"
    if math.exists():
        shutil.copyfile(math, output / "math.jsonl")
    non_visible = [chunk_training_example(chunk) for chunk in data.train_chunks if not chunk.explanation]
    visible = [chunk_training_example(chunk) for chunk in data.train_chunks if chunk.explanation]
    tokens = [
        token_statistics(tokenizer, "train chunks, non-visible", non_visible),
        token_statistics(tokenizer, "train chunks, visible", visible),
        token_statistics(tokenizer, "train reasoning", data.train_reasoning),
        token_statistics(tokenizer, "validation", data.validation),
    ]
    summary = build_summary(arguments.name, config, data, tokens)
    markdown = render_build_summary(summary)
    for summary_directory in (output, RUNS_DIRECTORY / f"data_rewrite_build_{arguments.name}" / "summary"):
        summary_directory.mkdir(parents=True, exist_ok=True)
        (summary_directory / "summary.json").write_text(
            json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False, default=str), encoding="utf-8"
        )
        (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    rewrite_command = commands.add_parser("rewrite", help="the Lean pass (resumable by shard)")
    rewrite_command.add_argument("--config", type=Path, required=True)
    rewrite_command.add_argument("--run-name", required=True)
    rewrite_command.add_argument("--proof-records", type=Path, help="a ProofRecord file instead of the configured one")
    rewrite_command.add_argument("--max-proofs", type=int)
    rewrite_command.add_argument("--max-examples", type=int)
    rewrite_command.add_argument("--pool-size", type=int)
    explain_command = commands.add_parser("explain", help="the teacher's chunk explanations (resumable by shard)")
    explain_command.add_argument("--config", type=Path, required=True, help="ExplainConfig")
    explain_command.add_argument("--build-config", type=Path, required=True, help="BuildConfig of either arm")
    summary_command = commands.add_parser("summary", help="kept and dropped per reason")
    summary_command.add_argument("--run-name", required=True)
    build_command = commands.add_parser("build", help="one naming variant's data set (config: BuildConfig)")
    build_command.add_argument("--config", type=Path, required=True)
    build_command.add_argument("--name", required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "rewrite":
            command_rewrite(arguments)
        case "explain":
            command_explain(arguments)
        case "summary":
            command_summary(arguments)
        case "build":
            command_build(arguments)


if __name__ == "__main__":
    main()
