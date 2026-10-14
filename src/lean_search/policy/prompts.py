"""The policy's chat format (shared by every model, the search and SFT data) and parsing of its replies."""

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from lean_search.lean.text import FORBIDDEN_TOKENS, find_forbidden_tokens
from lean_search.policy.client import ChatMessage, Sample

SYSTEM_PROMPT = (
    "You are a Lean 4 and Mathlib expert. Given the current proof state, write the next tactic or tactics that make "
    "progress on it. Reply with a single ```lean code block that contains only tactics."
)
# Visible reasoning: thinking off, a short explanation in the reply itself, then the block.
VISIBLE_SYSTEM_PROMPT = (
    "You are a Lean 4 and Mathlib expert. Given the current proof state, briefly explain the key idea (a few "
    "sentences), then give the next tactic or tactics that make progress on it in a single ```lean code block that "
    "contains only tactics."
)
# Optionally appended to the system prompt in thinking mode to keep the thoughts short.
BRIEF_THINKING_INSTRUCTION = "Think briefly (a few sentences) about which tactic to use; do not restate the goal."
ASSISTANT_PREFILL = "```lean\n"
FENCE = "```"
END_OF_TURN = "<|im_end|>"
THINK_START = "<think>"
THINK_END = "</think>"
LENGTH_FINISH_REASON = "length"


@dataclass(frozen=True)
class FewShotExample:
    goals: tuple[str, ...]
    tactic_block: str


# Steps of traced train-split Lean Workbook proofs: introduce binders, destructure, prove an auxiliary fact, close.
FEW_SHOT_EXAMPLES = (
    FewShotExample(
        goals=("⊢ ∀ (x y : ℝ), x.sin * y.sin = 1 / 2 * ((x - y).cos - (x + y).cos)",),
        tactic_block="intro x y",
    ),
    FewShotExample(
        goals=("h : ∃ x, x ^ 2 ≡ 2 [ZMOD 4]\n⊢ False",),
        tactic_block="rcases h with ⟨x, hx⟩",
    ),
    FewShotExample(
        goals=("a : ℝ\nha : a ^ 2 - 3 * a + 1 = 0\n⊢ a ^ 3 / (a ^ 6 + 1) = 1 / 18",),
        tactic_block="have h₁ : a^6 + 1 ≠ 0 := by\n  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)]",
    ),
    FewShotExample(
        goals=("a b : ℝ\nhab : a > 0 ∧ b > 0\nh : a ^ 3 + b ^ 3 = a - b\n⊢ a ^ 2 + b ^ 2 < 1",),
        tactic_block="nlinarith [sq_nonneg (a - 1), sq_nonneg (b - 1), h, sq_nonneg (a - b)]",
    ),
)


class ChatTemplate(Protocol):
    """The part of a Hugging Face tokenizer that renders prompts."""

    def apply_chat_template(
        self,
        conversation: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
        enable_thinking: bool,
    ) -> str: ...


def user_message(goals: Sequence[str], lemmas: Sequence[str] = ()) -> str:
    sections = ["Proof state:\n```lean\n" + "\n\n".join(goals) + "\n```"]
    if lemmas:
        sections.append("Lemmas that may help:\n```lean\n" + "\n".join(lemmas) + "\n```")
    return "\n\n".join(sections)


def assistant_message(tactic_block: str) -> str:
    return f"{ASSISTANT_PREFILL}{tactic_block}\n{FENCE}"


def system_prompt(instruction: str = "") -> str:
    return f"{SYSTEM_PROMPT} {instruction}" if instruction else SYSTEM_PROMPT


def prompt_messages(
    goals: Sequence[str], lemmas: Sequence[str] = (), *, few_shot: bool = False, system_instruction: str = ""
) -> list[ChatMessage]:
    messages = [ChatMessage("system", system_prompt(system_instruction))]
    if few_shot:
        for example in FEW_SHOT_EXAMPLES:
            messages.append(ChatMessage("user", user_message(example.goals)))
            messages.append(ChatMessage("assistant", assistant_message(example.tactic_block)))
    messages.append(ChatMessage("user", user_message(goals, lemmas)))
    return messages


