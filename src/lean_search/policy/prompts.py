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


def prompt_messages(goals: Sequence[str], lemmas: Sequence[str] = (), *, few_shot: bool = False) -> list[ChatMessage]:
    messages = [ChatMessage("system", SYSTEM_PROMPT)]
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
) -> str:
    conversation = [
        {"role": message.role, "content": message.content}
        for message in prompt_messages(goals, lemmas, few_shot=few_shot)
    ]
    text = template.apply_chat_template(
        conversation, tokenize=False, add_generation_prompt=True, enable_thinking=thinking
    )
    # A think block cannot be prefilled into, so with thinking the model writes the fence itself.
    return text if thinking else text + ASSISTANT_PREFILL


def render_completion(tactic_block: str) -> str:
    return f"{tactic_block}\n{FENCE}{END_OF_TURN}"


def render_thinking_completion(reasoning: str, tactic_block: str) -> str:
    """SFT target after a thinking prompt (which ends in the opened think block): reasoning, block, end of turn."""
    # Qwen3.5's chat template trims an assistant turn's reasoning the same way.
    return f"{reasoning.strip()}\n{THINK_END}\n\n{assistant_message(tactic_block)}{END_OF_TURN}"


def stop_sequences(thinking: bool) -> tuple[str, ...]:
    # A thinking model may write fences while it thinks, so it runs to its end of turn instead.
    return () if thinking else (FENCE,)


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


def generated_block(text: str, thinking: bool) -> str | None:
    if not thinking:
        return text
    _, think_end, answer = text.rpartition(THINK_END)
    if not think_end:
        return None
    _, fence, after_fence = answer.partition(FENCE)
    if not fence:
        return None
    # Skips the info string of the opening fence, usually "lean".
    return after_fence.partition("\n")[2].partition(FENCE)[0]


def parse_sample(
    sample: Sample, *, thinking: bool, forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS
) -> str | ParseFailure:
    """The normalized tactic block of one sample, or why it cannot be used."""
    if sample.finish_reason == LENGTH_FINISH_REASON:
        return ParseFailure.TRUNCATED
    block = generated_block(sample.text, thinking)
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


@dataclass(frozen=True)
class ParsedSamples:
    candidates: tuple[TacticCandidate, ...]
    failures: tuple[ParseFailure, ...]
    failed_generated_tokens: int

    @property
    def duplicate_samples(self) -> int:
        return sum(candidate.sample_count - 1 for candidate in self.candidates)


def parse_samples(
    samples: Sequence[Sample], *, thinking: bool, forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS
) -> ParsedSamples:
    """Distinct usable tactic blocks, most likely first; identical blocks merge and keep the best log-probability."""
    candidates: dict[str, TacticCandidate] = {}
    failures: list[ParseFailure] = []
    failed_generated_tokens = 0
    for sample in samples:
        match parse_sample(sample, thinking=thinking, forbidden_tokens=forbidden_tokens):
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
                )
            case str() as block:
                candidates[block] = TacticCandidate(block, sample.cumulative_logprob, sample.token_count, 1)
    ordered = sorted(candidates.values(), key=lambda candidate: -candidate.log_probability)
    return ParsedSamples(tuple(ordered), tuple(failures), failed_generated_tokens)
