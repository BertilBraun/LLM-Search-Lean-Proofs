"""Supervised fine-tuning data: traced proof steps rendered in the policy's chat format, mixed by source."""

import dataclasses
import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lean_search.corpora.records import DataSplit, read_traced_steps
from lean_search.lean.text import find_forbidden_tokens
from lean_search.policy.prompts import ChatTemplate, normalize_tactic_block, render_completion, render_prompt

IGNORE_INDEX = -100


class Tokenizer(ChatTemplate, Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True)
class SftExample:
    source: str
    proof_identifier: str
    step_index: int
    goals: tuple[str, ...]
    tactic_block: str


@dataclass(frozen=True)
class TokenizedExample:
    example: SftExample
    input_ids: tuple[int, ...]
    prompt_token_count: int

    @property
    def token_count(self) -> int:
        return len(self.input_ids)

    @property
    def completion_token_count(self) -> int:
        return len(self.input_ids) - self.prompt_token_count

    @property
    def labels(self) -> tuple[int, ...]:
        return (IGNORE_INDEX,) * self.prompt_token_count + self.input_ids[self.prompt_token_count :]


@dataclass(frozen=True)
class SourceWeight:
    name: str
    weight: float


@dataclass(frozen=True)
class SftDataConfig:
    sources: tuple[SourceWeight, ...]
    # Prompt plus completion tokens of the reference tokenizer; 0 takes every example.
    token_budget: int = 0
    max_prompt_tokens: int = 2048
    max_completion_tokens: int = 512
    validation_examples: int = 2000
    reference_tokenizer: str = "Qwen/Qwen3.5-2B"
    seed: str = "sft"


@dataclass(frozen=True)
class TracedExamples:
    train: dict[str, list[SftExample]]
    validation: dict[str, list[SftExample]]
    forbidden: Counter[str]


@dataclass(frozen=True)
class DeduplicatedPool:
    examples_by_source: dict[str, list[SftExample]]
    duplicates_by_source: Counter[str]
    keys: frozenset[bytes]


@dataclass(frozen=True)
class LengthStatistics:
    count: int
    total: int
    mean: float
    p50: int
    p90: int
    p99: int
    maximum: int


@dataclass(frozen=True)
class SourceStatistics:
    source: str
    traced_steps: int
    forbidden_steps: int
    duplicates: int
    examined: int
    over_length: int
    selected: int
    prompt_tokens: LengthStatistics
    completion_tokens: LengthStatistics
    total_tokens: int


class SourceStream:
    """One source's unique examples in a fixed pseudo-random order, tokenized lazily up to a token target."""

    def __init__(self, examples: Sequence[SftExample], tokenize: Callable[[SftExample], TokenizedExample | None]):
        self.examples = examples
        self.tokenize = tokenize
        self.examined = 0
        self.over_length = 0
        self.accepted: list[TokenizedExample] = []
        self.tokens = 0

    def extend_to(self, token_target: float) -> bool:
        while self.tokens < token_target:
            if self.examined == len(self.examples):
                return False
            tokenized = self.tokenize(self.examples[self.examined])
            self.examined += 1
            if tokenized is None:
                self.over_length += 1
                continue
            self.accepted.append(tokenized)
            self.tokens += tokenized.token_count
        return True


def sft_example(source: str, proof_identifier: str, step_index: int, goals: Sequence[str], step: str) -> SftExample:
    return SftExample(source, proof_identifier, step_index, tuple(goals), normalize_tactic_block(step))


def read_traced_examples(directory: Path, sources: Collection[str]) -> TracedExamples:
    train: dict[str, list[SftExample]] = {source: [] for source in sources}
    validation: dict[str, list[SftExample]] = {source: [] for source in sources}
    forbidden: Counter[str] = Counter()
    for path in sorted(directory.glob("shards/*/*.steps.jsonl")):
        for step in read_traced_steps(path):
            if step.source not in train:
                continue
            example = sft_example(step.source, step.proof_identifier, step.step_index, step.goals_before, step.step)
            is_train = step.split == DataSplit.TRAIN
            # The search rejects such blocks, so the policy must not learn to write them.
            if find_forbidden_tokens(example.tactic_block):
                forbidden[step.source] += is_train
                continue
            (train if is_train else validation)[step.source].append(example)
    return TracedExamples(train, validation, forbidden)


def ordering_key(example: SftExample, seed: str) -> bytes:
    return hashlib.sha256(f"{seed}\n{example.proof_identifier}\n{example.step_index}".encode()).digest()


