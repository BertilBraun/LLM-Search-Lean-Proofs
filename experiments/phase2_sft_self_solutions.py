"""Self-solutions: the base model's own answer-checked math solutions, as SFT targets that keep its reasoning style.

    python experiments/phase2_sft_self_solutions.py --name self_v1 \
        --server-urls http://127.0.0.1:8140/v1,http://127.0.0.1:8141/v1 --served-name base-4b

Problems: MATH train and NuminaMath-CoT's school-level sources, decontaminated against MATH-500 and miniF2F, in a
fixed pseudo-random order, half from each source. The first `--visible-problems` are solved once in the visible
non-thinking format (the reasoning-retention prompt), the next `--thinking-problems` once with thinking on. A solution
is kept if it finished on its own and its last \\boxed{} (after the thinking block, with thinking) matches the
reference solution's boxed answer. Writes $LEAN_SEARCH_DATA/math_sft/<name>/{train,samples}.jsonl and a summary
under $LEAN_SEARCH_RUNS/phase2_sft_data/summary/<name>.md.
"""

import argparse
import asyncio
import dataclasses
import hashlib
import itertools
import json
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.evaluation.math_answers import answers_match, last_boxed
from lean_search.policy import ChatMessage, PolicyClient
from lean_search.policy.prompts import THINK_END
from lean_search.search.summary import markdown_table
from lean_search.training.math_data import (
    MATH_INSTRUCTION,
    ContaminationFilter,
    MathSolution,
    benchmark_statements,
    load_candidates,
    write_solutions,
)

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase2_sft_data"
MATH_TRAIN = DATA_DIRECTORY / "raw" / "math_lighteval" / "data" / "train-00000-of-00001.parquet"
NUMINAMATH_SHARD = DATA_DIRECTORY / "raw" / "numinamath_cot" / "data" / "train-00000-of-00005.parquet"
MATH_500 = DATA_DIRECTORY / "math500" / "test.jsonl"
STOP_FINISH_REASON = "stop"


@dataclass(frozen=True)
class SampledSolution:
    source: str
    identifier: str
    problem: str
    reference_answer: str
    thinking: bool
    text: str
    token_count: int
    finish_reason: str
    answer: str | None
    correct: bool


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--server-urls", required=True, help="comma-separated, all serving --served-name")
    parser.add_argument("--served-name", required=True)
    parser.add_argument("--tokenizer", default="Qwen/Qwen3.5-4B")
    parser.add_argument("--visible-problems", type=int, default=8000)
    parser.add_argument("--thinking-problems", type=int, default=1500)
    parser.add_argument("--visible-max-tokens", type=int, default=2048)
    parser.add_argument("--thinking-max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--requests-in-flight", type=int, default=256)
    parser.add_argument("--seed", default="self-solutions")
    return parser.parse_args()


def ordered_problems(seed: str) -> list[tuple[MathSolution, str]]:
    """Decontaminated problems with a boxed reference answer, alternating sources, each in a fixed random order."""
    contamination = ContaminationFilter(benchmark_statements(MATH_500))
    by_source = []
    for solutions in load_candidates(MATH_TRAIN, NUMINAMATH_SHARD).values():
        kept = []
        for solution in sorted(
            solutions, key=lambda item: hashlib.sha256(f"{seed}\n{item.identifier}".encode()).digest()
        ):
            reference = last_boxed(solution.solution)
            if reference is not None and not contamination.is_contaminated(solution.problem):
                kept.append((solution, reference))
        by_source.append(kept)
    interleaved = itertools.chain.from_iterable(itertools.zip_longest(*by_source))
    return [item for item in interleaved if item is not None]


def final_answer(text: str, thinking: bool) -> str | None:
    if thinking:
        _, think_end, after = text.partition(THINK_END)
        return last_boxed(after) if think_end else None
    return last_boxed(text)


