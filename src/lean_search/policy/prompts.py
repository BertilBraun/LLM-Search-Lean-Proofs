"""The policy's chat format (shared by every model, the search and SFT data) and parsing of its replies."""

import itertools
import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from lean_search.lean.text import FORBIDDEN_TOKENS, find_forbidden_tokens
from lean_search.policy.client import ChatMessage, Sample
from lean_search.search.texts import CharacterSpan, InsertedSpan, SampledTokens, TokenSpan

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
FEEDBACK_HEADING = "These attempts failed here (fix one or try something else):"
REWRITE_PATTERN_FAILURE = "did not find instance of the pattern"
TYPE_LABELS = frozenset({"has type", "but is expected to have type"})


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


@dataclass(frozen=True)
class FailedAttempt:
    """A block tried at the state and Lean's error, both already cut to the prompt's length."""

    tactic_block: str
    error: str


def shortened(text: str, max_characters: int) -> str:
    return text if len(text) <= max_characters else text[: max_characters - 1].rstrip() + "…"


def error_summary(message: str) -> str:
    """Lean's error without the goal dump that follows it: the first line, plus the pattern a failed `rw` looked for
    and a mismatch's actual and expected types."""
    lines = message.strip().splitlines()
    kept = lines[:1]
    for index, line in enumerate(lines):
        if index == 0 and REWRITE_PATTERN_FAILURE in line:
            kept.extend(indented_after(lines, index))
        elif index > 0 and line.strip() in TYPE_LABELS:
            kept.extend([line.strip(), *indented_after(lines, index)])
    return "\n".join(kept)


def indented_after(lines: Sequence[str], index: int) -> list[str]:
    return list(itertools.takewhile(lambda line: line.startswith(" "), lines[index + 1 :]))


def user_message(
    goals: Sequence[str],
    lemmas: Sequence[str] = (),
    *,
    failed_tactics: Sequence[str] = (),
    failed_attempts: Sequence[FailedAttempt] = (),
) -> str:
    sections = ["Proof state:\n```lean\n" + "\n\n".join(goals) + "\n```"]
    if lemmas:
        sections.append("Lemmas that may help:\n```lean\n" + "\n".join(lemmas) + "\n```")
    if failed_tactics:
        sections.append("Already tried here without success: " + ", ".join(failed_tactics))
    if failed_attempts:
        attempts = [f"```lean\n{attempt.tactic_block}\n```\nError: {attempt.error}" for attempt in failed_attempts]
        sections.append(FEEDBACK_HEADING + "\n\n" + "\n\n".join(attempts))
    return "\n\n".join(sections)


def assistant_message(tactic_block: str) -> str:
    return f"{ASSISTANT_PREFILL}{tactic_block}\n{FENCE}"


def system_prompt(instruction: str = "") -> str:
    return f"{SYSTEM_PROMPT} {instruction}" if instruction else SYSTEM_PROMPT


