import pytest

from lean_search.policy import Sample
from lean_search.policy.prompts import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    ParseFailure,
    parse_sample,
    parse_samples,
    prompt_messages,
    render_completion,
    render_prompt,
    stop_sequences,
    user_message,
)

GOALS = ("x : ℕ\nh : x + 1 = 3\n⊢ x = 2", "case right\n⊢ 0 < 1")


class ChatMlTemplate:
    """Qwen3's template in miniature: ChatML turns and an empty think block when thinking is off."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        assert not tokenize and add_generation_prompt
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + (
            "<|im_start|>assistant\n" if enable_thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )


def sample(text: str, log_probability: float = -1.0, tokens: int = 5, finish_reason: str = "stop") -> Sample:
    return Sample(text=text, cumulative_logprob=log_probability, token_count=tokens, finish_reason=finish_reason)


def test_user_message_separates_goals_by_a_blank_line_in_a_lean_block() -> None:
    assert user_message(GOALS) == ("Proof state:\n```lean\nx : ℕ\nh : x + 1 = 3\n⊢ x = 2\n\ncase right\n⊢ 0 < 1\n```")


def test_user_message_lists_lemmas_after_the_state() -> None:
    assert user_message(GOALS[:1], ["Nat.succ_le_iff : succ n ≤ m ↔ n < m", "Nat.lt_irrefl : ¬n < n"]).endswith(
        "\n\nLemmas that may help:\n```lean\nNat.succ_le_iff : succ n ≤ m ↔ n < m\nNat.lt_irrefl : ¬n < n\n```"
    )


def test_zero_shot_prompt_is_system_and_user() -> None:
    assert [message.role for message in prompt_messages(GOALS)] == ["system", "user"]


def test_few_shot_prompt_puts_examples_between_system_and_user() -> None:
    roles = [message.role for message in prompt_messages(GOALS, few_shot=True)]
    assert roles == ["system", *["user", "assistant"] * len(FEW_SHOT_EXAMPLES), "user"]


def test_few_shot_answers_are_fenced_tactic_blocks() -> None:
    answers = [message.content for message in prompt_messages(GOALS, few_shot=True) if message.role == "assistant"]
    assert answers[0] == "```lean\nintro x y\n```"


def test_prompt_without_thinking_ends_with_the_prefilled_fence() -> None:
    prompt = render_prompt(ChatMlTemplate(), GOALS)
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n```lean\n")


def test_prompt_with_thinking_leaves_the_assistant_turn_to_the_model() -> None:
    assert render_prompt(ChatMlTemplate(), GOALS, thinking=True).endswith("<|im_start|>assistant\n")


def test_prompt_starts_with_our_system_message() -> None:
    assert render_prompt(ChatMlTemplate(), GOALS).startswith(f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>")


def test_completion_closes_the_fence_and_the_turn() -> None:
    assert render_completion("intro x\nsimp") == "intro x\nsimp\n```<|im_end|>"


@pytest.mark.parametrize(("thinking", "stops"), [(False, ("```",)), (True, ())])
def test_only_non_thinking_generation_stops_at_the_fence(thinking: bool, stops: tuple[str, ...]) -> None:
    assert stop_sequences(thinking) == stops


@pytest.mark.parametrize(
    ("text", "block"),
    [
        ("nlinarith [sq_nonneg (a - b)]\n", "nlinarith [sq_nonneg (a - b)]"),
        ("  intro x\n  simp at h  \n", "intro x\nsimp at h"),
        ("\n\nhave h : 0 < 2 := by\n  norm_num\nlinarith\n", "have h : 0 < 2 := by\n  norm_num\nlinarith"),
        ("simp -- no sorry needed\n", "simp -- no sorry needed"),
        ("by\n  intro n hn\n  omega\n", "intro n hn\nomega"),
    ],
)
def test_block_is_dedented_and_stripped(text: str, block: str) -> None:
    assert parse_sample(sample(text), thinking=False) == block


@pytest.mark.parametrize(
    ("text", "finish_reason", "failure"),
    [
        ("nlinarith [sq_nonneg (a", "length", ParseFailure.TRUNCATED),
        ("  \n\n", "stop", ParseFailure.EMPTY),
        ("sorry", "stop", ParseFailure.FORBIDDEN),
        ("norm_num\nexact?", "stop", ParseFailure.FORBIDDEN),
        ("native_decide", "stop", ParseFailure.FORBIDDEN),
    ],
)
def test_unusable_samples_report_why(text: str, finish_reason: str, failure: ParseFailure) -> None:
    assert parse_sample(sample(text, finish_reason=finish_reason), thinking=False) == failure


def test_search_forbidden_steps_extend_the_wrapper_tokens() -> None:
    forbidden = frozenset({"decide"})
    assert parse_sample(sample("decide"), thinking=False, forbidden_tokens=forbidden) == ParseFailure.FORBIDDEN


@pytest.mark.parametrize(
    ("text", "block"),
    [
        ("Use the hypothesis.\n</think>\n\n```lean\nlinarith [h]\n```", "linarith [h]"),
        ("Maybe ```lean\nsimp\n``` works.</think>\n```lean4\nomega\n```\nDone.", "omega"),
        ("</think>\n```lean\nring_nf", "ring_nf"),
    ],
)
def test_thinking_block_is_read_after_the_think_block(text: str, block: str) -> None:
    assert parse_sample(sample(text), thinking=True) == block


@pytest.mark.parametrize("text", ["I think linarith works.\n```lean\nlinarith\n```", "</think>\nJust use linarith."])
def test_thinking_without_a_block_after_the_think_block_fails(text: str) -> None:
    assert parse_sample(sample(text), thinking=True) == ParseFailure.NO_BLOCK


def test_identical_blocks_merge_keeping_the_best_log_probability() -> None:
    parsed = parse_samples([sample("simp", -3.0), sample("  simp\n", -1.5), sample("simp", -2.0)], thinking=False)
    assert [(candidate.tactic_block, candidate.log_probability) for candidate in parsed.candidates] == [("simp", -1.5)]


def test_merged_candidate_carries_the_tokens_of_all_its_samples() -> None:
    parsed = parse_samples([sample("simp", tokens=3), sample("simp", tokens=4)], thinking=False)
    assert (parsed.candidates[0].generated_tokens, parsed.duplicate_samples) == (7, 1)


def test_candidates_are_ordered_most_likely_first() -> None:
    parsed = parse_samples([sample("simp", -4.0), sample("omega", -0.5), sample("ring", -2.0)], thinking=False)
    assert [candidate.tactic_block for candidate in parsed.candidates] == ["omega", "ring", "simp"]


def test_failed_samples_are_counted_with_their_tokens() -> None:
    parsed = parse_samples(
        [sample("sorry", tokens=2), sample("simp", tokens=3), sample("x", tokens=9, finish_reason="length")],
        thinking=False,
    )
    assert (parsed.failures, parsed.failed_generated_tokens) == ((ParseFailure.FORBIDDEN, ParseFailure.TRUNCATED), 11)


def test_samples_that_all_fail_yield_no_candidates() -> None:
    parsed = parse_samples([sample("sorry"), sample("", finish_reason="stop")], thinking=False)
    assert parsed.candidates == ()