async def sample_all(
    arguments: argparse.Namespace, problems: Sequence[tuple[MathSolution, str]], thinking_from: int
) -> list[SampledSolution]:
    urls = arguments.server_urls.split(",")
    semaphore = asyncio.Semaphore(arguments.requests_in_flight)
    clients = [PolicyClient(url, arguments.served_name) for url in urls]
    finished = 0

    async def solve(index: int, problem: MathSolution, reference: str) -> SampledSolution:
        nonlocal finished
        thinking = index >= thinking_from
        message = ChatMessage("user", f"{problem.problem}\n\n{MATH_INSTRUCTION}")
        async with semaphore:
            generation = await clients[index % len(clients)].generate_chat(
                [message],
                enable_thinking=thinking,
                sample_count=1,
                max_tokens=arguments.thinking_max_tokens if thinking else arguments.visible_max_tokens,
                temperature=arguments.temperature,
                top_p=arguments.top_p,
            )
        sample = generation.samples[0]
        answer = final_answer(sample.text, thinking)
        finished += 1
        if finished % 1000 == 0:
            print(f"{finished}/{len(problems)} solved", flush=True)
        return SampledSolution(
            source=problem.source,
            identifier=problem.identifier,
            problem=problem.problem,
            reference_answer=reference,
            thinking=thinking,
            text=sample.text,
            token_count=sample.token_count,
            finish_reason=sample.finish_reason,
            answer=answer,
            correct=answer is not None and answers_match(answer, reference),
        )

    try:
        return list(
            await asyncio.gather(
                *(solve(index, problem, reference) for index, (problem, reference) in enumerate(problems))
            )
        )
    finally:
        for client in clients:
            await client.close()


def kept(sample: SampledSolution) -> bool:
    return sample.correct and sample.finish_reason == STOP_FINISH_REASON


def length_cells(values: Sequence[int]) -> list[str]:
    if not values:
        return ["0", "–", "–", "–", "–"]
    ordered = sorted(values)
    return [
        f"{len(ordered):,}",
        f"{statistics.mean(ordered):,.0f}",
        f"{ordered[len(ordered) // 10]:,}",
        f"{ordered[len(ordered) // 2]:,}",
        f"{ordered[9 * len(ordered) // 10]:,}",
    ]


def main() -> None:
    arguments = parse_arguments()
    problems = ordered_problems(arguments.seed)[: arguments.visible_problems + arguments.thinking_problems]
    samples = asyncio.run(sample_all(arguments, problems, arguments.visible_problems))
    output_directory = DATA_DIRECTORY / "math_sft" / arguments.name
    output_directory.mkdir(parents=True, exist_ok=True)
    with (output_directory / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(dataclasses.asdict(sample), ensure_ascii=False) + "\n")
    solutions = [
        MathSolution(sample.source, sample.identifier, sample.problem, sample.text.strip(), sample.thinking)
        for sample in samples
        if kept(sample)
    ]
    write_solutions(output_directory / "train.jsonl", solutions)
    tokenizer = transformers.AutoTokenizer.from_pretrained(arguments.tokenizer)
    rows = []
    for thinking in (False, True):
        group = [sample for sample in samples if sample.thinking == thinking]
        good = [sample for sample in group if kept(sample)]
        mode = "thinking" if thinking else "visible"
        rows.append(
            [
                mode,
                f"{len(group):,}",
                f"{sum(sample.correct for sample in group) / max(1, len(group)):.1%}",
                f"{sum(sample.finish_reason != STOP_FINISH_REASON for sample in group) / max(1, len(group)):.1%}",
                *length_cells([sample.token_count for sample in good]),
                f"{sum(sample.token_count for sample in good):,}",
            ]
        )
    reference_lengths = [
        len(tokenizer.encode(problem.solution, add_special_tokens=False))
        for problem, _ in problems[: arguments.visible_problems]
    ]
    reference_cells = length_cells(reference_lengths)
    reference_summary = ", ".join(
        f"{name} {value}" for name, value in zip(("n", "mean", "p10", "p50", "p90"), reference_cells, strict=True)
    )
    intro = (
        f"`{arguments.served_name}` solved {len(problems):,} decontaminated problems (MATH train and school-level "
        f"NuminaMath-CoT, alternating) once each at temperature {arguments.temperature} / top-p "
        f"{arguments.top_p}: {arguments.visible_problems:,} in the visible non-thinking format (cap "
        f"{arguments.visible_max_tokens}), {arguments.thinking_problems:,} with thinking (cap "
        f"{arguments.thinking_max_tokens}). Kept: finished and the boxed answer matches the reference's."
    )
    header = ["Mode", "Problems", "Correct", "Truncated", "Kept", "Mean tokens", "p10", "p50", "p90", "Kept tokens"]
    sections = [
        f"# Self-solution math data `{arguments.name}`",
        intro,
        markdown_table(header, rows),
        f"Reference-solution tokens of the same visible problems, for comparison: {reference_summary}.",
    ]
    markdown = "\n\n".join(sections) + "\n"
    (output_directory / "summary.md").write_text(markdown, encoding="utf-8")
    (RUN_DIRECTORY / "summary").mkdir(parents=True, exist_ok=True)
    (RUN_DIRECTORY / "summary" / f"{arguments.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
