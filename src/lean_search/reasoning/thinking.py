"""A thinking sample split into its reasoning and the tactic block the search would use."""

from dataclasses import dataclass

from lean_search.lean.text import FORBIDDEN_TOKENS, find_forbidden_tokens
from lean_search.policy.client import Sample
from lean_search.policy.prompts import (
    FENCE,
    THINK_END,
    THINK_START,
    ParseFailure,
    normalize_tactic_block,
    parse_sample,
    visible_explanation,
)


@dataclass(frozen=True)
class ThinkingSample:
    # Text before the closing think tag, stripped; the whole text when the sample never closed its thoughts.
    reasoning: str
    tactic_block: str | None
    parse_failure: ParseFailure | None
    # The block was written without its opening fence (see `unfenced_block`); the search's parser rejects it.
    recovered_format: bool = False


def reasoning_text(text: str) -> str:
    # The same (last) closing tag that `generated_block` reads the answer after.
    before, think_end, _ = text.rpartition(THINK_END)
    return (before if think_end else text).strip()


def unfenced_block(text: str) -> str | None:
    """The answer after the thoughts when it is a tactic and a closing fence only, as in the non-thinking format."""
    _, think_end, answer = text.rpartition(THINK_END)
    before, fence, after = answer.partition(FENCE)
    if not think_end or not fence or not before.strip() or after.strip():
        return None
    return before


def recovered_sample(text: str, reasoning: str, forbidden_tokens: frozenset[str]) -> ThinkingSample | None:
    unfenced = unfenced_block(text)
    if unfenced is None:
        return None
    block = normalize_tactic_block(unfenced)
    if not block:
        return None
    if find_forbidden_tokens(block, forbidden_tokens):
        return ThinkingSample(reasoning, None, ParseFailure.FORBIDDEN, recovered_format=True)
    return ThinkingSample(reasoning, block, None, recovered_format=True)


def sample_reasoning(text: str, *, thinking: bool, visible: bool) -> str:
    if thinking:
        return reasoning_text(text)
    return visible_explanation(text) if visible else ""


def parse_thinking_sample(
    sample: Sample, *, thinking: bool, forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS, visible: bool = False
) -> ThinkingSample:
    """The search's parse, plus blocks a thinking sample wrote without the opening fence (SFT-format leakage)."""
    reasoning = sample_reasoning(sample.text, thinking=thinking, visible=visible)
    match parse_sample(sample, thinking=thinking, forbidden_tokens=forbidden_tokens, visible=visible):
        case ParseFailure.EMPTY if thinking and (
            recovered := recovered_sample(sample.text, reasoning, forbidden_tokens)
        ):
            return recovered
        case ParseFailure() as failure:
            return ThinkingSample(reasoning, None, failure)
        case str() as block:
            return ThinkingSample(reasoning, block, None)


def is_trainable_reasoning(reasoning: str) -> bool:
    # A think tag inside the reasoning would be read as the end of the thoughts when the example is rendered.
    return bool(reasoning) and THINK_START not in reasoning and THINK_END not in reasoning
