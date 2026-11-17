"""The offline arm (O): v0's adapter continued by supervised fine-tuning on the pool's known proofs, without visible
reasoning (experiments/offline_arm.py; DESIGN.md, "Follow-up study: controlled arms", "The offline arm").

The pool keeps each statement's verified proof only as its source and length, so the proof's text is recovered from
the source corpora as phase 2 normalized them (`recovered_candidates`): of a statement's distinct proofs in that source
the three first in phase 2's hash order, those of the recorded tactic count and characters. Statements the evaluations
hold out, and near-duplicates of them, are dropped first (`pool_selection`). Each proof is then walked in Lean the way
the search runs policy blocks (rl/offline_walk.py) into examples: the state before a block of 1-5 tactics and the
block, in v0's no-reasoning SFT format. Two training sets come from them: every walked proof ("pool", O1) and a
stratified subsample of about an expert-iteration arm's completion tokens ("matched", O2, `matched_sample`).
"""

import hashlib
import json
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy

from lean_search.corpora.decontamination import canonical_statement
from lean_search.corpora.normalize import normalized_proof_text, short_hash
from lean_search.corpora.pipeline import PROOFS_PER_STATEMENT
from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.expert_iteration.near_duplicates import MinHasher, exhaustive_matches
from lean_search.expert_iteration.pool import problem_name
from lean_search.rl.expert_iteration_data import ReplayConfig
from lean_search.rl.fixed_sets import character_stratum
from lean_search.rl.training_overlap import exhaustive_duplicates, fingerprints
from lean_search.search.records import from_json_object
from lean_search.training.sft import SftConfig
from lean_search.training.sft_data import SftExample

EXAMPLE_SOURCE = "offline_arm"


class Subset(StrEnum):
    # O1: every usable pool proof that walked.
    POOL = "pool"
    # O2: the stratified subsample matched to an expert-iteration arm's completion tokens.
    MATCHED = "matched"


@dataclass(frozen=True)
class OfflineDataConfig:
    # Under $LEAN_SEARCH_DATA: the frozen pool and its sha256 (base.toml's [statements.curriculum]).
    pool: str
    pool_sha256: str
    # Under $LEAN_SEARCH_DATA: the sets the evaluations hold out (base.toml's [statements] held_out).
    held_out_sets: tuple[str, ...]
    # Under $LEAN_SEARCH_RUNS: the 512 held-out states, whose statements are held out too.
    held_out_states_file: str
    # A pool statement whose formal statement, or root state, reaches this estimated Jaccard with a held-out one's is
    # dropped (the probe's near-duplicate threshold, rl/training_overlap.py).
    near_duplicate_threshold: float = 0.7
    # Statements whose examples validate instead of training (both subsets).
    validation_fraction: float = 0.02
    seed: str = "offline-arm"


@dataclass(frozen=True)
class WalkConfig:
    # The search whose policy blocks the walk reproduces: its tactic limits, flattening, naming, identifier check,
    # forbidden steps and the policy's completion cap.
    search_config: str
    processes: int = 90
    max_block_tactics: int = 5
    seed: str = "offline-arm-blocks"
    # The policy server's context (serve_model.sh's MAX_MODEL_LEN 8192) less the policy's completion cap.
    max_prompt_tokens: int = 7168


@dataclass(frozen=True)
class MatchedConfig:
    # About an expert-iteration arm's completion tokens over its 16 phases (~0.13M per phase at window 1).
    completion_tokens: int = 2_000_000
    # Probe v2's bands of proof characters (rl/fixed_sets.CharacterStrataConfig.edges).
    band_edges: tuple[int, ...] = (500, 1000, 1500, 2000, 3000, 4500)
    seed: str = "offline-arm-matched"
    # An expert-iteration arm with a 4-phase window sees each block about 4 times; the pool subset takes sft's epochs.
    epochs: int = 4


@dataclass(frozen=True)
class OfflineArmConfig:
    # The arm's directories: $LEAN_SEARCH_DATA/<name>, and $LEAN_SEARCH_CHECKPOINTS/<name>_<subset>_<rate>.
    name: str
    # v0's adapter (base.toml's [initial] policy_adapter), continued by every run.
    initial_policy_adapter: str
    # As written in run names ("5e-5").
    learning_rates: tuple[str, ...]
    data: OfflineDataConfig
    walk: WalkConfig
    matched: MatchedConfig
    replay: ReplayConfig
    # `data` and `initial_adapter` are filled in per run.
    sft: SftConfig


