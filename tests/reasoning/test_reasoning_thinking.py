import pytest

from lean_search.policy.client import Sample
from lean_search.policy.prompts import ParseFailure
from lean_search.reasoning.thinking import is_trainable_reasoning, parse_thinking_sample, reasoning_text

ANSWER = "\n</think>\n\n```lean\nnlinarith [sq_nonneg (a - b)]\n```"


def sample(text: str, finish_reason: str = "stop") -> Sample:
    return Sample(text, -1.0, 10, finish_reason)


def test_reasoning_is_the_stripped_text_before_the_closing_tag() -> None:
    assert parse_thinking_sample(sample("\nThe goal is an inequality.\n" + ANSWER), thinking=True).reasoning == (
        "The goal is an inequality."
    )


def test_block_is_read_after_the_closing_tag() -> None:
    parsed = parse_thinking_sample(sample("Draft:\n```lean\nlinarith\n```\nNo, use squares." + ANSWER), thinking=True)
    assert parsed.tactic_block == "nlinarith [sq_nonneg (a - b)]"


def test_truncated_sample_keeps_its_unfinished_reasoning() -> None:
    parsed = parse_thinking_sample(sample("First expand the square and", "length"), thinking=True)
    assert (parsed.reasoning, parsed.tactic_block, parsed.parse_failure) == (
        "First expand the square and",
        None,
        ParseFailure.TRUNCATED,
    )


def test_unclosed_thoughts_have_no_block() -> None:
    assert parse_thinking_sample(sample("```lean\nlinarith\n```"), thinking=True).parse_failure == ParseFailure.NO_BLOCK


def test_forbidden_block_is_a_parse_failure() -> None:
    text = "Search.\n</think>\n\n```lean\nexact?\n```"
    assert parse_thinking_sample(sample(text), thinking=True).parse_failure == ParseFailure.FORBIDDEN


def test_non_thinking_sample_has_no_reasoning() -> None:
    parsed = parse_thinking_sample(sample("linarith"), thinking=False)
    assert (parsed.reasoning, parsed.tactic_block) == ("", "linarith")


def test_reasoning_is_read_before_the_last_closing_tag() -> None:
    assert reasoning_text("one</think>two</think>\n```lean\nrfl\n```") == "one</think>two"


@pytest.mark.parametrize(
    ("reasoning", "trainable"),
    [
        ("Use linarith on h₀.", True),
        ("", False),
        ("one</think>two", False),
        ("<think>nested", False),
    ],
)
def test_trainable_reasoning_is_non_empty_without_think_tags(reasoning: str, trainable: bool) -> None:
    assert is_trainable_reasoning(reasoning) == trainable
