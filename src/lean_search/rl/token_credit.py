"""Per-token advantages of a sample: its sampled tokens mapped to the explanation, each tactic and the closing part."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lean_search.rl.advantages import CreditMode, SampleAdvantages
from lean_search.search.texts import CharacterSpan, SampledCompletion

INCOMPLETE_CHARACTER = "�"


class TokenDecoder(Protocol):
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str: ...


class TokenSegment(StrEnum):
    # Everything before the first tactic: the explanation and the opening fence.
    EXPLANATION = "explanation"
    TACTIC = "tactic"
    # After the last tactic: the closing fence, anything after it and the end of turn.
    CLOSING = "closing"
    # Written by the harness, not sampled.
    INSERTED = "inserted"


@dataclass(frozen=True)
class TokenCredits:
    # 0 where not trained.
    advantages: tuple[float, ...]
    trained: tuple[bool, ...]
    segments: tuple[TokenSegment, ...]


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


def sampled_token_offsets(decoder: TokenDecoder, completion: SampledCompletion) -> tuple[tuple[int, int], ...] | None:
    """Each recorded token's characters in the completion text; None when the tokens do not decode to the text."""
    text = completion.text
    removed = sorted(
        (span.characters for span in completion.tokens.inserted if span.tokens.start == span.tokens.end),
        key=lambda span: span.start,
    )
    expected = text
    for span in reversed(removed):
        expected = expected[: span.start] + expected[span.end :]
    offsets, decoded = decoded_offsets(decoder, completion.tokens.token_ids)
    if not decoded.startswith(expected):
        return None
    return tuple(
        (text_position(start, removed, inclusive=True), text_position(end, removed, inclusive=False))
        for start, end in offsets
    )


def inserted_token_indices(completion: SampledCompletion) -> frozenset[int]:
    return frozenset(
        index for span in completion.tokens.inserted for index in range(span.tokens.start, span.tokens.end)
    )


def overlaps(token: tuple[int, int], span: CharacterSpan) -> bool:
    start, end = token
    if start == end:
        return span.start <= start < span.end
    return span.start < end and start < span.end


def tactic_position(token: tuple[int, int], spans: Sequence[CharacterSpan]) -> int:
    """The first tactic the token overlaps; for a token between tactics the next one; len(spans) after the last."""
    for index, span in enumerate(spans):
        if overlaps(token, span):
            return index
    return next((index for index, span in enumerate(spans) if span.start >= token[1]), len(spans))


def token_credits(
    offsets: Sequence[tuple[int, int]],
    spans: Sequence[CharacterSpan],
    inserted: frozenset[int],
    advantages: SampleAdvantages,
    mode: CreditMode,
) -> TokenCredits:
    """Without one span per tactic (no usable block, or none recorded) every sampled token gets the sequence credit."""
    per_tactic = mode == CreditMode.PER_TACTIC and bool(spans) and len(spans) == len(advantages.tactics)
    segments: list[TokenSegment] = []
    values: list[float | None] = []
    for index, token in enumerate(offsets):
        if index in inserted:
            segments.append(TokenSegment.INSERTED)
            values.append(None)
        elif not per_tactic or (token[0] < spans[0].start and token[1] <= spans[0].start):
            segments.append(TokenSegment.EXPLANATION)
            values.append(advantages.sequence)
        elif (position := tactic_position(token, spans)) == len(spans):
            segments.append(TokenSegment.CLOSING)
            values.append(advantages.closing)
        else:
            segments.append(TokenSegment.TACTIC)
            values.append(advantages.tactics[position])
    return TokenCredits(
        advantages=tuple(0.0 if value is None else value for value in values),
        trained=tuple(value is not None for value in values),
        segments=tuple(segments),
    )