def load_offline_arm_config(path: Path) -> OfflineArmConfig:
    config = from_json_object(OfflineArmConfig, tomllib.loads(path.read_text(encoding="utf-8")))
    for rate in config.learning_rates:
        if float(rate) <= 0:
            raise ValueError(f"Learning rate {rate} must be positive.")
    if config.matched.epochs < 1:
        raise ValueError("matched.epochs must be at least 1.")
    if config.walk.max_block_tactics < 1:
        raise ValueError("walk.max_block_tactics must be at least 1.")
    return config


def subset_epochs(config: OfflineArmConfig, subset: Subset) -> int:
    match subset:
        case Subset.MATCHED:
            return config.matched.epochs
        case Subset.POOL:
            return config.sft.optimization.epochs


def run_label(subset: Subset, rate: str) -> str:
    return f"{subset}_{rate}"


def run_name(config: OfflineArmConfig, subset: Subset, rate: str) -> str:
    return f"{config.name}_{run_label(subset, rate)}"


# Selection of the pool's statements.


class Exclusion(StrEnum):
    """Why a pool statement gives no example, in the order the reasons are tried."""

    UNUSABLE = "not verified, or closed by the automation alone"
    HELD_OUT_SET = "in a held-out set (probe v2, its twins, the old probe, the gate)"
    HELD_OUT_STATE = "the statement of a held-out state"
    NEAR_HELD_OUT_STATEMENT = "formal statement near a held-out one"
    NEAR_HELD_OUT_ROOT = "root state near a held-out statement's"


@dataclass(frozen=True)
class HeldOutReferences:
    names: frozenset[str]
    # Canonical statements of the held-out states.
    state_statements: frozenset[str]
    # Every held-out statement's formal statement, the held-out states' included.
    formal_statements: tuple[str, ...]
    # The held-out sets' root states, as the pool records them.
    root_states: tuple[tuple[str, ...], ...]


def held_out_references(
    held_out: Iterable[StatementRecord], state_statements: Iterable[str], pool: Sequence[VerifiedStatement]
) -> HeldOutReferences:
    held_out = list(held_out)
    state_statements = list(state_statements)
    names = frozenset(problem_name(record) for record in held_out)
    roots = tuple(record.root_goals for record in pool if record.name in names and record.root_goals)
    return HeldOutReferences(
        names,
        frozenset(canonical_statement(statement) for statement in state_statements),
        (*(record.formal_statement for record in held_out), *dict.fromkeys(state_statements)),
        roots,
    )


@dataclass(frozen=True)
class PoolSelection:
    kept: tuple[VerifiedStatement, ...]
    # Per `Exclusion` value, the statements dropped for it.
    dropped: dict[str, int]


def is_usable(record: VerifiedStatement) -> bool:
    return record.verified and not record.automation_solved and not record.load_failed


def statement_signatures(statements: Sequence[str]) -> numpy.ndarray:
    hasher = MinHasher()
    return numpy.stack([hasher.signature(statement) for statement in statements])


def pool_selection(pool: Sequence[VerifiedStatement], references: HeldOutReferences, threshold: float) -> PoolSelection:
    """The usable statements no exclusion drops, each counted under the first reason that applies; the near-duplicate
    checks compare every pair (no LSH)."""
    dropped: Counter[str] = Counter()
    remaining: list[VerifiedStatement] = []
    for record in pool:
        if not is_usable(record):
            dropped[Exclusion.UNUSABLE] += 1
        elif record.name in references.names:
            dropped[Exclusion.HELD_OUT_SET] += 1
        elif canonical_statement(record.statement.formal_statement) in references.state_statements:
            dropped[Exclusion.HELD_OUT_STATE] += 1
        else:
            remaining.append(record)
    if remaining and references.formal_statements:
        near = exhaustive_matches(
            statement_signatures(references.formal_statements),
            statement_signatures([record.statement.formal_statement for record in remaining]),
            threshold,
        )
        dropped[Exclusion.NEAR_HELD_OUT_STATEMENT] += sum(near)
        remaining = [record for record, hit in zip(remaining, near, strict=True) if not hit]
    if remaining and references.root_states:
        near = exhaustive_duplicates(
            fingerprints([record.root_goals for record in remaining]), fingerprints(references.root_states), threshold
        )
        dropped[Exclusion.NEAR_HELD_OUT_ROOT] += sum(near)
        remaining = [record for record, hit in zip(remaining, near, strict=True) if not hit]
    return PoolSelection(tuple(remaining), {reason.value: dropped[reason] for reason in Exclusion})


# Recovering the proofs' text.


@dataclass(frozen=True)
class ProofTarget:
    """What the pool recorded of a statement's verified proof."""

    source: str
    tactics: int
    characters: int


@dataclass(frozen=True)
class CorpusProof:
    """A normalized proof of a target statement, as phase 2 named it (`<source>/<shard>/<row>`)."""

    statement_key: str
    source: str
    identifier: str
    tactic_proof: str
    tactics: int

    @property
    def proof_key(self) -> str:
        return short_hash(normalized_proof_text(self.tactic_proof))