def duplicate_key(example: SftExample) -> bytes:
    return hashlib.sha256("\0".join((*example.goals, "\1", example.tactic_block)).encode()).digest()


def deduplicate(
    examples_by_source: Mapping[str, Sequence[SftExample]], seed: str, excluded_keys: Collection[bytes] = frozenset()
) -> DeduplicatedPool:
    """Shuffles each source deterministically and keeps the first occurrence of each (goals, step) pair."""
    seen: set[bytes] = set()
    kept: dict[str, list[SftExample]] = {}
    duplicates: Counter[str] = Counter()
    for source, examples in examples_by_source.items():
        kept[source] = []
        for example in sorted(examples, key=lambda example: ordering_key(example, seed)):
            key = duplicate_key(example)
            if key in seen or key in excluded_keys:
                duplicates[source] += 1
                continue
            seen.add(key)
            kept[source].append(example)
    return DeduplicatedPool(kept, duplicates, frozenset(seen))


def tokenize_example(tokenizer: Tokenizer, example: SftExample) -> TokenizedExample:
    prompt_ids = tokenizer.encode(render_prompt(tokenizer, example.goals), add_special_tokens=False)
    completion_ids = tokenizer.encode(render_completion(example.tactic_block), add_special_tokens=False)
    return TokenizedExample(example, tuple(prompt_ids + completion_ids), len(prompt_ids))


def length_capped_tokenizer(
    tokenizer: Tokenizer, max_prompt_tokens: int, max_completion_tokens: int
) -> Callable[[SftExample], TokenizedExample | None]:
    def tokenize(example: SftExample) -> TokenizedExample | None:
        tokenized = tokenize_example(tokenizer, example)
        if tokenized.prompt_token_count > max_prompt_tokens or tokenized.completion_token_count > max_completion_tokens:
            return None
        return tokenized

    return tokenize


def select_mixture(streams: Mapping[str, SourceStream], weights: Mapping[str, float], token_budget: int) -> None:
    """Fills each stream to its weighted share of the budget; shares of exhausted sources go to the others."""
    active = {source for source, weight in weights.items() if weight > 0}
    remaining = math.inf if token_budget == 0 else float(token_budget)
    while active:
        total_weight = sum(weights[source] for source in active)
        exhausted = {
            source for source in active if not streams[source].extend_to(remaining * weights[source] / total_weight)
        }
        if not exhausted:
            return
        remaining -= sum(streams[source].tokens for source in exhausted)
        active -= exhausted


def select_validation(
    examples_by_source: Mapping[str, Sequence[SftExample]],
    count: int,
    seed: str,
    tokenize: Callable[[SftExample], TokenizedExample | None],
) -> list[TokenizedExample]:
    candidates = sorted(
        (example for examples in examples_by_source.values() for example in examples),
        key=lambda example: ordering_key(example, seed),
    )
    selected: list[TokenizedExample] = []
    for example in candidates:
        if len(selected) == count:
            break
        if (tokenized := tokenize(example)) is not None:
            selected.append(tokenized)
    return selected


def length_statistics(values: Sequence[int]) -> LengthStatistics:
    if not values:
        return LengthStatistics(0, 0, 0.0, 0, 0, 0, 0)
    ordered = sorted(values)

    def quantile(fraction: float) -> int:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    total = sum(ordered)
    return LengthStatistics(
        len(ordered), total, total / len(ordered), quantile(0.5), quantile(0.9), quantile(0.99), ordered[-1]
    )


def source_statistics(
    source: str, traced: TracedExamples, pool: DeduplicatedPool, stream: SourceStream
) -> SourceStatistics:
    return SourceStatistics(
        source=source,
        traced_steps=len(traced.train[source]) + traced.forbidden[source],
        forbidden_steps=traced.forbidden[source],
        duplicates=pool.duplicates_by_source[source],
        examined=stream.examined,
        over_length=stream.over_length,
        selected=len(stream.accepted),
        prompt_tokens=length_statistics([example.prompt_token_count for example in stream.accepted]),
        completion_tokens=length_statistics([example.completion_token_count for example in stream.accepted]),
        total_tokens=stream.tokens,
    )


def write_examples(path: Path, examples: Iterable[SftExample]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def read_examples(path: Path) -> Iterator[SftExample]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            fields["goals"] = tuple(fields["goals"])
            yield SftExample(**fields)
