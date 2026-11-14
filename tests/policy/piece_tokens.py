from collections.abc import Sequence

from lean_search.policy import Sample
from lean_search.search.texts import SampledTokens


class PieceDecoder:
    """A token id is its piece's UTF-8 bytes read as one integer, so any piece of text, or of a character's bytes, can
    be one token."""

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return b"".join(token.to_bytes((token.bit_length() + 7) // 8, "big") for token in token_ids).decode(
            errors="replace"
        )


def piece_bytes(piece: str | bytes) -> bytes:
    match piece:
        case bytes():
            return piece
        case str():
            return piece.encode()


def token_id(piece: str | bytes) -> int:
    return int.from_bytes(piece_bytes(piece), "big")


def tokenized(
    pieces: Sequence[tuple[str | bytes, float]],
    *,
    hidden: str = "",
    finish_reason: str = "stop",
    stop_string: str | None = None,
) -> Sample:
    """A sample written as these (piece, log-probability) tokens; vLLM's text omits a trailing end of turn or stop
    string (`hidden`), its tokens do not."""
    written = b"".join(piece_bytes(piece) for piece, _ in pieces).decode()
    assert written.endswith(hidden)
    log_probabilities = tuple(log_probability for _, log_probability in pieces)
    tokens = SampledTokens(tuple(token_id(piece) for piece, _ in pieces), log_probabilities)
    text = written[: len(written) - len(hidden)]
    return Sample(text, sum(log_probabilities), len(pieces), finish_reason, tokens, stop_string)
