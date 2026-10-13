"""Reasoning retention: MATH-500 problems solved in natural language with thinking on, base models vs Lean-trained.

    python experiments/reasoning_retention.py --config experiments/configs/evaluation/reasoning_retention.toml problems
    python experiments/reasoning_retention.py --config ... run --gpu 0 --port 8130 --labels qwen3.5-2b ...
    python experiments/reasoning_retention.py --config ... summarize

`problems` fixes a stratified subset (by level and subject) and the problems read by hand. `run` serves each
model on one GPU (a LoRA adapter on its base), samples k solutions per problem, and scores them: the answer is the
last \\boxed{} after the thinking block, compared with `lean_search.evaluation.math_answers`. `summarize` writes the
accuracy, length and truncation tables and, for the judged problems, one trace per model to read.
Outputs in $LEAN_SEARCH_RUNS/reasoning_retention/: problems.jsonl, models/<label>/{samples,scores}.jsonl, summary/.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import hashlib
import json
import os
import statistics
import subprocess
import time
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import transformers

from lean_search.evaluation.math_answers import answers_match, last_boxed
from lean_search.policy import ChatMessage, PolicyClient
from lean_search.policy.prompts import THINK_END
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "reasoning_retention"
LENGTH_FINISH_REASON = "length"
JUDGED_TRACE_CHARACTERS = 12000


@dataclass(frozen=True)
class ModelSpec:
    label: str
    base: str
    adapter: str = ""


@dataclass(frozen=True)
class RetentionConfig:
    dataset: str
    problem_count: int
    judged_problem_count: int
    seed: str
    sample_count: int
    temperature: float
    top_p: float
    max_tokens: int
    max_model_length: int
    requests_in_flight: int
    instruction: str
    models: tuple[ModelSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Problem:
    unique_id: str
    problem: str
    answer: str
    subject: str
    level: int
    judged: bool


@dataclass(frozen=True)
class SolutionSample:
    text: str
    token_count: int
    finish_reason: str


@dataclass(frozen=True)
class ProblemSamples:
    unique_id: str
    prompt_tokens: int
    seconds: float
    samples: tuple[SolutionSample, ...]


@dataclass(frozen=True)
class ScoredSample:
    unique_id: str
    sample_index: int
    truncated: bool
    finished_thinking: bool
    answer: str | None
    correct: bool
    reasoning_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class SamplingRun:
    label: str
    base: str
    adapter: str
    problems: int
    samples: int
    generated_tokens: int
    wall_seconds: float
    generated_tokens_per_second: float
    git_revision: str


def stable_order(seed: str, key: str) -> bytes:
    return hashlib.sha256(f"{seed}\n{key}".encode()).digest()


def select_problems(candidates: Sequence[Problem], count: int, judged_count: int, seed: str) -> list[Problem]:
    """Proportional by (level, subject) cell with largest remainders; judged problems spread evenly over levels."""
    cells: dict[tuple[int, str], list[Problem]] = defaultdict(list)
    for problem in candidates:
        cells[(problem.level, problem.subject)].append(problem)
    quotas = {cell: len(members) * count / len(candidates) for cell, members in cells.items()}
    allocation = {cell: int(quota) for cell, quota in quotas.items()}
    by_remainder = sorted(cells, key=lambda cell: (allocation[cell] - quotas[cell], stable_order(seed, str(cell))))
    for cell in by_remainder[: count - sum(allocation.values())]:
        allocation[cell] += 1
    chosen = [
        problem
        for cell, members in sorted(cells.items())
        for problem in sorted(members, key=lambda problem: stable_order(seed, problem.unique_id))[: allocation[cell]]
    ]
    by_level: dict[int, list[Problem]] = defaultdict(list)
    for problem in sorted(chosen, key=lambda problem: stable_order(seed + "/judged", problem.unique_id)):
        by_level[problem.level].append(problem)
    levels = sorted(by_level)
    judged = {by_level[levels[rank % len(levels)]][rank // len(levels)].unique_id for rank in range(judged_count)}
    return [dataclasses.replace(problem, judged=problem.unique_id in judged) for problem in chosen]


def write_records(path: Path, records: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def read_records[T](path: Path, record_type: type[T]) -> list[T]:
    with path.open(encoding="utf-8") as handle:
        return [from_json_object(record_type, json.loads(line)) for line in handle]


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


@contextlib.contextmanager
def served(name: str, model: ModelSpec, gpu: int, port: int, max_model_length: int) -> Iterator[None]:
    deployment = REPOSITORY_DIRECTORY / "deployment"
    environment = {**os.environ, "MAX_MODEL_LEN": str(max_model_length)}
    subprocess.run(
        [str(deployment / "serve_model.sh"), name, model.base, str(gpu), str(port)], check=True, env=environment
    )
    try:
        yield
    finally:
        subprocess.run([str(deployment / "stop_model.sh"), name], check=True)


async def sample_problems(
    config: RetentionConfig, model: ModelSpec, problems: Sequence[Problem], server_url: str, served_name: str
) -> list[ProblemSamples]:
    semaphore = asyncio.Semaphore(config.requests_in_flight)
    async with PolicyClient(server_url, served_name) as client:
        adapter = None
        if model.adapter:
            adapter = f"{served_name}-adapter"
            await client.load_adapter(adapter, model.adapter)

        async def sample(problem: Problem) -> ProblemSamples:
            message = ChatMessage("user", f"{problem.problem}\n\n{config.instruction}")
            async with semaphore:
                started = time.monotonic()
                generation = await client.generate_chat(
                    [message],
                    enable_thinking=True,
                    sample_count=config.sample_count,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    top_p=config.top_p,
                    adapter=adapter,
                )
            samples = tuple(
                SolutionSample(sample.text, sample.token_count, sample.finish_reason) for sample in generation.samples
            )
            return ProblemSamples(problem.unique_id, generation.prompt_token_count, time.monotonic() - started, samples)

        return list(await asyncio.gather(*(sample(problem) for problem in problems)))


def score(
    problem: Problem, samples: ProblemSamples, tokenizer: transformers.PreTrainedTokenizerBase
) -> list[ScoredSample]:
    scored = []
    for index, sample in enumerate(samples.samples):
        reasoning, think_end, after = sample.text.partition(THINK_END)
        answer = last_boxed(after) if think_end else None
        scored.append(
            ScoredSample(
                unique_id=problem.unique_id,
                sample_index=index,
                truncated=sample.finish_reason == LENGTH_FINISH_REASON,
                finished_thinking=bool(think_end),
                answer=answer,
                correct=answer is not None and answers_match(answer, problem.answer),
                reasoning_tokens=len(tokenizer.encode(reasoning, add_special_tokens=False)),
                total_tokens=sample.token_count,
            )
        )
    return scored


def command_problems(config: RetentionConfig) -> None:
    with Path(config.dataset).open(encoding="utf-8") as handle:
        candidates = [
            Problem(row["unique_id"], row["problem"], row["answer"], row["subject"], int(row["level"]), judged=False)
            for row in map(json.loads, handle)
        ]
    problems = select_problems(candidates, config.problem_count, config.judged_problem_count, config.seed)
    write_records(RUN_DIRECTORY / "problems.jsonl", problems)
    print(f"{len(problems)} problems, {sum(problem.judged for problem in problems)} judged, from {len(candidates)}")


def command_run(config: RetentionConfig, labels: Sequence[str], gpu: int, port: int) -> None:
    problems = read_records(RUN_DIRECTORY / "problems.jsonl", Problem)
    models = {model.label: model for model in config.models}
    for label in labels:
        model = models[label]
        if model.adapter and not Path(model.adapter).exists():
            print(f"{label}: adapter {model.adapter} does not exist, skipped", flush=True)
            continue
        directory = RUN_DIRECTORY / "models" / label
        served_name = f"retention-{label}"
        started = time.monotonic()
        with served(served_name, model, gpu, port, config.max_model_length):
            results = asyncio.run(sample_problems(config, model, problems, f"http://127.0.0.1:{port}/v1", served_name))
        wall_seconds = time.monotonic() - started
        write_records(directory / "samples.jsonl", results)
        generated = sum(sample.token_count for result in results for sample in result.samples)
        run = SamplingRun(
            label=label,
            base=model.base,
            adapter=model.adapter,
            problems=len(results),
            samples=sum(len(result.samples) for result in results),
            generated_tokens=generated,
            wall_seconds=wall_seconds,
            generated_tokens_per_second=generated / wall_seconds,
            git_revision=git_revision(),
        )
        (directory / "sampling.json").write_text(json.dumps(dataclasses.asdict(run), indent=1), encoding="utf-8")
        tokenizer = transformers.AutoTokenizer.from_pretrained(model.base)
        by_id = {problem.unique_id: problem for problem in problems}
        write_records(
            directory / "scores.jsonl",
            (scored for result in results for scored in score(by_id[result.unique_id], result, tokenizer)),
        )
        print(f"{label}: {run.samples} samples, {generated:,} tokens in {wall_seconds:.0f} s", flush=True)


def percent(numerator: float, denominator: float) -> str:
    return f"{numerator / denominator:.1%}" if denominator else "–"


def quantiles(values: Sequence[int]) -> list[str]:
    if not values:
        return ["–"] * 4
    ordered = sorted(values)
    return [
        f"{statistics.mean(ordered):,.0f}",
        f"{ordered[len(ordered) // 2]:,}",
        f"{ordered[int(0.9 * len(ordered))]:,}",
        f"{ordered[-1]:,}",
    ]


def command_summarize(config: RetentionConfig) -> None:
    problems = read_records(RUN_DIRECTORY / "problems.jsonl", Problem)
    labels = [
        model.label for model in config.models if (RUN_DIRECTORY / "models" / model.label / "scores.jsonl").exists()
    ]
    scores = {label: read_records(RUN_DIRECTORY / "models" / label / "scores.jsonl", ScoredSample) for label in labels}
    samples = {
        label: {
            record.unique_id: record
            for record in read_records(RUN_DIRECTORY / "models" / label / "samples.jsonl", ProblemSamples)
        }
        for label in labels
    }
    accuracy_rows, length_rows, level_rows = [], [], []
    levels = sorted({problem.level for problem in problems})
    level_of = {problem.unique_id: problem.level for problem in problems}
    for label in labels:
        records = scores[label]
        by_problem: dict[str, list[ScoredSample]] = defaultdict(list)
        for record in records:
            by_problem[record.unique_id].append(record)
        any_correct = sum(any(record.correct for record in group) for group in by_problem.values())
        accuracy_rows.append(
            [
                label,
                percent(sum(record.correct for record in records), len(records)),
                percent(any_correct, len(by_problem)),
                percent(sum(record.truncated for record in records), len(records)),
                percent(sum(not record.finished_thinking for record in records), len(records)),
                percent(sum(record.finished_thinking and record.answer is None for record in records), len(records)),
            ]
        )
        length_rows.append(
            [
                label,
                *quantiles([record.reasoning_tokens for record in records]),
                *quantiles([record.reasoning_tokens for record in records if record.correct]),
                *quantiles(
                    [record.reasoning_tokens for record in records if not record.correct and not record.truncated]
                ),
            ]
        )
        level_rows.append(
            [
                label,
                *(
                    percent(
                        sum(record.correct for record in records if level_of[record.unique_id] == level),
                        sum(level_of[record.unique_id] == level for record in records),
                    )
                    for level in levels
                ),
            ]
        )
    sections = [
        "# Reasoning retention on MATH-500",
        f"{len(problems)} MATH-500 problems stratified by level and subject (seed `{config.seed}`), thinking on, "
        f"k = {config.sample_count} samples at temperature {config.temperature} (top-p {config.top_p}), at most "
        f"{config.max_tokens} generated tokens; the answer is the last \\boxed{{}} after the thinking block.",
        markdown_table(
            [
                "Model",
                "pass@1 (mean over k)",
                f"any@{config.sample_count}",
                "Truncated",
                "Thinking unfinished",
                "No boxed answer",
            ],
            accuracy_rows,
        ),
        "## Accuracy by level (pass@1)",
        markdown_table(["Model", *(f"Level {level}" for level in levels)], level_rows),
        "## Reasoning length (tokens before </think>)",
        markdown_table(
            [
                "Model",
                "All mean",
                "p50",
                "p90",
                "Max",
                "Correct mean",
                "p50",
                "p90",
                "Max",
                "Wrong (finished) mean",
                "p50",
                "p90",
                "Max",
            ],
            length_rows,
        ),
    ]
    summary_directory = RUN_DIRECTORY / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    judged = [problem for problem in problems if problem.judged]
    for label in labels:
        scored = {(record.unique_id, record.sample_index): record for record in scores[label]}
        lines = [f"# Judged traces: {label}"]
        for problem in judged:
            record = scored[(problem.unique_id, 0)]
            text = samples[label][problem.unique_id].samples[0].text
            lines += [
                f"## {problem.unique_id} (level {problem.level}, {problem.subject})",
                f"Problem: {problem.problem}",
                f"Reference: {problem.answer}; answer: {record.answer}; correct: {record.correct}; "
                f"reasoning tokens: {record.reasoning_tokens}; truncated: {record.truncated}",
                "```text\n"
                + text[:JUDGED_TRACE_CHARACTERS]
                + ("\n[...]" if len(text) > JUDGED_TRACE_CHARACTERS else "")
                + "\n```",
            ]
        (summary_directory / "judged").mkdir(exist_ok=True)
        (summary_directory / "judged" / f"{label}.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    print("\n\n".join(sections))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("problems", help="fix the stratified problem subset")
    run = commands.add_parser("run", help="sample and score models on one GPU")
    run.add_argument("--labels", nargs="+", required=True)
    run.add_argument("--gpu", type=int, required=True)
    run.add_argument("--port", type=int, default=8130)
    commands.add_parser("summarize", help="tabulate every scored model")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    config = from_json_object(RetentionConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    match arguments.command:
        case "problems":
            command_problems(config)
        case "run":
            command_run(config, arguments.labels, arguments.gpu, arguments.port)
        case "summarize":
            command_summarize(config)


if __name__ == "__main__":
    main()
