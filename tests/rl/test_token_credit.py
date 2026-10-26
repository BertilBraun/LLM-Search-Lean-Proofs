import pytest

from lean_search.rl.advantages import SampleAdvantages
from lean_search.rl.token_credit import CharacterSpan, CreditMode, TokenSegment, token_credits, token_segments

EXPLANATION = "Introduce x, then normalize.\n\n```lean\n"
BLOCK = "intro x\nsimp\nring"
COMPLETION = EXPLANATION + BLOCK + "\n```<|im_end|>"
ADVANTAGES = SampleAdvantages(overall=0.5, prefix=0.8, error=-0.3)
E, P, R, M = TokenSegment.EXPLANATION, TokenSegment.PREFIX, TokenSegment.ERROR, TokenSegment.MASKED


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


def segments_of(text: str, tactic_spans: list[CharacterSpan], first_failing: int | None) -> str:
    """One letter per character: E explanation, P prefix, R error, M masked."""
    segments = token_segments(character_offsets(text), tactic_spans, first_failing)
    return "".join({E: "E", P: "P", R: "R", M: "M"}[segment] for segment in segments)


def segment_at(text: str, needle: str, first_failing: int | None) -> set[TokenSegment]:
    tactic_spans = spans(text, "intro x", "simp", "ring")
    segments = token_segments(character_offsets(text), tactic_spans, first_failing)
    start = text.index(needle)
    return set(segments[start : start + len(needle)])


@pytest.mark.parametrize(
    ("needle", "first_failing", "segment"),
    [
        ("Introduce", None, E),
        ("```lean", None, E),
        ("intro x", None, P),
        ("ring", None, P),
        ("<|im_end|>", None, P),
        ("Introduce", 0, E),
        ("intro x", 0, R),
        ("simp", 0, M),
        ("<|im_end|>", 0, M),
        ("intro x", 1, P),
        ("simp", 1, R),
        ("ring", 1, M),
        ("```<|im_end|>", 1, M),
    ],
)
def test_segment_of_each_part(needle: str, first_failing: int | None, segment: TokenSegment) -> None:
    assert segment_at(COMPLETION, needle, first_failing) == {segment}


def test_newline_between_tactics_belongs_to_the_next_tactic() -> None:
    newline = EXPLANATION.__len__() + len("intro x")
    segments = token_segments(character_offsets(COMPLETION), spans(COMPLETION, "intro x", "simp", "ring"), 1)
    assert segments[newline] == R


def test_flattened_have_keeps_its_valid_prefix_and_blames_the_nested_step() -> None:
    text = "```lean\nhave h : x = 1 := by\n  simp\nlinarith\n```"
    tactic_spans = spans(text, "have h : x = 1", "simp", "linarith")
    assert segments_of(text, tactic_spans, 1) == "E" * 8 + "P" * 14 + "R" * 13 + "M" * 13


def test_token_straddling_two_tactics_takes_the_first() -> None:
    offsets = [(0, 3), (3, 9), (9, 12)]
    assert token_segments(offsets, [CharacterSpan(0, 5), CharacterSpan(6, 12)], 1) == (P, P, R)


def test_without_spans_every_token_is_explanation() -> None:
    assert set(token_segments(character_offsets(COMPLETION), [], 0)) == {E}


@pytest.mark.parametrize(("first_failing", "expected"), [(None, 0.8), (1, -0.3)])
def test_tactic_token_advantage(first_failing: int | None, expected: float) -> None:
    text = COMPLETION
    credits = token_credits(
        character_offsets(text), spans(text, "intro x", "simp", "ring"), first_failing, ADVANTAGES, CreditMode.PER_TOKEN
    )
    assert credits.advantages[text.index("simp")] == expected


def test_explanation_tokens_get_the_overall_advantage() -> None:
    credits = token_credits(
        character_offsets(COMPLETION), spans(COMPLETION, "intro x", "simp", "ring"), 1, ADVANTAGES, CreditMode.PER_TOKEN
    )
    assert set(credits.advantages[: len(EXPLANATION)]) == {0.5}


def test_masked_tokens_are_not_trained() -> None:
    credits = token_credits(
        character_offsets(COMPLETION), spans(COMPLETION, "intro x", "simp", "ring"), 1, ADVANTAGES, CreditMode.PER_TOKEN
    )
    assert not credits.trained[COMPLETION.index("ring")]


def test_prefix_without_a_reached_state_falls_back_to_the_overall_advantage() -> None:
    advantages = SampleAdvantages(overall=-0.4, prefix=None, error=None)
    credits = token_credits(
        character_offsets(COMPLETION),
        spans(COMPLETION, "intro x", "simp", "ring"),
        None,
        advantages,
        CreditMode.PER_TOKEN,
    )
    assert set(credits.advantages) == {-0.4}


def test_sequence_credit_trains_every_token_with_the_overall_advantage() -> None:
    credits = token_credits(
        character_offsets(COMPLETION), spans(COMPLETION, "intro x", "simp", "ring"), 0, ADVANTAGES, CreditMode.SEQUENCE
    )
    assert (set(credits.advantages), set(credits.trained)) == ({0.5}, {True})