def render_prompt(
    template: ChatTemplate,
    goals: Sequence[str],
    lemmas: Sequence[str] = (),
    *,
    few_shot: bool = False,
    thinking: bool = False,
    thinking_instruction: str = "",
    visible: bool = False,
) -> str:
    """`thinking_instruction` extends the system prompt in thinking mode only."""
    if visible:
        assert not thinking and not few_shot
        conversation = [
            {"role": "system", "content": VISIBLE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message(goals, lemmas)},
        ]
        return template.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
    instruction = thinking_instruction if thinking else ""
    conversation = [
        {"role": message.role, "content": message.content}
        for message in prompt_messages(goals, lemmas, few_shot=few_shot, system_instruction=instruction)
    ]
    text = template.apply_chat_template(
        conversation, tokenize=False, add_generation_prompt=True, enable_thinking=thinking
    )
    # A think block cannot be prefilled into, so with thinking the model writes the fence itself.
    return text if thinking else text + ASSISTANT_PREFILL


def render_completion(tactic_block: str) -> str:
    return f"{tactic_block}\n{FENCE}{END_OF_TURN}"


def thinking_prefill(reasoning: str) -> str:
    """Given thoughts after a thinking prompt, up to the opened block: the model continues with the tactics."""
    # Qwen3.5's chat template trims an assistant turn's reasoning the same way.
    return f"{reasoning.strip()}\n{THINK_END}\n\n{ASSISTANT_PREFILL}"


def render_thinking_completion(reasoning: str, tactic_block: str) -> str:
    """SFT target after a thinking prompt (which ends in the opened think block): reasoning, block, end of turn."""
    return f"{thinking_prefill(reasoning)}{tactic_block}\n{FENCE}{END_OF_TURN}"


def visible_prefill(explanation: str) -> str:
    """Given an explanation after a visible-reasoning prompt, up to the opened block."""
    return f"{explanation.strip()}\n\n{ASSISTANT_PREFILL}"


def render_visible_completion(explanation: str, tactic_block: str) -> str:
    """SFT target after a visible-reasoning prompt: the explanation, the block, end of turn (loss on all of it)."""
    return f"{visible_prefill(explanation)}{tactic_block}\n{FENCE}{END_OF_TURN}"


def visible_explanation(text: str) -> str:
    return text.partition(FENCE)[0].strip()


def stop_sequences(thinking: bool, visible: bool = False) -> tuple[str, ...]:
    # A model that reasons may write fences before its answer, so it runs to its end of turn instead.
    return () if thinking or visible else (FENCE,)


def truncated_in_thinking(sample: Sample) -> bool:
    return sample.finish_reason == LENGTH_FINISH_REASON and THINK_END not in sample.text


def truncated_before_answer(sample: Sample, *, visible: bool) -> bool:
    """Cut off inside the thoughts, or (visible reasoning) inside the explanation before any block opened."""
    if visible:
        return sample.finish_reason == LENGTH_FINISH_REASON and FENCE not in sample.text
    return truncated_in_thinking(sample)


def answer_prefix(truncated: Sample, *, visible: bool) -> str:
    return visible_prefill(truncated.text) if visible else thinking_prefill(truncated.text)


def forced_answer_prompt(prompt: str, truncated: Sample, *, visible: bool = False) -> str:
    """The prompt and the cut-off reasoning, closed, up to the opened block."""
    return prompt + answer_prefix(truncated, visible=visible)


def forced_sample(truncated: Sample, continuation: Sample, *, visible: bool = False) -> Sample:
    """The cut-off sample with its reasoning closed and the forced block: it parses like any other sample."""
    return Sample(
        text=f"{answer_prefix(truncated, visible=visible)}{continuation.text}\n{FENCE}",
        cumulative_logprob=truncated.cumulative_logprob + continuation.cumulative_logprob,
        token_count=truncated.token_count + continuation.token_count,
        finish_reason=continuation.finish_reason,
    )


