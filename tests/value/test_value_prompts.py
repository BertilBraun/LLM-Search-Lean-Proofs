import functools

import pytest

from lean_search.policy.expander import load_tokenizer
from lean_search.policy.prompts import user_message
from lean_search.value.bins import BIN_COUNT, DEAD_BIN
from lean_search.value.prompts import (
    BIN_TOKENS,
    VALUE_SYSTEM_PROMPT,
    ValueTokenizer,
    bin_token_ids,
    render_value_prompt,
    render_value_target,
    value_messages,
)

GOALS = ("x : ℕ\nh : x + 1 = 3\n⊢ x = 2", "case right\n⊢ 0 < 1")
VALUE_MODELS = ("Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-2B-Base", "Qwen/Qwen3-1.7B", "Qwen/Qwen2.5-Math-1.5B")


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


@functools.cache
def cached_tokenizer(repository: str) -> ValueTokenizer:
    try:
        return load_tokenizer(repository)
    except OSError:
        pytest.skip(f"{repository} is not in the Hugging Face cache")


def test_value_prompt_is_system_and_user() -> None:
    assert [(message.role, message.content) for message in value_messages(GOALS)] == [
        ("system", VALUE_SYSTEM_PROMPT),
        ("user", user_message(GOALS)),
    ]


def test_value_prompt_ends_with_an_empty_think_block() -> None:
    assert render_value_prompt(ChatMlTemplate(), GOALS).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def test_value_target_is_the_bin_token_and_the_end_of_turn() -> None:
    assert render_value_target(DEAD_BIN) == "dead<|im_end|>"


@pytest.mark.parametrize("repository", VALUE_MODELS)
def test_bin_tokens_are_distinct_single_tokens(repository: str) -> None:
    assert len(set(bin_token_ids(cached_tokenizer(repository)))) == BIN_COUNT


@pytest.mark.parametrize("repository", VALUE_MODELS)
@pytest.mark.parametrize("bin_index", range(BIN_COUNT))
def test_the_bin_token_is_the_next_token_after_the_prompt(repository: str, bin_index: int) -> None:
    tokenizer = cached_tokenizer(repository)
    prompt = render_value_prompt(tokenizer, GOALS)
    prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
    target_ids = tokenizer.encode(prompt + BIN_TOKENS[bin_index], add_special_tokens=False)
    assert target_ids == [*prompt_ids, bin_token_ids(tokenizer)[bin_index]]


@pytest.mark.parametrize("repository", VALUE_MODELS)
def test_prompt_and_target_are_the_rendered_conversation(repository: str) -> None:
    tokenizer = cached_tokenizer(repository)
    conversation = [{"role": message.role, "content": message.content} for message in value_messages(GOALS)]
    conversation.append({"role": "assistant", "content": BIN_TOKENS[2]})
    rendered = tokenizer.apply_chat_template(conversation, tokenize=False, enable_thinking=False)
    assert render_value_prompt(tokenizer, GOALS) + render_value_target(2) + "\n" == rendered
