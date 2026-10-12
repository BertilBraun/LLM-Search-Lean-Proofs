"""Deterministic held-out statements, replay shares and samples for the expert-iteration data sets."""

import hashlib
from collections.abc import Sequence

from lean_search.value.labels import ValueExample


def replay_amount(new_amount: int, replay_fraction: float) -> int:
    """How much replay data makes up `replay_fraction` of a mixture with `new_amount` of new data."""
    assert 0 <= replay_fraction < 1, replay_fraction
    return round(new_amount * replay_fraction / (1 - replay_fraction))


def is_held_out(problem_name: str, seed: str, fraction: float) -> bool:
    digest = hashlib.sha256(f"{seed}\n{problem_name}".encode()).digest()
    return int.from_bytes(digest[:8], "big") < fraction * 2**64


def sample_value_examples(examples: Sequence[ValueExample], count: int, seed: str) -> list[ValueExample]:
    """The `count` examples first in a seeded hash order of their identifier and goals."""

    def order(example: ValueExample) -> bytes:
        return hashlib.sha256("\0".join((seed, example.identifier, *example.goals)).encode()).digest()

    return sorted(examples, key=order)[:count]