class ParseFailure(Enum):
    TRUNCATED = "truncated"
    NO_BLOCK = "no_block"
    EMPTY = "empty"
    FORBIDDEN = "forbidden"


def normalize_tactic_block(text: str) -> str:
    lines = [line.rstrip() for line in text.strip("\n").split("\n")]
    # Models sometimes open the block with the `by` that already precedes the proof.
    if lines[0].strip() == "by":
        lines = lines[1:]
    return textwrap.dedent("\n".join(lines)).strip("\n")


def generated_block(text: str, thinking: bool, visible: bool = False) -> str | None:
    if not thinking and not visible:
        return text
    if thinking:
        _, think_end, answer = text.rpartition(THINK_END)
        if not think_end:
            return None
    else:
        answer = text
    _, fence, after_fence = answer.partition(FENCE)
    if not fence:
        return None
    # Skips the info string of the opening fence, usually "lean".
    return after_fence.partition("\n")[2].partition(FENCE)[0]


def closed_visible_block(text: str) -> bool:
    _, fence, after_fence = text.partition(FENCE)
    return bool(fence) and FENCE in after_fence


def parse_sample(
    sample: Sample,
    *,
    thinking: bool,
    forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS,
    visible: bool = False,
) -> str | ParseFailure:
    """The normalized tactic block of one sample, or why it cannot be used."""
    # A visible-reasoning sample cannot stop at the fence that opens its block, so it may run on after closing it.
    complete_visible = visible and closed_visible_block(sample.text)
    if sample.finish_reason == LENGTH_FINISH_REASON and not complete_visible:
        return ParseFailure.TRUNCATED
    block = generated_block(sample.text, thinking, visible)
    if block is None:
        return ParseFailure.NO_BLOCK
    block = normalize_tactic_block(block)
    if not block:
        return ParseFailure.EMPTY
    if find_forbidden_tokens(block, forbidden_tokens):
        return ParseFailure.FORBIDDEN
    return block


@dataclass(frozen=True)
class TacticCandidate:
    tactic_block: str
    # The highest log-probability among the samples that produced this block.
    log_probability: float
    generated_tokens: int
    sample_count: int
    # Samples behind the block whose answer was forced after their thoughts were cut off.
    forced_sample_count: int = 0

    @property
    def forced(self) -> bool:
        return self.forced_sample_count == self.sample_count


@dataclass(frozen=True)
class ParsedSamples:
    candidates: tuple[TacticCandidate, ...]
    failures: tuple[ParseFailure, ...]
    failed_generated_tokens: int

    @property
    def duplicate_samples(self) -> int:
        return sum(candidate.sample_count - 1 for candidate in self.candidates)


def parse_samples(
    samples: Sequence[Sample],
    *,
    thinking: bool,
    forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS,
    forced_indices: frozenset[int] = frozenset(),
    visible: bool = False,
) -> ParsedSamples:
    """Distinct usable tactic blocks, most likely first; identical blocks merge and keep the best log-probability."""
    candidates: dict[str, TacticCandidate] = {}
    failures: list[ParseFailure] = []
    failed_generated_tokens = 0
    for index, sample in enumerate(samples):
        forced = int(index in forced_indices)
        match parse_sample(sample, thinking=thinking, forbidden_tokens=forbidden_tokens, visible=visible):
            case ParseFailure() as failure:
                failures.append(failure)
                failed_generated_tokens += sample.token_count
            case str() as block if block in candidates:
                earlier = candidates[block]
                candidates[block] = TacticCandidate(
                    block,
                    max(earlier.log_probability, sample.cumulative_logprob),
                    earlier.generated_tokens + sample.token_count,
                    earlier.sample_count + 1,
                    earlier.forced_sample_count + forced,
                )
            case str() as block:
                candidates[block] = TacticCandidate(block, sample.cumulative_logprob, sample.token_count, 1, forced)
    ordered = sorted(candidates.values(), key=lambda candidate: -candidate.log_probability)
    return ParsedSamples(tuple(ordered), tuple(failures), failed_generated_tokens)
