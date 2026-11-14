from collections.abc import Sequence

from lean_search.policy import Sample
from lean_search.search.texts import SampledTokens


class PieceDecoder:
    """A token id is its piece's UTF-8 bytes read as one integer, so any piece of text can be one token."""

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(token.to_bytes((token.bit_length() + 7) // 8, "big").decode() for token in token_ids)


def token_id(piece: str) -> int:
    return int.from_bytes(piece.encode(), "big")


def tokenized(
    pieces: Sequence[tuple[str, float]],
    *,
    hidden: str = "",
    finish_reason: str = "stop",
    stop_string: str | None = None,
) -> Sample:
    """A sample written as these (piece, log-probability) tokens; vLLM's text omits a trailing end of turn or stop
    string (`hidden`), its tokens do not."""
    written = "".join(piece for piece, _ in pieces)
    assert written.endswith(hidden)
    log_probabilities = tuple(log_probability for _, log_probability in pieces)
    tokens = SampledTokens(tuple(token_id(piece) for piece, _ in pieces), log_probabilities)
    text = written[: len(written) - len(hidden)]
    return Sample(text, sum(log_probabilities), len(pieces), finish_reason, tokens, stop_string)
