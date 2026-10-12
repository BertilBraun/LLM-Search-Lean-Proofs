from lean_search.training.dpo_data import PreferencePair, tokenize_pair

GOALS = ("x : ℝ\n⊢ x + 0 = x",)
THINKING_TURN = "<|im_start|>assistant\n<think>\n"


class TemplateTokenizer:
    """Qwen-like turns: thinking prompts open a think block, other prompts get an empty one."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + (THINKING_TURN if enable_thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n")

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def decoded(token_ids: tuple[int, ...]) -> str:
    return "".join(chr(token_id) for token_id in token_ids)


def thinking_pair() -> PreferencePair:
    return PreferencePair("s", "v1/a.t", 0, GOALS, "simp", "exact foo", "error", "add_zero closes it", "try foo")


def test_a_pair_with_reasoning_is_prompted_in_thinking_mode() -> None:
    tokenized = tokenize_pair(TemplateTokenizer(), thinking_pair())
    prompt = decoded(tokenized.chosen.input_ids[: tokenized.chosen.prompt_token_count])
    assert prompt.endswith(THINKING_TURN)


def test_each_step_completes_with_its_own_reasoning() -> None:
    tokenized = tokenize_pair(TemplateTokenizer(), thinking_pair())
    assert tokenized.rejected is not None
    completions = [
        decoded(example.input_ids[example.prompt_token_count :]) for example in (tokenized.chosen, tokenized.rejected)
    ]
    assert [completion.split("\n</think>")[0] for completion in completions] == ["add_zero closes it", "try foo"]


def test_a_pair_without_reasoning_keeps_the_plain_format() -> None:
    pair = PreferencePair("s", "v1/a.t", 0, GOALS, "simp", None, "none")
    tokenized = tokenize_pair(TemplateTokenizer(), pair)
    prompt = decoded(tokenized.chosen.input_ids[: tokenized.chosen.prompt_token_count])
    assert prompt.endswith("</think>\n\n```lean\n")
