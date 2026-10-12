"""Lemma-aware SFT data: traced steps whose prompts carry annotated lemma lists of varying length."""

import dataclasses
import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.corpora.records import TracedStep
from lean_search.policy.prompts import render_completion, render_prompt
from lean_search.retrieval.config import DEFAULT_RETRIEVER, ApplicabilityConfig
from lean_search.retrieval.premises import RetrievedPremise
from lean_search.training.sft_data import SftExample, TokenizedExample, Tokenizer


@dataclass(frozen=True)
class LemmaSftExample:
    source: str
    proof_identifier: str
    step_index: int
    goals: tuple[str, ...]
    lemmas: tuple[str, ...]
    tactic_block: str
    lemma_count: int
    # Premises the step names, and how many of them the shown list contains.
    step_premises: tuple[str, ...] = ()
    shown_step_premises: int = 0
    injected_step_premises: int = 0


@dataclass(frozen=True)
class ProofUnit:
    source: str
    proof_identifier: str
    steps: tuple[TracedStep, ...]
    estimated_tokens: int


@dataclass(frozen=True)
class LemmaDataConfig:
    sources: tuple[str, ...]
    # Estimated prompt plus completion tokens; the lemma part is estimated from `estimated_tokens_per_lemma`.
    token_budget: int
    validation_examples: int = 2000
    # Each example draws its list length uniformly from these, so one adapter serves every ablation arm.
    lemma_counts: tuple[int, ...] = (0, 4, 8, 16, 32)
    candidate_count: int = 32
    # With this probability, premises the step names but retrieval missed replace random candidates.
    step_premise_injection: float = 0.5
    estimated_tokens_per_lemma: int = 45
    max_prompt_tokens: int = 4096
    max_completion_tokens: int = 256
    max_signature_characters: int = 256
    reference_tokenizer: str = "Qwen/Qwen3.5-2B"
    seed: str = "phase4-lemmas"
    # Hugging Face name or fine-tuned encoder directory whose premise embeddings exist.
    retriever: str = DEFAULT_RETRIEVER
    # The check the search runs; the data must use the same one.
    applicability: ApplicabilityConfig = field(default_factory=ApplicabilityConfig)


def stable_fraction(seed: str, purpose: str, key: str) -> float:
    digest = hashlib.sha256(f"{seed}\n{purpose}\n{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def step_key(step: TracedStep) -> str:
    return f"{step.proof_identifier}#{step.step_index}"


def lemma_count_for(key: str, lemma_counts: Sequence[int], seed: str) -> int:
    return lemma_counts[int(stable_fraction(seed, "lemma count", key) * len(lemma_counts))]


def inject_step_premises(
    candidates: Sequence[RetrievedPremise], missing: Sequence[RetrievedPremise], key: str, seed: str
) -> tuple[RetrievedPremise, ...]:
    """Each missing premise takes a pseudo-random rank's score and position; the lowest-ranked candidates leave."""
    kept = list(candidates[: len(candidates) - len(missing)])
    for index, premise in enumerate(missing):
        rank = int(stable_fraction(seed, f"injection rank {index}", key) * len(candidates))
        score = candidates[min(rank, len(candidates) - 1)].score
        kept.insert(min(rank, len(kept)), dataclasses.replace(premise, score=score))
    return tuple(kept)


def select_proofs(proofs_by_source: Mapping[str, Sequence[ProofUnit]], token_budget: int) -> dict[str, list[ProofUnit]]:
    """Equal token shares per source in the given proof order; shares of exhausted sources go to the others."""
    selected: dict[str, list[ProofUnit]] = {source: [] for source in proofs_by_source}
    tokens = dict.fromkeys(proofs_by_source, 0)
    positions = dict.fromkeys(proofs_by_source, 0)
    active = {source for source, proofs in proofs_by_source.items() if proofs}
    remaining = float(token_budget) if token_budget else math.inf
    while active:
        share = remaining / len(active)
        exhausted = set()
        for source in active:
            proofs = proofs_by_source[source]
            while tokens[source] < share and positions[source] < len(proofs):
                selected[source].append(proofs[positions[source]])
                tokens[source] += proofs[positions[source]].estimated_tokens
                positions[source] += 1
            if positions[source] == len(proofs) and tokens[source] < share:
                exhausted.add(source)
        if not exhausted:
            break
        remaining -= sum(tokens[source] for source in exhausted)
        active -= exhausted
    return selected


def subsample_indices(
    examples: Sequence[LemmaSftExample], token_counts: Sequence[int], token_budget: int, seed: str
) -> list[int]:
    """Ascending indices of about `token_budget` tokens in which each list length keeps its token share."""
    totals: Counter[int] = Counter()
    for example, count in zip(examples, token_counts, strict=True):
        totals[example.lemma_count] += count
    total = sum(totals.values())
    order = sorted(
        range(len(examples)),
        key=lambda index: stable_fraction(
            seed, "subsample", f"{examples[index].proof_identifier}#{examples[index].step_index}"
        ),
    )
    taken: Counter[int] = Counter()
    chosen: set[int] = set()
    for index in order:
        lemma_count = examples[index].lemma_count
        if taken[lemma_count] < token_budget * totals[lemma_count] / total:
            chosen.add(index)
            taken[lemma_count] += token_counts[index]
    return sorted(chosen)


def tokenize_lemma_example(tokenizer: Tokenizer, example: LemmaSftExample) -> TokenizedExample:
    prompt_ids = tokenizer.encode(render_prompt(tokenizer, example.goals, example.lemmas), add_special_tokens=False)
    completion_ids = tokenizer.encode(render_completion(example.tactic_block), add_special_tokens=False)
    plain = SftExample(
        example.source, example.proof_identifier, example.step_index, example.goals, example.tactic_block
    )
    return TokenizedExample(plain, tuple(prompt_ids + completion_ids), len(prompt_ids))


def write_lemma_examples(path: Path, examples: Iterable[LemmaSftExample]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_lemma_examples(path: Path) -> Iterator[LemmaSftExample]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            for name in ("goals", "lemmas", "step_premises"):
                fields[name] = tuple(fields[name])
            yield LemmaSftExample(**fields)
