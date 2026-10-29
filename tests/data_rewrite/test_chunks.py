from collections import Counter

import pytest

from lean_search.data_rewrite.chunks import (
    DEFAULT_CHUNK_LENGTHS,
    REST_OF_PROOF,
    Chunk,
    ChunkLength,
    ChunkRejection,
    choose_chunks,
    chunk_size,
    drawn_length,
    fallback_sizes,
)


def accept_all(start: int, end: int) -> ChunkRejection | None:
    return None


def test_drawn_lengths_cover_every_configured_length() -> None:
    drawn = {drawn_length(f"proof#{start}", DEFAULT_CHUNK_LENGTHS, "seed") for start in range(200)}
    assert drawn == {1, 3, 5, 7, REST_OF_PROOF}


def test_zero_weight_lengths_are_never_drawn() -> None:
    lengths = (ChunkLength(1, 0.0), ChunkLength(3, 1.0))
    assert {drawn_length(f"proof#{start}", lengths, "seed") for start in range(100)} == {3}


def test_drawn_length_is_fixed_by_its_key() -> None:
    assert drawn_length("proof#4", DEFAULT_CHUNK_LENGTHS, "seed") == drawn_length(
        "proof#4", DEFAULT_CHUNK_LENGTHS, "seed"
    )


@pytest.mark.parametrize(
    ("drawn", "start", "total", "expected"),
    [(3, 0, 10, 3), (7, 6, 10, 4), (REST_OF_PROOF, 2, 10, 8), (1, 9, 10, 1)],
)
def test_chunk_size_stops_at_the_end_of_the_proof(drawn: int, start: int, total: int, expected: int) -> None:
    assert chunk_size(drawn, start, total) == expected


def test_fallback_sizes_try_shorter_configured_lengths() -> None:
    assert fallback_sizes(6, DEFAULT_CHUNK_LENGTHS) == [6, 5, 3, 1]


def test_every_start_state_gets_one_chunk() -> None:
    choices = choose_chunks("proof", 9, DEFAULT_CHUNK_LENGTHS, "seed", accept_all)
    assert [chunk.start for chunk in choices.chunks] == list(range(9))


def test_chunks_end_within_the_proof() -> None:
    choices = choose_chunks("proof", 9, DEFAULT_CHUNK_LENGTHS, "seed", accept_all)
    assert all(chunk.end <= 9 for chunk in choices.chunks)


def test_a_chunk_that_does_not_fit_falls_back_to_a_shorter_one() -> None:
    lengths = (ChunkLength(1), ChunkLength(REST_OF_PROOF, 1000.0))

    def short_only(start: int, end: int) -> ChunkRejection | None:
        return None if end - start == 1 else ChunkRejection.COMPLETION_TOO_LONG

    choices = choose_chunks("proof", 4, lengths, "seed", short_only)
    assert {chunk.tactics for chunk in choices.chunks} == {1}


def test_start_states_without_a_fitting_chunk_are_counted() -> None:
    def long_prompt(start: int, end: int) -> ChunkRejection | None:
        return ChunkRejection.PROMPT_TOO_LONG if start == 2 else None

    choices = choose_chunks("proof", 4, DEFAULT_CHUNK_LENGTHS, "seed", long_prompt)
    assert choices.dropped == Counter({ChunkRejection.PROMPT_TOO_LONG: 1})


def test_chunk_records_its_drawn_length() -> None:
    lengths = (ChunkLength(7),)
    (first, *_) = choose_chunks("proof", 3, lengths, "seed", accept_all).chunks
    assert first == Chunk(0, 3, 7)
