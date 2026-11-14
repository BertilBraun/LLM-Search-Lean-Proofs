"""Per-token advantages of a sample: its sampled tokens mapped to the explanation, each tactic and the closing part."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.rl.advantages import CreditMode, SampleAdvantages
from lean_search.search.texts import CharacterSpan, SampledCompletion, overlaps


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


def inserted_token_indices(completion: SampledCompletion) -> frozenset[int]:
    return frozenset(
        index for span in completion.tokens.inserted for index in range(span.tokens.start, span.tokens.end)
    )


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
    """Segments by position whatever the mode when there is one span per tactic, else every sampled token is the
    explanation. Per-tactic credit gives the tactics and the closing part their own advantages and the rest the
    sequence credit; the other modes give every sampled token the sample's one advantage."""
    by_position = bool(spans) and len(spans) == len(advantages.tactics)
    per_tactic = mode == CreditMode.PER_TACTIC
    match mode:
        case CreditMode.PER_TACTIC | CreditMode.SEQUENCE:
            whole = advantages.sequence
        case CreditMode.PROOF_SUCCESS:
            whole = advantages.proof_success
    segments: list[TokenSegment] = []
    values: list[float | None] = []
    for index, token in enumerate(offsets):
        if index in inserted:
            segments.append(TokenSegment.INSERTED)
            values.append(None)
        elif not by_position or (token[0] < spans[0].start and token[1] <= spans[0].start):
            segments.append(TokenSegment.EXPLANATION)
            values.append(whole)
        elif (position := tactic_position(token, spans)) == len(spans):
            segments.append(TokenSegment.CLOSING)
            values.append(advantages.closing if per_tactic else whole)
        else:
            segments.append(TokenSegment.TACTIC)
            values.append(advantages.tactics[position] if per_tactic else whole)
    return TokenCredits(
        advantages=tuple(0.0 if value is None else value for value in values),
        trained=tuple(value is not None for value in values),
        segments=tuple(segments),
    )
