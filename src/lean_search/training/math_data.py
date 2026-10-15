"""General math worked solutions (visible, or with a thinking block) mixed into Lean SFT to keep reasoning."""

import dataclasses
import json
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as parquet

from lean_search.corpora.decontamination import informal_ngrams
from lean_search.data.minif2f import load_minif2f
from lean_search.policy.prompts import END_OF_TURN
from lean_search.training.sft_data import SftExample, TokenizedExample, Tokenizer

MATH_INSTRUCTION = "Please reason step by step, and put your final answer within \\boxed{}."
# A problem is contaminated if it shares this fraction of a reference's informal 4-grams (or the reference shares
# this fraction of the problem's): one direction catches a reference quoted inside a longer problem.
CONTAINMENT_THRESHOLD = 0.5
# School-level NuminaMath-CoT sources; the competition ones are left out because miniF2F draws on AMC, AIME and IMO.
NUMINAMATH_SOURCES = frozenset({"cn_k12", "synthetic_math", "orca_math", "gsm8k"})
BOX = "\\boxed{"


@dataclass(frozen=True)
class MathSolution:
    source: str
    identifier: str
    problem: str
    solution: str
    # A solution that starts with reasoning inside the thinking block (thinking-mode prompt).
    thinking: bool = False


class ContaminationFilter:
    """Informal 4-gram containment against reference problems (benchmark statements)."""

    def __init__(self, references: Iterable[str]) -> None:
        self.reference_ngrams = [informal_ngrams(reference) for reference in references]
        self.ngram_to_references: dict[str, list[int]] = {}
        for index, ngrams in enumerate(self.reference_ngrams):
            for ngram in ngrams:
                self.ngram_to_references.setdefault(ngram, []).append(index)

    def is_contaminated(self, problem: str) -> bool:
        ngrams = informal_ngrams(problem)
        shared: Counter[int] = Counter()
        for ngram in ngrams:
            shared.update(self.ngram_to_references.get(ngram, ()))
        return any(
            count >= CONTAINMENT_THRESHOLD * len(self.reference_ngrams[index])
            or count >= CONTAINMENT_THRESHOLD * len(ngrams)
            for index, count in shared.items()
        )


def load_candidates(math_train: Path, numinamath_shard: Path) -> dict[str, list[MathSolution]]:
    """MATH train and NuminaMath-CoT's school-level problems with their reference solutions, by source."""
    math_rows = parquet.read_table(math_train).to_pylist()
    numina_rows = parquet.read_table(numinamath_shard, columns=["source", "problem", "solution"]).to_pylist()
    return {
        "math_train": [
            MathSolution("math_train", f"math_train/{index}", row["problem"], row["solution"])
            for index, row in enumerate(math_rows)
        ],
        "numinamath_cot": [
            MathSolution(
                f"numinamath_cot/{row['source']}", f"numinamath_cot/0/{index}", row["problem"], row["solution"]
            )
            for index, row in enumerate(numina_rows)
            if row["source"] in NUMINAMATH_SOURCES and BOX in row["solution"]
        ],
    }


def benchmark_statements(math_500: Path) -> list[str]:
    """MATH-500 problems and miniF2F informal statements, the references for decontamination."""
    with math_500.open(encoding="utf-8") as handle:
        problems = [json.loads(line)["problem"] for line in handle]
    return problems + [problem.informal_prefix for problem in load_minif2f()]


def math_prompt(tokenizer: Tokenizer, problem: str, thinking: bool = False) -> str:
    conversation = [{"role": "user", "content": f"{problem}\n\n{MATH_INSTRUCTION}"}]
    return tokenizer.apply_chat_template(
        conversation, tokenize=False, add_generation_prompt=True, enable_thinking=thinking
    )


def tokenize_math_solution(tokenizer: Tokenizer, solution: MathSolution) -> TokenizedExample:
    """Visible: an empty think block in the prompt; thinking: an open one. The solution is the completion."""
    prompt = math_prompt(tokenizer, solution.problem, solution.thinking)
    prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
    completion_ids = tokenizer.encode(solution.solution.strip() + END_OF_TURN, add_special_tokens=False)
    # The Lean fields stay empty: math examples only train, they never enter the tactic evaluation.
    placeholder = SftExample(solution.source, solution.identifier, 0, (), "")
    return TokenizedExample(placeholder, tuple(prompt_ids + completion_ids), len(prompt_ids))


def fill_budget(
    tokenized_by_source: dict[str, Sequence[TokenizedExample]], weights: dict[str, float], token_budget: int
) -> dict[str, list[TokenizedExample]]:
    """Each source's examples (already in a fixed random order) up to its weighted share; unused shares move on."""
    selected: dict[str, list[TokenizedExample]] = {source: [] for source in weights}
    active = {source for source, weight in weights.items() if weight > 0}
    remaining = float(token_budget)
    while active:
        total_weight = sum(weights[source] for source in active)
        exhausted = set()
        for source in active:
            target = remaining * weights[source] / total_weight
            available = sum(example.token_count for example in tokenized_by_source[source])
            if available <= target:
                exhausted.add(source)
        if not exhausted:
            for source in active:
                target = remaining * weights[source] / total_weight
                tokens = 0
                for example in tokenized_by_source[source]:
                    if tokens >= target:
                        break
                    selected[source].append(example)
                    tokens += example.token_count
            return selected
        for source in exhausted:
            selected[source] = list(tokenized_by_source[source])
            remaining -= sum(example.token_count for example in selected[source])
        active -= exhausted
    return selected


def write_solutions(path: Path, solutions: Iterable[MathSolution]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for solution in solutions:
            handle.write(json.dumps(dataclasses.asdict(solution), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_solutions(path: Path) -> Iterator[MathSolution]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield MathSolution(**json.loads(line))
