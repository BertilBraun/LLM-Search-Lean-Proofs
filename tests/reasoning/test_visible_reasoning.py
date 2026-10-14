import dataclasses

import pytest
from reasoning_records import execution, first_state, sample_record, state_record
from test_reasoning_rendering import BLOCK, GOALS, MODEL, CharacterTokenizer, decode

from lean_search.policy.client import Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import PolicyTokenizer, load_tokenizer
from lean_search.policy.prompts import (
    END_OF_TURN,
    VISIBLE_SYSTEM_PROMPT,
    forced_sample,
    parse_sample,
    render_prompt,
    render_visible_completion,
    stop_sequences,
    truncated_before_answer,
    user_message,
    visible_explanation,
)
from lean_search.reasoning.dataset import (
    ReasoningExample,
    ReasoningOrigin,
    SelectionConfig,
    reasoning_example,
    select_samples,
    tokenize_reasoning_example,
)
from lean_search.reasoning.pipeline import sample_record as record_of
from lean_search.reasoning.records import StateSamples
from lean_search.reasoning.reward import RewardConfig, StepOutcome
from lean_search.search.config import parse_run_config
from lean_search.training.sft_data import IGNORE_INDEX

EXPLANATION = "Adding the two hypotheses gives 2a = 4, so a linear combination closes the goal."
VISIBLE_TEXT = f"{EXPLANATION}\n\n```lean\n{BLOCK}\n```"


def sample(text: str, finish_reason: str = "stop", tokens: int = 30) -> Sample:
    return Sample(text, -2.0, tokens, finish_reason)


def visible_example() -> ReasoningExample:
    return ReasoningExample("test", "test/0", 0, GOALS, BLOCK, EXPLANATION, "", ReasoningOrigin.SAMPLED, visible=True)


def test_the_visible_prompt_asks_for_an_explanation_with_thinking_off() -> None:
    prompt = render_prompt(CharacterTokenizer(), GOALS, visible=True)
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n") and VISIBLE_SYSTEM_PROMPT in prompt


def test_the_visible_prompt_does_not_prefill_the_block() -> None:
    assert not render_prompt(CharacterTokenizer(), GOALS, visible=True).endswith("```lean\n")


def test_visible_generation_runs_to_its_end_of_turn() -> None:
    assert stop_sequences(False, visible=True) == ()


@pytest.mark.parametrize(
    ("text", "finish_reason", "expected"),
    [
        (VISIBLE_TEXT, "stop", BLOCK),
        (f"{VISIBLE_TEXT}\nThen `ring` would also do.\n```lean\nring\n```", "stop", BLOCK),
        (f"{VISIBLE_TEXT}\nAnd then I keep on writing until the c", "length", BLOCK),
    ],
)
def test_the_first_block_after_the_explanation_is_the_step(text: str, finish_reason: str, expected: str) -> None:
    assert parse_sample(sample(text, finish_reason), thinking=False, visible=True) == expected


@pytest.mark.parametrize("text", [EXPLANATION, f"{EXPLANATION}\n\n```lean\nlinarith [h₀"])
def test_a_visible_sample_cut_off_before_its_block_closes_is_truncated(text: str) -> None:
    assert not isinstance(parse_sample(sample(text, "length"), thinking=False, visible=True), str)


def test_the_explanation_is_the_text_before_the_block() -> None:
    assert visible_explanation(VISIBLE_TEXT) == EXPLANATION


@pytest.mark.parametrize(("text", "forced"), [(EXPLANATION, True), (f"{EXPLANATION}\n\n```lean\nlinarith [h₀", False)])
def test_only_samples_cut_off_before_any_block_are_forced(text: str, forced: bool) -> None:
    assert truncated_before_answer(sample(text, "length"), visible=True) == forced


def test_a_forced_visible_sample_parses_to_the_continuations_block() -> None:
    forced = forced_sample(sample(EXPLANATION, "length", 1024), sample(f"{BLOCK}\n", "stop", 6), visible=True)
    assert parse_sample(forced, thinking=False, visible=True) == BLOCK


def test_visible_completion_is_explanation_then_block() -> None:
    assert render_visible_completion(f"  {EXPLANATION}\n", BLOCK) == f"{VISIBLE_TEXT}{END_OF_TURN}"


def test_visible_examples_train_on_explanation_and_block() -> None:
    tokenized = tokenize_reasoning_example(CharacterTokenizer(), visible_example())
    trained = tuple(label for label in tokenized.labels if label != IGNORE_INDEX)
    assert decode(trained) == render_visible_completion(EXPLANATION, BLOCK)


def test_visible_examples_use_the_visible_prompt() -> None:
    tokenizer = CharacterTokenizer()
    tokenized = tokenize_reasoning_example(tokenizer, visible_example())
    assert decode(tokenized.input_ids[: tokenized.prompt_token_count]) == render_prompt(tokenizer, GOALS, visible=True)


def test_sampled_visible_reasoning_becomes_a_visible_example() -> None:
    tokenizer = CharacterTokenizer()
    record = record_of(0, sample(VISIBLE_TEXT), False, tokenizer, visible=True)
    sampled = StateSamples(first_state(), False, "", 100, 0, 1024, 1.0, (record,), visible=True)
    example = reasoning_example(sampled, record)
    assert (example.visible, example.reasoning, example.tactic_block) == (True, EXPLANATION, BLOCK)


def test_forced_samples_are_not_selected_for_training() -> None:
    forced = dataclasses.replace(sample_record(0, "omega", 40), forced=True)
    record = state_record([forced], [execution("omega", StepOutcome.CLOSED)])
    assert select_samples(record, RewardConfig(), SelectionConfig(max_per_state=2, min_reasoning_tokens=16)) == []


POLICY = '[expander]\nkind = "automation_then_policy"\n\n[policy]\nmodel = "m"\ntokenizer = "t"\n'


@pytest.mark.parametrize("extra", ["thinking = true\n", "few_shot = true\n"])
def test_visible_reasoning_excludes_thinking_and_few_shot(extra: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(POLICY + "visible_reasoning = true\n" + extra)


def test_a_visible_policy_section_is_parsed() -> None:
    config = parse_run_config(POLICY + "visible_reasoning = true\nfew_shot = false\n")
    assert (config.policy.visible_reasoning, config.policy.reasons) == (True, True)


def test_visible_reasoning_is_off_by_default() -> None:
    assert not PolicyConfig().visible_reasoning


@pytest.fixture(scope="module")
def qwen_tokenizer() -> PolicyTokenizer:
    try:
        return load_tokenizer(MODEL)
    except OSError:
        pytest.skip(f"{MODEL} is not in the Hugging Face cache")


def test_visible_rendering_is_the_chat_template_with_thinking_off(qwen_tokenizer: PolicyTokenizer) -> None:
    conversation = [
        {"role": "system", "content": VISIBLE_SYSTEM_PROMPT},
        {"role": "user", "content": user_message(GOALS)},
        {"role": "assistant", "content": VISIBLE_TEXT},
    ]
    rendered = qwen_tokenizer.apply_chat_template(conversation, tokenize=False, enable_thinking=False)
    prompt = render_prompt(qwen_tokenizer, GOALS, visible=True)
    assert prompt + render_visible_completion(EXPLANATION, BLOCK) + "\n" == rendered
