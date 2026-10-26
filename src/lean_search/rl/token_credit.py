"""Per-token advantages within a GRPO sample: explanation, valid tactic prefix, first failing tactic, masked rest."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.rl.advantages import SampleAdvantages
from lean_search.search.texts import CharacterSpan


class CreditMode(StrEnum):
    PER_TOKEN = "per_token"
    # Every completion token gets the sample's overall advantage (outcome-level GRPO).
    SEQUENCE = "sequence"


class TokenSegment(StrEnum):
    # Everything before the first tactic: the explanation and the opening fence.
    EXPLANATION = "explanation"
    # Tactics before the first failing one, and after a complete block the closing fence and end of turn.
    PREFIX = "prefix"
    ERROR = "error"
    # After the first failing tactic: Lean never evaluated it.
    MASKED = "masked"


@dataclass(frozen=True)
class TokenCredits:
    advantages: tuple[float, ...]
    trained: tuple[bool, ...]
    segments: tuple[TokenSegment, ...]


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


def token_segments(
    offsets: Sequence[tuple[int, int]], spans: Sequence[CharacterSpan], first_failing_tactic: int | None
) -> tuple[TokenSegment, ...]:
    """Each token's segment from its character range; without spans the whole completion is explanation."""
    if not spans:
        return tuple(TokenSegment.EXPLANATION for _ in offsets)
    assert first_failing_tactic is None or first_failing_tactic < len(spans), (first_failing_tactic, len(spans))
    segments = []
    for token in offsets:
        if token[0] < spans[0].start and token[1] <= spans[0].start:
            segments.append(TokenSegment.EXPLANATION)
            continue
        position = tactic_position(token, spans)
        if first_failing_tactic is None or position < first_failing_tactic:
            segments.append(TokenSegment.PREFIX)
        elif position == first_failing_tactic:
            segments.append(TokenSegment.ERROR)
        else:
            segments.append(TokenSegment.MASKED)
    return tuple(segments)


def segment_advantage(segment: TokenSegment, advantages: SampleAdvantages) -> float:
    match segment:
        case TokenSegment.EXPLANATION:
            return advantages.overall
        case TokenSegment.PREFIX:
            return advantages.overall if advantages.prefix is None else advantages.prefix
        case TokenSegment.ERROR:
            assert advantages.error is not None
            return advantages.error
        case TokenSegment.MASKED:
            return 0.0


def token_credits(
    offsets: Sequence[tuple[int, int]],
    spans: Sequence[CharacterSpan],
    first_failing_tactic: int | None,
    advantages: SampleAdvantages,
    mode: CreditMode,
) -> TokenCredits:
    match mode:
        case CreditMode.PER_TOKEN:
            segments = token_segments(offsets, spans, first_failing_tactic)
        case CreditMode.SEQUENCE:
            segments = tuple(TokenSegment.EXPLANATION for _ in offsets)
    return TokenCredits(
        advantages=tuple(segment_advantage(segment, advantages) for segment in segments),
        trained=tuple(segment != TokenSegment.MASKED for segment in segments),
        segments=segments,
    )