def prompt_messages(
    goals: Sequence[str],
    lemmas: Sequence[str] = (),
    *,
    few_shot: bool = False,
    system_instruction: str = "",
    failed_tactics: Sequence[str] = (),
    failed_attempts: Sequence[FailedAttempt] = (),
) -> list[ChatMessage]:
    messages = [ChatMessage("system", system_prompt(system_instruction))]
    if few_shot:
        for example in FEW_SHOT_EXAMPLES:
            messages.append(ChatMessage("user", user_message(example.goals)))
            messages.append(ChatMessage("assistant", assistant_message(example.tactic_block)))
    content = user_message(goals, lemmas, failed_tactics=failed_tactics, failed_attempts=failed_attempts)
    messages.append(ChatMessage("user", content))
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
    failed_tactics: Sequence[str] = (),
    failed_attempts: Sequence[FailedAttempt] = (),
) -> str:
    """`thinking_instruction` extends the system prompt in thinking mode only. `failed_tactics`: the automation that
    failed at the state; `failed_attempts`: the policy's failed blocks there (the feedback round)."""
    if visible:
        assert not thinking and not few_shot
        content = user_message(goals, lemmas, failed_tactics=failed_tactics, failed_attempts=failed_attempts)
        conversation = [
            {"role": "system", "content": VISIBLE_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        return template.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
    instruction = thinking_instruction if thinking else ""
    messages = prompt_messages(
        goals,
        lemmas,
        few_shot=few_shot,
        system_instruction=instruction,
        failed_tactics=failed_tactics,
        failed_attempts=failed_attempts,
    )
    conversation = [{"role": message.role, "content": message.content} for message in messages]
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


def answer_opening(*, visible: bool) -> str:
    """What budget forcing inserts after reasoning cut off by the token cap: the reasoning closed, the block opened."""
    return f"\n\n{ASSISTANT_PREFILL}" if visible else f"\n{THINK_END}\n\n{ASSISTANT_PREFILL}"


def forced_answer_prompt(
    prompt_token_ids: Sequence[int], truncated: Sample, opening_token_ids: Sequence[int]
) -> tuple[int, ...]:
    """The prompt, the cut-off sample's own tokens and the opening: the record holds exactly what the model saw."""
    return (*prompt_token_ids, *truncated.tokens.token_ids, *opening_token_ids)


def forced_sample(
    truncated: Sample, opening_token_ids: Sequence[int], continuation: Sample, *, visible: bool = False
) -> Sample:
    """The cut-off sample, the inserted opening and the forced block: it parses like any other sample."""
    opening = answer_opening(visible=visible)
    sampled_before = len(truncated.tokens.token_ids)
    inserted = [
        InsertedSpan(
            CharacterSpan(len(truncated.text), len(truncated.text) + len(opening)),
            TokenSpan(sampled_before, sampled_before + len(opening_token_ids)),
        )
    ]
    token_ids = (*truncated.tokens.token_ids, *opening_token_ids, *continuation.tokens.token_ids)
    text = truncated.text + opening + continuation.text
    if continuation.stop_string == FENCE:
        # The model wrote the closing fence: vLLM cut it from the text, its tokens end the continuation.
        text += FENCE
    else:
        closing = f"\n{FENCE}"
        inserted.append(
            InsertedSpan(CharacterSpan(len(text), len(text) + len(closing)), TokenSpan(len(token_ids), len(token_ids)))
        )
        text += closing
    log_probabilities = (
        *truncated.tokens.log_probabilities,
        *(None for _ in opening_token_ids),
        *continuation.tokens.log_probabilities,
    )
    return Sample(
        text=text,
        cumulative_logprob=truncated.cumulative_logprob + continuation.cumulative_logprob,
        token_count=truncated.token_count + continuation.token_count,
        finish_reason=continuation.finish_reason,
        tokens=SampledTokens(token_ids, log_probabilities, tuple(inserted)),
    )


class ParseFailure(Enum):
    TRUNCATED = "truncated"
    NO_BLOCK = "no_block"
    EMPTY = "empty"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class NormalizedBlock:
    text: str
    # For every character of `text`, and its end, the position in the text the block was read from.
    positions: tuple[int, ...]


def normalized_block(text: str, offset: int = 0) -> NormalizedBlock:
    """The block without surrounding blank lines, trailing spaces, a leading `by` line and common indentation."""
    lines: list[tuple[int, str]] = []
    start = len(text) - len(text.lstrip("\n"))
    for line in text[start:].split("\n"):
        lines.append((start, line.rstrip()))
        start += len(line) + 1
    # Models sometimes open the block with the `by` that already precedes the proof.
    if lines and lines[0][1].strip() == "by":
        lines.pop(0)
    while lines and not lines[0][1].strip():
        lines.pop(0)
    while lines and not lines[-1][1].strip():
        lines.pop()
    indentations = [line[: len(line) - len(line.lstrip())] for _, line in lines if line.strip()]
    margin = len(os.path.commonprefix(indentations)) if indentations else 0
    characters: list[str] = []
    positions: list[int] = []
    for index, (line_start, line) in enumerate(lines):
        if index:
            characters.append("\n")
            positions.append(offset + line_start - 1)
        kept = line[margin:] if line.strip() else ""
        first = line_start + len(line) - len(kept)
        characters.extend(kept)
        positions.extend(offset + first + column for column in range(len(kept)))
    end = positions[-1] + 1 if positions else offset
    return NormalizedBlock("".join(characters), (*positions, end))


def normalize_tactic_block(text: str) -> str:
    return normalized_block(text).text


def generated_block_start(text: str, thinking: bool, visible: bool = False) -> int | None:
    """Where the tactic block of a generated text starts, or None without a block."""
    if not thinking and not visible:
        return 0
    answer_start = 0
    if thinking:
        think_end = text.rfind(THINK_END)
        if think_end < 0:
            return None
        answer_start = think_end + len(THINK_END)
    fence = text.find(FENCE, answer_start)
    if fence < 0:
        return None
    # Skips the info string of the opening fence, usually "lean".
    newline = text.find("\n", fence + len(FENCE))
    return len(text) if newline < 0 else newline + 1


def generated_block(text: str, thinking: bool, visible: bool = False) -> str | None:
    start = generated_block_start(text, thinking, visible)
    if start is None:
        return None
    if not thinking and not visible:
        return text
    return text[start:].partition(FENCE)[0]


def closed_visible_block(text: str) -> bool:
    _, fence, after_fence = text.partition(FENCE)
    return bool(fence) and FENCE in after_fence


def parse_sample_block(
    sample: Sample,
    *,
    thinking: bool,
    forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS,
    visible: bool = False,
) -> NormalizedBlock | ParseFailure:
    """The normalized block with its characters' positions in the sample's text, or why there is none."""
    # A visible-reasoning sample cannot stop at the fence that opens its block, so it may run on after closing it.
    complete_visible = visible and closed_visible_block(sample.text)
    if sample.finish_reason == LENGTH_FINISH_REASON and not complete_visible:
        return ParseFailure.TRUNCATED
    start = generated_block_start(sample.text, thinking, visible)
    block = generated_block(sample.text, thinking, visible)
    if start is None or block is None:
        return ParseFailure.NO_BLOCK
    normalized = normalized_block(block, start)
    if not normalized.text:
        return ParseFailure.EMPTY
    if find_forbidden_tokens(normalized.text, forbidden_tokens):
        return ParseFailure.FORBIDDEN
    return normalized


def parse_sample(
    sample: Sample,
    *,
    thinking: bool,
    forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS,
    visible: bool = False,
) -> str | ParseFailure:
    """The normalized tactic block of one sample, or why it cannot be used."""
    match parse_sample_block(sample, thinking=thinking, forbidden_tokens=forbidden_tokens, visible=visible):
        case NormalizedBlock(text=block):
            return block
        case ParseFailure() as failure:
            return failure


@dataclass(frozen=True)
class TacticCandidate:
    tactic_block: str
    # The highest log-probability among the samples that produced this block.
    log_probability: float
    generated_tokens: int
    sample_count: int
    # Samples behind the block whose answer was forced after their thoughts were cut off.
    forced_sample_count: int = 0
    # The samples behind the block and, per sample, where each block character (and the end) is in its text.
    sample_indices: tuple[int, ...] = ()
    block_positions: tuple[tuple[int, ...], ...] = ()

    @property
    def forced(self) -> bool:
        return self.forced_sample_count == self.sample_count


@dataclass(frozen=True)
class ParsedSamples:
    candidates: tuple[TacticCandidate, ...]
    failures: tuple[ParseFailure, ...]
    failed_generated_tokens: int
    # The sample behind each failure.
    failed_sample_indices: tuple[int, ...] = ()

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
    failed_indices: list[int] = []
    failed_generated_tokens = 0
    for index, sample in enumerate(samples):
        forced = int(index in forced_indices)
        match parse_sample_block(sample, thinking=thinking, forbidden_tokens=forbidden_tokens, visible=visible):
            case ParseFailure() as failure:
                failures.append(failure)
                failed_indices.append(index)
                failed_generated_tokens += sample.token_count
            case NormalizedBlock(text=block, positions=positions) if block in candidates:
                earlier = candidates[block]
                candidates[block] = TacticCandidate(
                    block,
                    max(earlier.log_probability, sample.cumulative_logprob),
                    earlier.generated_tokens + sample.token_count,
                    earlier.sample_count + 1,
                    earlier.forced_sample_count + forced,
                    (*earlier.sample_indices, index),
                    (*earlier.block_positions, positions),
                )
            case NormalizedBlock(text=block, positions=positions):
                candidates[block] = TacticCandidate(
                    block, sample.cumulative_logprob, sample.token_count, 1, forced, (index,), (positions,)
                )
    ordered = sorted(candidates.values(), key=lambda candidate: -candidate.log_probability)
    return ParsedSamples(tuple(ordered), tuple(failures), failed_generated_tokens, tuple(failed_indices))
