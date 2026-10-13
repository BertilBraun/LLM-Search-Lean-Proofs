import pytest
from reasoning_records import GOALS, execution

from lean_search.policy.prompts import render_thinking_completion, thinking_prefill
from lean_search.reasoning.compression import (
    LengthBounds,
    RewriteConfig,
    RewriteDefect,
    RewriteMode,
    RewriteRequest,
    copies_step,
    restates_goal,
    rewrite_defect,
    rewrite_messages,
    sufficiency_check,
)
from lean_search.reasoning.pipeline import LeanTaskResult
from lean_search.reasoning.reward import RewardConfig, StepOutcome

STEP = "nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]"
GOAL = ("a b : ℝ\nh : a ^ 2 + b ^ 2 = 2\n⊢ a * b + a + b ≤ 3 + a * a * b * b",)
REQUEST = RewriteRequest(GOAL, STEP, "First I expand everything and then I compare the squares ...")


@pytest.mark.parametrize(
    ("text", "finish_reason", "tokens", "defect"),
    [
        ("Squares of a - b and a + b bound the products.", "stop", 12, None),
        ("Squares of a - b and", "length", 320, RewriteDefect.TRUNCATED),
        ("", "stop", 0, RewriteDefect.EMPTY),
        ("Bound it.</think>", "stop", 6, RewriteDefect.THINK_TAG),
        ("Use:\n```lean\nnlinarith\n```", "stop", 8, RewriteDefect.CODE_BLOCK),
        ("Squares bound the products.", "stop", 250, RewriteDefect.TOO_LONG),
        (f"Just {STEP}.", "stop", 20, RewriteDefect.COPIES_STEP),
        ("We must show a * b + a + b ≤ 3 + a * a * b * b here.", "stop", 20, RewriteDefect.RESTATES_GOAL),
    ],
)
def test_rewrite_defects(text: str, finish_reason: str, tokens: int, defect: RewriteDefect | None) -> None:
    assert rewrite_defect(text, finish_reason, tokens, REQUEST, max_accepted_tokens=200) == defect


def test_a_short_quote_of_the_goal_is_no_restatement() -> None:
    assert not restates_goal("Since x = 2, substitute.", ("x : ℕ\n⊢ x = 2",))


def test_naming_the_tactic_is_no_copy_of_the_step() -> None:
    assert not copies_step("nlinarith with the squares of the differences closes it.", STEP)


def test_compression_prompts_contain_the_reasoning() -> None:
    (_, user) = rewrite_messages(REQUEST, RewriteMode.COMPRESS, 150)
    assert REQUEST.reasoning in user.content


def test_rationalization_prompts_contain_no_reasoning() -> None:
    (_, user) = rewrite_messages(REQUEST, RewriteMode.RATIONALIZE, 150)
    assert REQUEST.reasoning not in user.content


@pytest.mark.parametrize("mode", list(RewriteMode))
def test_rewrite_prompts_show_the_state_and_the_step(mode: RewriteMode) -> None:
    (_, user) = rewrite_messages(RewriteRequest(GOALS[0], "subst h₀", ""), mode, 150)
    assert GOALS[0][0] in user.content and "subst h₀" in user.content


def test_the_prefill_is_the_training_target_up_to_the_block() -> None:
    reasoning = "  Substitute a first. "
    assert render_thinking_completion(reasoning, "subst h₀").startswith(thinking_prefill(reasoning) + "subst h₀\n```")


def test_sufficiency_counts_the_samples_whose_block_succeeded() -> None:
    lean = LeanTaskResult("", (execution("omega", StepOutcome.CLOSED), execution("simp", StepOutcome.ERROR)))
    check = sufficiency_check(("omega", "simp", None, "omega"), lean, RewardConfig())
    assert check.successes == 2


def test_a_check_without_a_succeeding_sample_is_insufficient() -> None:
    lean = LeanTaskResult("", (execution("simp", StepOutcome.ERROR),))
    assert not sufficiency_check(("simp", None), lean, RewardConfig()).sufficient


def test_a_state_that_could_not_be_rebuilt_is_insufficient() -> None:
    assert not sufficiency_check(("omega",), LeanTaskResult("replay failed", ()), RewardConfig()).sufficient


CONDENSING = RewriteConfig(
    target_tokens=150,
    max_accepted_tokens=600,
    min_accepted_tokens=100,
    target_ratio=0.5,
    min_accepted_ratio=0.3,
    max_accepted_ratio=0.8,
)


@pytest.mark.parametrize(
    ("config", "original_tokens", "bounds"),
    [
        (RewriteConfig(target_tokens=150, max_accepted_tokens=200), 600, LengthBounds(150, 0, 200, condense=False)),
        (CONDENSING, 600, LengthBounds(300, 180, 480, condense=True)),
        (CONDENSING, 400, LengthBounds(200, 120, 320, condense=True)),
        (CONDENSING, 1000, LengthBounds(500, 300, 600, condense=True)),
        (CONDENSING, 0, LengthBounds(150, 100, 600, condense=False)),
    ],
)
def test_condensing_bounds_follow_the_original_length(
    config: RewriteConfig, original_tokens: int, bounds: LengthBounds
) -> None:
    assert config.bounds(original_tokens) == bounds


def test_rewrites_below_the_minimum_are_too_short() -> None:
    defect = rewrite_defect("Squares bound the products.", "stop", 90, REQUEST, 600, min_accepted_tokens=100)
    assert defect == RewriteDefect.TOO_SHORT


def test_condensing_asks_to_keep_every_step() -> None:
    (_, user) = rewrite_messages(REQUEST, RewriteMode.COMPRESS, 300, condense=True)
    assert "keep every mathematical step" in user.content and "about 300 tokens" in user.content
