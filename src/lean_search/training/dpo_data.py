"""Preference pairs for DPO: one proof state, a chosen and a rejected step, rendered in the policy's SFT format.

A pair without a rejected step trains only the chosen step's negative log-likelihood (dataset steps, proof steps
whose siblings all made progress).
"""

import dataclasses
import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from lean_search.training.sft_data import SftExample, TokenizedExample, Tokenizer, tokenize_example


@dataclass(frozen=True)
class PreferencePair:
    source: str
    proof_identifier: str
    step_index: int
    goals: tuple[str, ...]
    chosen: str
    rejected: str | None
    # Why the rejected step lost, e.g. a Lean error, a timeout or a dead subtree.
    rejection: str


@dataclass(frozen=True)
class TokenizedPair:
    pair: PreferencePair
    chosen: TokenizedExample
    rejected: TokenizedExample | None

    @property
    def token_count(self) -> int:
        return self.chosen.token_count + (0 if self.rejected is None else self.rejected.token_count)

    @property
    def padded_length(self) -> int:
        """Both sequences share a micro-batch, padded to the longer one."""
        if self.rejected is None:
            return self.chosen.token_count
        return 2 * max(self.chosen.token_count, self.rejected.token_count)


def tokenize_pair(tokenizer: Tokenizer, pair: PreferencePair) -> TokenizedPair:
    def completion(tactic_block: str) -> TokenizedExample:
        example = SftExample(pair.source, pair.proof_identifier, pair.step_index, pair.goals, tactic_block)
        return tokenize_example(tokenizer, example)

    return TokenizedPair(pair, completion(pair.chosen), None if pair.rejected is None else completion(pair.rejected))


def fits(pair: TokenizedPair, max_prompt_tokens: int, max_completion_tokens: int) -> bool:
    completions = [pair.chosen] if pair.rejected is None else [pair.chosen, pair.rejected]
    return pair.chosen.prompt_token_count <= max_prompt_tokens and all(
        completion.completion_token_count <= max_completion_tokens for completion in completions
    )


def pair_key(pair: PreferencePair) -> bytes:
    rejected = "\2" if pair.rejected is None else pair.rejected
    return hashlib.sha256("\0".join((*pair.goals, "\1", pair.chosen, "\1", rejected)).encode()).digest()


def deduplicate_pairs(pairs: Iterable[PreferencePair]) -> list[PreferencePair]:
    seen: set[bytes] = set()
    kept = []
    for pair in pairs:
        key = pair_key(pair)
        if key not in seen:
            seen.add(key)
            kept.append(pair)
    return kept


def write_pairs(path: Path, pairs: Iterable[PreferencePair]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(dataclasses.asdict(pair), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def read_pairs(path: Path) -> Iterator[PreferencePair]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            yield PreferencePair(**fields | {"goals": tuple(fields["goals"])})
