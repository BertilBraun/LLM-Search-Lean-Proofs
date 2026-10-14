import pytest

from lean_search.training.math_data import (
    ContaminationFilter,
    MathSolution,
    fill_budget,
    tokenize_math_solution,
)
from lean_search.training.sft_data import IGNORE_INDEX, SftExample, TokenizedExample

SOLUTION = MathSolution(
    "math_train", "math_train/1", "What is $2+3$?", "We add: $2+3=5$. So the answer is $\\boxed{5}$."
)


class CharacterTokenizer:
    """ChatML turns with an empty think block when thinking is off, one token per character."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + (
            "<|im_start|>assistant\n" if enable_thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def decode(token_ids: tuple[int, ...]) -> str:
    return "".join(chr(token_id) for token_id in token_ids)


TOKENIZED = tokenize_math_solution(CharacterTokenizer(), SOLUTION)


def test_the_prompt_is_the_visible_format_with_an_empty_think_block() -> None:
    assert decode(TOKENIZED.input_ids[: TOKENIZED.prompt_token_count]).endswith(
        "\\boxed{}.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def test_the_completion_is_the_solution_and_the_end_of_turn() -> None:
    assert decode(TOKENIZED.input_ids[TOKENIZED.prompt_token_count :]) == SOLUTION.solution + "<|im_end|>"


def test_only_the_solution_carries_loss() -> None:
    assert set(TOKENIZED.labels[: TOKENIZED.prompt_token_count]) == {IGNORE_INDEX}


@pytest.mark.parametrize(
    ("problem", "contaminated"),
    [
        ("Integers $x$ and $y$ with $x>y>0$ satisfy $x+y+xy=80$. What is $x$?", True),
        ("Answer the following and explain. Integers $x$ and $y$ with $x>y>0$ satisfy $x+y+xy=80$. What is $x$?", True),
        ("A train travels 60 miles per hour for 3 hours. How far does it go?", False),
    ],
)
def test_contamination_by_shared_four_grams(problem: str, contaminated: bool) -> None:
    references = ["Integers $x$ and $y$ with $x>y>0$ satisfy $x+y+xy=80$. What is $x$? Show that it is 26."]
    assert ContaminationFilter(references).is_contaminated(problem) == contaminated


def examples(source: str, count: int, length: int) -> list[TokenizedExample]:
    return [
        TokenizedExample(SftExample(source, f"{source}/{index}", 0, (), ""), (1,) * length, 1) for index in range(count)
    ]


def test_an_exhausted_source_passes_its_share_on() -> None:
    selected = fill_budget(
        {"small": examples("small", 2, 10), "large": examples("large", 50, 10)}, {"small": 1.0, "large": 1.0}, 200
    )
    assert [sum(example.token_count for example in selected[source]) for source in ("small", "large")] == [20, 180]
