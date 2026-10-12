"""Near-duplicate statements (one problem formalized several ways) by MinHash/LSH over normalized token 5-grams.

Statements are tokenized as for decontamination (bound names anonymized) and hashed into 5-gram sets; a MinHash
signature of `PERMUTATIONS` values estimates their Jaccard similarity. LSH (`BANDS` bands of `ROWS` rows, detection
around Jaccard (1 / BANDS) ** (1 / ROWS) ~ 0.68) proposes pairs, and a pair joins one cluster when its estimated
Jaccard reaches the threshold. Each cluster keeps its first member in the given order (easiest first: the shortest
known proof).
"""

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass

import numpy

from lean_search.corpora.decontamination import anonymized_statement_tokens, token_ngrams

PERMUTATIONS = 60
BANDS = 10
ROWS = PERMUTATIONS // BANDS
MERSENNE_PRIME = (1 << 31) - 1
EMPTY_SIGNATURE = numpy.full(PERMUTATIONS, MERSENNE_PRIME, dtype=numpy.uint64)


@dataclass(frozen=True)
class SimilarPair:
    first: int
    second: int
    estimated_jaccard: float


class MinHasher:
    def __init__(self, seed: int = 0) -> None:
        generator = random.Random(seed)
        self.multipliers = numpy.array(
            [generator.randrange(1, MERSENNE_PRIME) for _ in range(PERMUTATIONS)], dtype=numpy.uint64
        )
        self.offsets = numpy.array(
            [generator.randrange(0, MERSENNE_PRIME) for _ in range(PERMUTATIONS)], dtype=numpy.uint64
        )

    def signature(self, formal_statement: str) -> numpy.ndarray:
        grams = token_ngrams(anonymized_statement_tokens(formal_statement))
        if not grams:
            return EMPTY_SIGNATURE
        hashes = numpy.array(
            [int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=4).digest()) for gram in grams],
            dtype=numpy.uint64,
        ) % numpy.uint64(MERSENNE_PRIME)
        permuted = (numpy.outer(hashes, self.multipliers) + self.offsets) % numpy.uint64(MERSENNE_PRIME)
        return permuted.min(axis=0)


def estimated_jaccard(first: numpy.ndarray, second: numpy.ndarray) -> float:
    return float(numpy.mean(first == second))


def similar_pairs(signatures: numpy.ndarray) -> list[SimilarPair]:
    """Each LSH bucket's members paired with its first member (its likely cluster representative)."""
    pairs: dict[tuple[int, int], SimilarPair] = {}
    for band in range(BANDS):
        buckets: dict[bytes, int] = {}
        rows = signatures[:, band * ROWS : (band + 1) * ROWS]
        for index in range(len(signatures)):
            key = rows[index].tobytes()
            first = buckets.setdefault(key, index)
            if first != index and (first, index) not in pairs:
                similarity = estimated_jaccard(signatures[first], signatures[index])
                pairs[(first, index)] = SimilarPair(first, index, similarity)
    return list(pairs.values())


def clusters(count: int, pairs: Sequence[SimilarPair], threshold: float) -> list[int]:
    """Per statement, the smallest index of its cluster (union-find over the pairs at or above the threshold)."""
    parent = list(range(count))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for pair in pairs:
        if pair.estimated_jaccard >= threshold:
            first, second = root(pair.first), root(pair.second)
            parent[max(first, second)] = min(first, second)
    return [root(index) for index in range(count)]
