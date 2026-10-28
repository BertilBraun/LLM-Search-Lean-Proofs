from collections.abc import Sequence

import pytest

from lean_search.rl.advantages import CreditMode, SampleAdvantages
from lean_search.rl.token_credit import (
    TokenSegment,
    decoded_offsets,
    inserted_token_indices,
    sampled_token_offsets,
    token_credits,
)
from lean_search.search.texts import CharacterSpan, InsertedSpan, SampledCompletion, SampledTokens, TokenSpan

EXPLANATION = "Introduce x, then normalize.\n\n```lean\n"
BLOCK = "intro x\nsimp\nring"
COMPLETION = EXPLANATION + BLOCK + "\n```<|im_end|>"
ADVANTAGES = SampleAdvantages(sequence=0.5, tactics=(0.8, -0.3, None), closing=None)


class ByteDecoder:
    """Token i is the i-th UTF-8 byte of a text, so a multi-byte character spans several tokens."""

    def __init__(self, text: str) -> None:
        self.data = text.encode()

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return bytes(self.data[index] for index in token_ids).decode(errors="replace")


class CharacterDecoder:
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(chr(token) for token in token_ids)


def character_offsets(text: str) -> list[tuple[int, int]]:
    return [(index, index + 1) for index in range(len(text))]


def spans(text: str, *tactics: str) -> list[CharacterSpan]:
    found = []
    position = 0
    for tactic in tactics:
        start = text.index(tactic, position)
        found.append(CharacterSpan(start, start + len(tactic)))
        position = start + len(tactic)
    return found


def credits_at(needle: str, advantages: SampleAdvantages = ADVANTAGES, mode: CreditMode = CreditMode.PER_TACTIC):
    credits = token_credits(
        character_offsets(COMPLETION), spans(COMPLETION, "intro x", "simp", "ring"), frozenset(), advantages, mode
    )
    start = COMPLETION.index(needle)
    return credits, range(start, start + len(needle))


@pytest.mark.parametrize(
    ("needle", "segment", "advantage", "trained"),
    [
        ("Introduce", TokenSegment.EXPLANATION, 0.5, True),
        ("```lean", TokenSegment.EXPLANATION, 0.5, True),
        ("intro x", TokenSegment.TACTIC, 0.8, True),
        ("simp", TokenSegment.TACTIC, -0.3, True),
        ("ring", TokenSegment.TACTIC, 0.0, False),
        ("```<|im_end|>", TokenSegment.CLOSING, 0.0, False),
    ],
)
def test_token_credit_of_each_part(needle: str, segment: TokenSegment, advantage: float, trained: bool) -> None:
    credits, positions = credits_at(needle)
    found = {(credits.segments[index], credits.advantages[index], credits.trained[index]) for index in positions}
    assert found == {(segment, advantage, trained)}


def test_closing_tokens_of_a_complete_block_get_the_last_tactic_advantage() -> None:
    complete = SampleAdvantages(sequence=0.5, tactics=(0.8, 0.2, 0.4), closing=0.4)
    credits, positions = credits_at("<|im_end|>", complete)
    assert {credits.advantages[index] for index in positions} == {0.4}


def test_newline_between_tactics_belongs_to_the_next_tactic() -> None:
    credits, positions = credits_at("\nsimp")
    assert credits.advantages[positions[0]] == -0.3


def test_sequence_credit_gives_every_token_the_sequence_advantage() -> None:
    credits = token_credits(
        character_offsets(COMPLETION),
        spans(COMPLETION, "intro x", "simp", "ring"),
        frozenset(),
        ADVANTAGES,
        CreditMode.SEQUENCE,
    )
    assert set(credits.advantages) == {0.5}


def test_without_a_span_per_tactic_every_token_gets_the_sequence_advantage() -> None:
    credits = token_credits(character_offsets(COMPLETION), [], frozenset(), ADVANTAGES, CreditMode.PER_TACTIC)
    assert set(credits.advantages) == {0.5}


def test_inserted_tokens_are_never_trained() -> None:
    credits = token_credits(character_offsets(COMPLETION), [], frozenset({0, 1}), ADVANTAGES, CreditMode.SEQUENCE)
    assert (credits.trained[:3], credits.segments[:2]) == (
        (False, False, True),
        (TokenSegment.INSERTED, TokenSegment.INSERTED),
    )


def test_bytes_of_one_character_share_its_range() -> None:
    text = "a⊢b"
    offsets, decoded = decoded_offsets(ByteDecoder(text), range(len(text.encode())))
    assert (offsets, decoded) == ([(0, 1), (1, 2), (1, 2), (1, 2), (2, 3)], text)


def forced(text: str, opening: str, fence: str) -> SampledCompletion:
    """A sample whose opening the harness inserted (with tokens) and whose closing fence it appended (without)."""
    cut = text.index(opening)
    token_text = text[: len(text) - len(fence)] + "<|im_end|>"
    opening_tokens = TokenSpan(cut, cut + len(opening))
    return SampledCompletion(
        0,
        text,
        (),
        tokens=SampledTokens(
            tuple(ord(character) for character in token_text),
            tuple(None if cut <= index < cut + len(opening) else -0.1 for index in range(len(token_text))),
            (
                InsertedSpan(CharacterSpan(cut, cut + len(opening)), opening_tokens),
                InsertedSpan(
                    CharacterSpan(len(text) - len(fence), len(text)), TokenSpan(len(token_text), len(token_text))
                ),
            ),
        ),
    )


FORCED = forced("Thinking on and on.\n\n```lean\nsimp\n```", "\n\n```lean\n", "\n```")


def test_end_of_turn_after_the_inserted_fence_starts_past_it() -> None:
    offsets = sampled_token_offsets(CharacterDecoder(), FORCED)
    end_of_turn = len(FORCED.text) - len("\n```")
    assert offsets is not None and offsets[end_of_turn][0] == len(FORCED.text)


def test_tokens_before_the_inserted_fence_keep_their_positions() -> None:
    offsets = sampled_token_offsets(CharacterDecoder(), FORCED)
    assert offsets is not None and offsets[3] == (3, 4)


def test_tokens_that_do_not_decode_to_the_text_have_no_offsets() -> None:
    mismatched = SampledCompletion(0, "simp", (), tokens=SampledTokens((ord("x"),), (-0.1,)))
    assert sampled_token_offsets(CharacterDecoder(), mismatched) is None


def test_inserted_token_indices_cover_the_inserted_opening() -> None:
    cut = FORCED.text.index("\n\n```lean\n")
    assert inserted_token_indices(FORCED) == frozenset(range(cut, cut + len("\n\n```lean\n")))
