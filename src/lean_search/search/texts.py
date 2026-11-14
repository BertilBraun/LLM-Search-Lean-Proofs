"""What the policy saw and wrote at an expansion, kept for training: prompts, generated texts and tokens, spans."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from lean_search.lean.text import TacticPiece

# Enough for comparing vLLM's log-probabilities with the trainer's; keeps the token records small.
LOG_PROBABILITY_DECIMALS = 4
INCOMPLETE_CHARACTER = "�"


@dataclass(frozen=True)
class CharacterSpan:
    start: int
    end: int


@dataclass(frozen=True)
class TokenSpan:
    start: int
    end: int


@dataclass(frozen=True)
class InsertedSpan:
    """Text the harness inserted into a sample instead of the model sampling it (masked in training)."""

    characters: CharacterSpan
    # The inserted tokens' indices in the sample's token ids; empty when the inserted text has no tokens.
    tokens: TokenSpan


@dataclass(frozen=True)
class SampledTokens:
    """A sample's tokens in the order the model saw them, sampled and inserted, with vLLM's log-probabilities."""

    # Decoded: the text without token-less inserted spans, maybe followed by an end of turn or a stop string it omits.
    token_ids: tuple[int, ...] = ()
    # Per token: vLLM's log-probability of the sampled token (rounded); None for a token the harness inserted.
    log_probabilities: tuple[float | None, ...] = ()
    inserted: tuple[InsertedSpan, ...] = ()

    def rounded(self) -> "SampledTokens":
        return SampledTokens(
            self.token_ids,
            tuple(
                None if value is None else round(value, LOG_PROBABILITY_DECIMALS) for value in self.log_probabilities
            ),
            self.inserted,
        )


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
    # Empty in records written before tokens were kept.
    tokens: SampledTokens = SampledTokens()


@dataclass(frozen=True)
class ExpansionTexts:
    problem_name: str
    node_id: int
    # The exact prompt the samples were drawn from.
    prompt: str
    completions: tuple[SampledCompletion, ...]
    # The sampling settings behind the log-probabilities; None in records written before they were kept.
    temperature: float | None = None
    top_p: float | None = None
    # The published policy version that sampled them; None outside the GRPO loop and in older records.
    policy_version: int | None = None
    # The node's feedback round (policy.feedback): a second prompt, its samples a GRPO group of their own.
    feedback: bool = False


@dataclass(frozen=True)
class GeneratedText:
    """A sample behind a candidate: its text and where each character of the candidate's block came from."""

    text: str
    ended_turn: bool
    # For every character of the normalized block, and its end, the position in `text`.
    block_positions: tuple[int, ...]
    tokens: SampledTokens = SampledTokens()

    def span(self, tactic: TacticPiece) -> CharacterSpan:
        return CharacterSpan(self.block_positions[tactic.start], self.block_positions[tactic.end - 1] + 1)


@dataclass(frozen=True)
class UnparsedSample:
    """A sample without a usable block (none, cut off at the token cap, empty or forbidden)."""

    text: str
    ended_turn: bool
    reason: str
    tokens: SampledTokens = SampledTokens()


def tactic_spans(generated: GeneratedText, tactics: Sequence[TacticPiece]) -> tuple[CharacterSpan, ...]:
    return tuple(generated.span(tactic) for tactic in tactics)


class TokenDecoder(Protocol):
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str: ...


def decoded_offsets(decoder: TokenDecoder, token_ids: Sequence[int]) -> tuple[list[tuple[int, int]], str]:
    """Each token's characters in the decoded text; tokens sharing a multi-byte character share its range."""
    offsets: list[tuple[int, int]] = []
    pieces: list[str] = []
    length = 0
    pending = 0
    for index in range(len(token_ids)):
        piece = decoder.decode(token_ids[pending : index + 1], skip_special_tokens=False)
        if piece.endswith(INCOMPLETE_CHARACTER) and index + 1 < len(token_ids):
            continue
        offsets.extend([(length, length + len(piece))] * (index + 1 - pending))
        pieces.append(piece)
        length += len(piece)
        pending = index + 1
    return offsets, "".join(pieces)


def text_position(position: int, removed: Sequence[CharacterSpan], inclusive: bool) -> int:
    """A position in the decoded text as a position in the text that also holds the removed spans."""
    for span in removed:
        if span.start < position or (inclusive and span.start == position):
            position += span.end - span.start
    return position


def token_offsets(decoder: TokenDecoder, text: str, tokens: SampledTokens) -> tuple[tuple[int, int], ...] | None:
    """Each recorded token's characters in the sample's text; None when the tokens do not decode to the text."""
    removed = sorted(
        (span.characters for span in tokens.inserted if span.tokens.start == span.tokens.end),
        key=lambda span: span.start,
    )
    expected = text
    for span in reversed(removed):
        expected = expected[: span.start] + expected[span.end :]
    offsets, decoded = decoded_offsets(decoder, tokens.token_ids)
    if not decoded.startswith(expected):
        return None
    return tuple(
        (text_position(start, removed, inclusive=True), text_position(end, removed, inclusive=False))
        for start, end in offsets
    )


def overlaps(token: tuple[int, int], span: CharacterSpan) -> bool:
    start, end = token
    if start == end:
        return span.start <= start < span.end
    return span.start < end and start < span.end
