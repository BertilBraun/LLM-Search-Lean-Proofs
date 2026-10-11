"""The value model's chat format: the policy's rendering of the proof state, answered by a single bin token."""

from collections.abc import Sequence
from typing import Protocol

from lean_search.policy.client import ChatMessage
from lean_search.policy.prompts import END_OF_TURN, ChatTemplate, user_message

VALUE_SYSTEM_PROMPT = (
    "You are a Lean 4 and Mathlib expert. Given the current proof state, estimate how many more tactic steps are "
    "needed to finish the proof. Reply with a single token: a number from 1 to 7, 8 for eight or more steps, or dead "
    "if the proof cannot be finished from this state."
)
# Single tokens in the Qwen2.5, Qwen3 and Qwen3.5 tokenizers, also right after the template's generation prompt.
BIN_TOKENS = ("1", "2", "3", "4", "5", "6", "7", "8", "dead")


class ValueTokenizer(ChatTemplate, Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


def value_messages(goals: Sequence[str]) -> list[ChatMessage]:
    return [ChatMessage("system", VALUE_SYSTEM_PROMPT), ChatMessage("user", user_message(goals))]


def render_value_prompt(template: ChatTemplate, goals: Sequence[str]) -> str:
    conversation = [{"role": message.role, "content": message.content} for message in value_messages(goals)]
    # The generation prompt ends after the empty think block, so the assistant turn's first token is the bin.
    return template.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True, enable_thinking=False)


def render_value_target(bin_index: int) -> str:
    return f"{BIN_TOKENS[bin_index]}{END_OF_TURN}"


def bin_token_ids(tokenizer: ValueTokenizer) -> tuple[int, ...]:
    token_ids = []
    for token in BIN_TOKENS:
        encoded = tokenizer.encode(token, add_special_tokens=False)
        if len(encoded) != 1:
            raise ValueError(f"The bin token {token!r} is {len(encoded)} tokens in this tokenizer.")
        token_ids.append(encoded[0])
    return tuple(token_ids)
