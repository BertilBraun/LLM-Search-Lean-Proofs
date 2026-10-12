"""A thinking sample split into its reasoning and the tactic block the search would use."""

from dataclasses import dataclass

from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.policy.client import Sample
from lean_search.policy.prompts import THINK_END, THINK_START, ParseFailure, parse_sample


@dataclass(frozen=True)
class ThinkingSample:
    # Text before the closing think tag, stripped; the whole text when the sample never closed its thoughts.
    reasoning: str
    tactic_block: str | None
    parse_failure: ParseFailure | None


def reasoning_text(text: str) -> str:
    # The same (last) closing tag that `generated_block` reads the answer after.
    before, think_end, _ = text.rpartition(THINK_END)
    return (before if think_end else text).strip()


def parse_thinking_sample(
    sample: Sample, *, thinking: bool, forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS
) -> ThinkingSample:
    reasoning = reasoning_text(sample.text) if thinking else ""
    match parse_sample(sample, thinking=thinking, forbidden_tokens=forbidden_tokens):
        case ParseFailure() as failure:
            return ThinkingSample(reasoning, None, failure)
        case str() as block:
            return ThinkingSample(reasoning, block, None)


def is_trainable_reasoning(reasoning: str) -> bool:
    # A think tag inside the reasoning would be read as the end of the thoughts when the example is rendered.
    return bool(reasoning) and THINK_START not in reasoning and THINK_END not in reasoning
