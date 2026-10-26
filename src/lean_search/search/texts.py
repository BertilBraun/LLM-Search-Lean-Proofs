"""What the policy saw and wrote at an expansion, kept for training: prompts, generated texts, tactic spans."""

from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.lean.text import TacticPiece


@dataclass(frozen=True)
class CharacterSpan:
    start: int
    end: int


@dataclass(frozen=True)
class SampledCompletion:
    """One policy sample as generated: its edge in the tree and the executed tactics' characters in its text."""

    edge_id: int
    # Everything the model generated after the prompt: explanation, fenced block, anything after it.
    text: str
    # Per executed top-level tactic after flattening, in execution order, its characters in `text`.
    tactic_spans: tuple[CharacterSpan, ...]
    # Generation stopped at the end of turn, which the text itself does not contain.
    ended_turn: bool = True


@dataclass(frozen=True)
class ExpansionTexts:
    problem_name: str
    node_id: int
    # The exact prompt the samples were drawn from.
    prompt: str
    completions: tuple[SampledCompletion, ...]


@dataclass(frozen=True)
class GeneratedText:
    """A sample behind a candidate: its text and where each character of the candidate's block came from."""

    text: str
    ended_turn: bool
    # For every character of the normalized block, and its end, the position in `text`.
    block_positions: tuple[int, ...]

    def span(self, tactic: TacticPiece) -> CharacterSpan:
        return CharacterSpan(self.block_positions[tactic.start], self.block_positions[tactic.end - 1] + 1)


@dataclass(frozen=True)
class UnparsedSample:
    """A sample without a usable block (none, cut off at the token cap, empty or forbidden)."""

    text: str
    ended_turn: bool
    reason: str


def tactic_spans(generated: GeneratedText, tactics: Sequence[TacticPiece]) -> tuple[CharacterSpan, ...]:
    return tuple(generated.span(tactic) for tactic in tactics)
