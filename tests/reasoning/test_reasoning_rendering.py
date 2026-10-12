import pytest

from lean_search.policy.expander import PolicyTokenizer, load_tokenizer
from lean_search.policy.prompts import (
    BRIEF_THINKING_INSTRUCTION,
    END_OF_TURN,
    assistant_message,
    prompt_messages,
    render_prompt,
    render_thinking_completion,
)
from lean_search.reasoning.dataset import ReasoningExample, tokenize_reasoning_example
from lean_search.training.sft_data import IGNORE_INDEX, SftExample, tokenize_example

MODEL = "Qwen/Qwen3.5-2B"
GOALS = ("a b : ℝ\nh₀ : a + b = 3\nh₁ : a - b = 1\n⊢ a = 2",)
BLOCK = "linarith [h₀, h₁]"
REASONINGS = (
    "Adding the two hypotheses gives 2a = 4.",
    "\n  Two linear equations.\nTry:\n```lean\nnlinarith\n```\nNo: linarith is enough.  \n\n",
    "**Plan**: eliminate b.",
)


class CharacterTokenizer:
    """Qwen3.5's generation prompt (an opened think block with thinking on), one token per character."""

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + (
            "<|im_start|>assistant\n<think>\n" if enable_thinking else "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]


def decode(token_ids: tuple[int, ...]) -> str:
    return "".join(chr(token_id) for token_id in token_ids)


INSTRUCTIONS = ("", BRIEF_THINKING_INSTRUCTION)


def thinking_example(reasoning: str = REASONINGS[0], instruction: str = "") -> ReasoningExample:
    return ReasoningExample("test", "test/0", 0, GOALS, BLOCK, reasoning, instruction)


def test_thinking_completion_is_reasoning_closing_tag_and_block() -> None:
    assert (
        render_thinking_completion("  Add them.\n", BLOCK)
        == f"Add them.\n</think>\n\n```lean\n{BLOCK}\n```{END_OF_TURN}"
    )


def test_thinking_prompt_ends_in_the_opened_think_block() -> None:
    tokenized = tokenize_reasoning_example(CharacterTokenizer(), thinking_example())
    assert decode(tokenized.input_ids[: tokenized.prompt_token_count]).endswith("<|im_start|>assistant\n<think>\n")


def test_loss_covers_reasoning_and_block_but_not_the_prompt() -> None:
    tokenized = tokenize_reasoning_example(CharacterTokenizer(), thinking_example())
    trained = tuple(label for label in tokenized.labels if label != IGNORE_INDEX)
    assert decode(trained) == render_thinking_completion(REASONINGS[0], BLOCK)


def test_replay_examples_use_the_non_thinking_format() -> None:
    tokenizer = CharacterTokenizer()
    replay = ReasoningExample("test", "test/0", 0, GOALS, BLOCK, None, "")
    assert tokenize_reasoning_example(tokenizer, replay).input_ids == (
        tokenize_example(tokenizer, SftExample("test", "test/0", 0, GOALS, BLOCK)).input_ids
    )


def test_the_thinking_instruction_extends_the_system_prompt_of_thinking_prompts() -> None:
    prompt = render_prompt(CharacterTokenizer(), GOALS, thinking=True, thinking_instruction=BRIEF_THINKING_INSTRUCTION)
    assert f"{BRIEF_THINKING_INSTRUCTION}<|im_end|>\n<|im_start|>user" in prompt


def test_the_thinking_instruction_leaves_non_thinking_prompts_alone() -> None:
    tokenizer = CharacterTokenizer()
    instructed = render_prompt(tokenizer, GOALS, thinking=False, thinking_instruction=BRIEF_THINKING_INSTRUCTION)
    assert instructed == render_prompt(tokenizer, GOALS)


def test_thinking_examples_are_rendered_with_their_instruction() -> None:
    tokenizer = CharacterTokenizer()
    tokenized = tokenize_reasoning_example(tokenizer, thinking_example(instruction=BRIEF_THINKING_INSTRUCTION))
    prompt = render_prompt(tokenizer, GOALS, thinking=True, thinking_instruction=BRIEF_THINKING_INSTRUCTION)
    assert decode(tokenized.input_ids[: tokenized.prompt_token_count]) == prompt


@pytest.fixture(scope="module")
def qwen_tokenizer() -> PolicyTokenizer:
    try:
        return load_tokenizer(MODEL)
    except OSError:
        pytest.skip(f"{MODEL} is not in the Hugging Face cache")


def conversation_with_reasoning(reasoning: str, instruction: str = "") -> list[dict[str, str]]:
    messages = prompt_messages(GOALS, system_instruction=instruction)
    conversation = [{"role": message.role, "content": message.content} for message in messages]
    conversation.append({"role": "assistant", "content": assistant_message(BLOCK), "reasoning_content": reasoning})
    return conversation


@pytest.mark.parametrize("instruction", INSTRUCTIONS)
@pytest.mark.parametrize("reasoning", REASONINGS)
def test_rendering_is_the_chat_template_with_reasoning_content(
    qwen_tokenizer: PolicyTokenizer, reasoning: str, instruction: str
) -> None:
    rendered = qwen_tokenizer.apply_chat_template(
        conversation_with_reasoning(reasoning, instruction), tokenize=False, enable_thinking=True
    )
    prompt = render_prompt(qwen_tokenizer, GOALS, thinking=True, thinking_instruction=instruction)
    assert prompt + render_thinking_completion(reasoning, BLOCK) + "\n" == rendered


@pytest.mark.parametrize("reasoning", REASONINGS)
def test_rendering_is_the_chat_template_with_the_think_block_in_the_content(
    qwen_tokenizer: PolicyTokenizer, reasoning: str
) -> None:
    conversation = conversation_with_reasoning(reasoning)
    del conversation[-1]["reasoning_content"]
    conversation[-1]["content"] = f"<think>\n{reasoning}\n</think>\n\n{assistant_message(BLOCK)}"
    rendered = qwen_tokenizer.apply_chat_template(conversation, tokenize=False, enable_thinking=True)
    rendering = render_prompt(qwen_tokenizer, GOALS, thinking=True) + render_thinking_completion(reasoning, BLOCK)
    assert rendering + "\n" == rendered


@pytest.mark.parametrize("instruction", INSTRUCTIONS)
@pytest.mark.parametrize("reasoning", REASONINGS)
def test_prompt_and_completion_tokens_are_the_tokens_of_the_whole_text(
    qwen_tokenizer: PolicyTokenizer, reasoning: str, instruction: str
) -> None:
    tokenized = tokenize_reasoning_example(qwen_tokenizer, thinking_example(reasoning, instruction))
    prompt = render_prompt(qwen_tokenizer, GOALS, thinking=True, thinking_instruction=instruction)
    whole = prompt + render_thinking_completion(reasoning, BLOCK)
    assert list(tokenized.input_ids) == qwen_tokenizer.encode(whole, add_special_tokens=False)


def test_qwen_loss_covers_exactly_the_completion(qwen_tokenizer: PolicyTokenizer) -> None:
    tokenized = tokenize_reasoning_example(qwen_tokenizer, thinking_example())
    trained = [label for label in tokenized.labels if label != IGNORE_INDEX]
    assert qwen_tokenizer.decode(trained) == render_thinking_completion(REASONINGS[0], BLOCK)
