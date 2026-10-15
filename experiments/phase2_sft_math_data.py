"""Build the general-math worked-solution mix for a gentle Lean SFT: MATH train and NuminaMath-CoT, decontaminated.

    python experiments/phase2_sft_math_data.py --name math_v1 --token-budget 4500000

Sources: the MATH train split (MATH-lighteval) and NuminaMath-CoT's school-level sources (cn_k12, synthetic_math,
orca_math, gsm8k; competition sources are left out because miniF2F draws on AMC, AIME and IMO). Problems sharing
half of their informal 4-grams with a MATH-500 or miniF2F statement are dropped. Equal token shares per source,
each in a fixed pseudo-random order; tokens are Qwen3.5 tokens of the visible chat format (prompt + solution).
Writes $LEAN_SEARCH_DATA/math_sft/<name>/train.jsonl and a summary under $LEAN_SEARCH_RUNS/phase2_sft_data/summary/.
"""

import argparse
import dataclasses
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.search.summary import markdown_table
from lean_search.training.math_data import (
    ContaminationFilter,
    benchmark_statements,
    fill_budget,
    load_candidates,
    tokenize_math_solution,
    write_solutions,
)
from lean_search.training.sft_data import length_statistics

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase2_sft_data"
MATH_TRAIN = DATA_DIRECTORY / "raw" / "math_lighteval" / "data" / "train-00000-of-00001.parquet"
NUMINAMATH_SHARD = DATA_DIRECTORY / "raw" / "numinamath_cot" / "data" / "train-00000-of-00005.parquet"
MATH_500 = DATA_DIRECTORY / "math500" / "test.jsonl"


@dataclass(frozen=True)
class SourceSummary:
    source: str
    candidates: int
    contaminated: int
    over_length: int
    selected: int
    tokens: int
    completion_tokens_mean: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--token-budget", type=int, required=True)
    parser.add_argument("--tokenizer", default="Qwen/Qwen3.5-4B")
    parser.add_argument("--max-prompt-tokens", type=int, default=1024)
    parser.add_argument("--max-completion-tokens", type=int, default=1024)
    parser.add_argument("--seed", default="math-mix")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    tokenizer = transformers.AutoTokenizer.from_pretrained(arguments.tokenizer)
    contamination = ContaminationFilter(benchmark_statements(MATH_500))
    pools = load_candidates(MATH_TRAIN, NUMINAMATH_SHARD)
    tokenized_by_source = {}
    counts: dict[str, Counter[str]] = {}
    for source, solutions in pools.items():
        counter: Counter[str] = Counter(candidates=len(solutions))
        ordered = sorted(
            solutions, key=lambda solution: hashlib.sha256(f"{arguments.seed}\n{solution.identifier}".encode()).digest()
        )
        kept = []
        for solution in ordered:
            if contamination.is_contaminated(solution.problem):
                counter["contaminated"] += 1
                continue
            tokenized = tokenize_math_solution(tokenizer, solution)
            if (
                tokenized.prompt_token_count > arguments.max_prompt_tokens
                or tokenized.completion_token_count > arguments.max_completion_tokens
            ):
                counter["over_length"] += 1
                continue
            kept.append(tokenized)
        tokenized_by_source[source] = kept
        counts[source] = counter
        print(f"{source}: {counter}", flush=True)
    selected = fill_budget(tokenized_by_source, dict.fromkeys(pools, 1.0), arguments.token_budget)
    by_identifier = {solution.identifier: solution for solutions in pools.values() for solution in solutions}
    chosen = [example for examples in selected.values() for example in examples]
    output_directory = DATA_DIRECTORY / "math_sft" / arguments.name
    write_solutions(
        output_directory / "train.jsonl", (by_identifier[example.example.proof_identifier] for example in chosen)
    )
    summaries = [
        SourceSummary(
            source=source,
            candidates=counts[source]["candidates"],
            contaminated=counts[source]["contaminated"],
            over_length=counts[source]["over_length"],
            selected=len(examples),
            tokens=sum(example.token_count for example in examples),
            completion_tokens_mean=length_statistics([example.completion_token_count for example in examples]).mean,
        )
        for source, examples in selected.items()
    ]
    total = length_statistics([example.token_count for example in chosen])
    rows = [
        [
            summary.source,
            f"{summary.candidates:,}",
            f"{summary.contaminated:,}",
            f"{summary.over_length:,}",
            f"{summary.selected:,}",
            f"{summary.tokens:,}",
            f"{summary.completion_tokens_mean:.0f}",
        ]
        for summary in summaries
    ]
    markdown = (
        "\n\n".join(
            [
                f"# Math worked-solution data `{arguments.name}`",
                f"Budget {arguments.token_budget:,} `{arguments.tokenizer}` tokens (prompt + solution), caps "
                f"{arguments.max_prompt_tokens} prompt and {arguments.max_completion_tokens} completion tokens, seed "
                f"`{arguments.seed}`. {total.count:,} examples, {total.total:,} tokens (mean {total.mean:.0f}). "
                "Visible chat format: the problem plus the \\boxed{} instruction, an empty think block, the worked "
                "solution as the completion. Contaminated: shares half of the informal 4-grams with one of the 500 "
                "MATH-500 or 488 miniF2F statements.",
                markdown_table(
                    [
                        "Source",
                        "Candidates",
                        "Contaminated",
                        "Over length",
                        "Selected",
                        "Tokens",
                        "Solution tokens mean",
                    ],
                    rows,
                ),
            ]
        )
        + "\n"
    )
    (output_directory / "summary.md").write_text(markdown, encoding="utf-8")
    (RUN_DIRECTORY / "summary").mkdir(parents=True, exist_ok=True)
    (RUN_DIRECTORY / "summary" / f"{arguments.name}.md").write_text(markdown, encoding="utf-8")
    (RUN_DIRECTORY / "summary" / f"{arguments.name}.json").write_text(
        json.dumps([dataclasses.asdict(summary) for summary in summaries], indent=1), encoding="utf-8"
    )
    print(markdown)


if __name__ == "__main__":
    main()