def recovered_candidates(
    targets: Mapping[str, ProofTarget], proofs: Iterable[CorpusProof]
) -> dict[str, tuple[str, ...]]:
    """Per target statement, the proofs that can be the verified one, in the order verification tried them: phase 2
    kept, per source and statement, one proof per whitespace-normalized text (the first by identifier) and of those
    the `PROOFS_PER_STATEMENT` first by the hash of statement and proof key; the pool verified the shortest first,
    ties in identifier order. Statements without a candidate are missing."""
    distinct: dict[tuple[str, str, str], CorpusProof] = {}
    for proof in proofs:
        target = targets.get(proof.statement_key)
        if target is None or proof.source != target.source:
            continue
        key = (proof.statement_key, proof.source, proof.proof_key)
        known = distinct.get(key)
        if known is None or proof.identifier < known.identifier:
            distinct[key] = proof
    by_statement: dict[str, list[CorpusProof]] = defaultdict(list)
    for proof in distinct.values():
        by_statement[proof.statement_key].append(proof)
    candidates: dict[str, tuple[str, ...]] = {}
    for key, found in by_statement.items():
        kept = sorted(found, key=lambda proof: short_hash(key + proof.proof_key))[:PROOFS_PER_STATEMENT]
        target = targets[key]
        matching = sorted(
            (
                proof
                for proof in kept
                if (proof.tactics, len(proof.tactic_proof)) == (target.tactics, target.characters)
            ),
            key=lambda proof: proof.identifier,
        )
        if matching:
            candidates[key] = tuple(proof.tactic_proof for proof in matching)
    return candidates


@dataclass(frozen=True)
class PoolProof:
    """A selected pool statement with its candidate proofs (usually one), to be walked."""

    name: str
    statement: StatementRecord
    proof_characters: int
    proof_tactics: int
    candidates: tuple[str, ...]


def read_pool_proofs(path: Path) -> list[PoolProof]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(PoolProof, json.loads(line)) for line in lines if line.strip()]


# Blocks and examples.


@dataclass(frozen=True)
class ExampleTokens:
    prompt: int
    completion: int


@dataclass(frozen=True)
class ProofExamples:
    """A walked proof's examples as the training sets take them."""

    name: str
    proof_characters: int
    examples: tuple[SftExample, ...]
    tokens: tuple[ExampleTokens, ...]

    @property
    def completion_tokens(self) -> int:
        return sum(tokens.completion for tokens in self.tokens)

    @property
    def prompt_tokens(self) -> int:
        return sum(tokens.prompt for tokens in self.tokens)


def hash_order(seed: str, name: str) -> bytes:
    return hashlib.sha256(f"{seed}\n{name}".encode()).digest()


@dataclass(frozen=True)
class BandSize:
    band: str
    proofs: int
    examples: int
    prompt_tokens: int
    completion_tokens: int


def band_sizes(proofs: Sequence[ProofExamples], edges: Sequence[int]) -> tuple[BandSize, ...]:
    """Per band of proof characters (every band, in order), what the proofs hold."""
    bands = [character_stratum(low, edges) for low in (0, *edges)]
    by_band: dict[str, list[ProofExamples]] = {band: [] for band in bands}
    for proof in proofs:
        by_band[character_stratum(proof.proof_characters, edges)].append(proof)
    return tuple(
        BandSize(
            band,
            len(members),
            sum(len(member.examples) for member in members),
            sum(member.prompt_tokens for member in members),
            sum(member.completion_tokens for member in members),
        )
        for band, members in by_band.items()
    )


def matched_sample(proofs: Sequence[ProofExamples], config: MatchedConfig) -> list[ProofExamples]:
    """Proofs drawn one per band in turn (each band in a seeded hash order; a band that runs out drops out of the
    turns), so the bands hold equal numbers as far as the pool allows, until their examples' completion tokens reach
    `completion_tokens`."""
    bands = [character_stratum(low, config.band_edges) for low in (0, *config.band_edges)]
    queues: dict[str, list[ProofExamples]] = {band: [] for band in bands}
    for proof in proofs:
        queues[character_stratum(proof.proof_characters, config.band_edges)].append(proof)
    for members in queues.values():
        members.sort(key=lambda proof: hash_order(config.seed, proof.name), reverse=True)
    chosen: list[ProofExamples] = []
    tokens = 0
    while tokens < config.completion_tokens and any(queues.values()):
        for band in bands:
            if tokens >= config.completion_tokens:
                break
            if queues[band]:
                proof = queues[band].pop()
                chosen.append(proof)
                tokens += proof.completion_tokens
    return chosen
