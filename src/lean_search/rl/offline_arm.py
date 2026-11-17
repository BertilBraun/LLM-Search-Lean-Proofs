"""The offline arm's data: pool selection, proof recovery, examples and subsets (DESIGN.md, "The offline arm")."""

import dataclasses
import hashlib
import json
import statistics
import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy

from lean_search.corpora.decontamination import canonical_statement
from lean_search.corpora.normalize import normalized_proof_text, short_hash
from lean_search.corpora.pipeline import PROOFS_PER_STATEMENT
from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.expert_iteration.mixing import is_held_out
from lean_search.expert_iteration.near_duplicates import MinHasher, exhaustive_matches
from lean_search.expert_iteration.pool import problem_name
from lean_search.rl.expert_iteration_data import ReplayConfig
from lean_search.rl.fixed_sets import character_stratum, hash_order
from lean_search.rl.offline_walk import WalkBlock, WalkedProof, WalkSettings, WalkStatus
from lean_search.rl.training_overlap import exhaustive_duplicates, fingerprints
from lean_search.search.records import from_json_object
from lean_search.training.sft import SftConfig, StepRecord
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
    # The search whose policy blocks the walk reproduces (limits, flattening, naming, checks, completion cap).
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
    # Per `Exclusion` value (preparation.json's keys), the statements dropped for it.
    dropped: dict[str, int]


def is_usable(record: VerifiedStatement) -> bool:
    return record.verified and not record.automation_solved and not record.load_failed


def statement_signatures(statements: Sequence[str]) -> numpy.ndarray:
    hasher = MinHasher()
    return numpy.stack([hasher.signature(statement) for statement in statements])


def pool_selection(pool: Sequence[VerifiedStatement], references: HeldOutReferences, threshold: float) -> PoolSelection:
    """The usable statements no exclusion drops (every pair compared), each drop under its first reason."""
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
    """Per statement, the matching proofs phase 2's per-source cap kept, in the pool's verification order."""
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
    # The valid prefix of a walk that failed later, not a whole proof.
    prefix: bool = False

    @property
    def completion_tokens(self) -> int:
        return sum(tokens.completion for tokens in self.tokens)

    @property
    def prompt_tokens(self) -> int:
        return sum(tokens.prompt for tokens in self.tokens)


@dataclass(frozen=True)
class BandSize:
    band: str
    proofs: int
    examples: int
    prompt_tokens: int
    completion_tokens: int
    # Of `proofs`, those that are a failed walk's prefix.
    prefix_proofs: int = 0


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
            sum(member.prefix for member in members),
        )
        for band, members in by_band.items()
    )


def matched_sample(proofs: Sequence[ProofExamples], config: MatchedConfig) -> list[ProofExamples]:
    """One proof per band in turn, each band in a seeded order, until the examples hold `completion_tokens`."""
    bands = [character_stratum(low, config.band_edges) for low in (0, *config.band_edges)]
    queues: dict[str, list[ProofExamples]] = {band: [] for band in bands}
    for proof in proofs:
        queues[character_stratum(proof.proof_characters, config.band_edges)].append(proof)
    for members in queues.values():
        members.sort(key=lambda proof: hash_order(proof.name, config.seed), reverse=True)
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


# A walk that failed at a block, or at a forbidden step, keeps the blocks before it: steps of a verified proof that ran
# as the search runs them. Other failed walks give nothing (a revisit, goals left at the end, no start).
PREFIX_STATUSES = frozenset({WalkStatus.BLOCK_FAILED, WalkStatus.FORBIDDEN})


def usable_blocks(walked: WalkedProof) -> tuple[WalkBlock, ...]:
    if walked.walk.status == WalkStatus.COMPLETE or walked.walk.status in PREFIX_STATUSES:
        return walked.walk.blocks
    return ()


@dataclass(frozen=True)
class ExampleCounts:
    # Examples dropped: a (state, block) pair an earlier proof gave, a prompt over the cap, a state near a held-out one.
    duplicates: int
    over_prompt_cap: int
    near_held_out_state: int
    # Kept examples at a block depth the probe's search never expands (its max_depth).
    beyond_search_depth: int
    # Kept examples from the prefix of a walk that failed later, and the proofs they came from.
    prefix_examples: int
    prefix_proofs: int


@dataclass(frozen=True)
class SplitExamples:
    train: tuple[ProofExamples, ...]
    validation: tuple[ProofExamples, ...]
    counts: ExampleCounts
    # Kept training examples by their block's tactics.
    block_tactics: dict[int, int]


def split_examples(
    walks: Sequence[WalkedProof],
    characters: Mapping[str, int],
    tokenize: Callable[[SftExample], ExampleTokens],
    near_held_out_states: frozenset[tuple[str, ...]],
    config: OfflineArmConfig,
    max_search_depth: int,
) -> SplitExamples:
    """The proofs' examples, in a seeded proof order, each statement in training or validation."""
    seen: set[tuple[tuple[str, ...], str]] = set()
    counts: Counter[str] = Counter()
    lengths: Counter[int] = Counter()
    train: list[ProofExamples] = []
    validation: list[ProofExamples] = []
    for walked in sorted(walks, key=lambda walked: hash_order(walked.name, config.walk.seed)):
        blocks = usable_blocks(walked)
        examples: list[SftExample] = []
        tokens: list[ExampleTokens] = []
        tactics: list[int] = []
        for index, block in enumerate(blocks):
            if (block.goals, block.block) in seen:
                counts["duplicates"] += 1
                continue
            seen.add((block.goals, block.block))
            if block.goals in near_held_out_states:
                counts["near_held_out_state"] += 1
                continue
            example = SftExample(EXAMPLE_SOURCE, walked.name, index, block.goals, block.block)
            found = tokenize(example)
            if found.prompt > config.walk.max_prompt_tokens:
                counts["over_prompt_cap"] += 1
                continue
            examples.append(example)
            tokens.append(found)
            tactics.append(block.tactics)
            counts["beyond_search_depth"] += index >= max_search_depth
        if not examples:
            continue
        prefix = walked.walk.status != WalkStatus.COMPLETE
        if prefix:
            counts["prefix_examples"] += len(examples)
            counts["prefix_proofs"] += 1
        proof = ProofExamples(walked.name, characters[walked.name], tuple(examples), tuple(tokens), prefix)
        if is_held_out(walked.name, config.data.seed, config.data.validation_fraction):
            validation.append(proof)
        else:
            train.append(proof)
            lengths.update(tactics)
    return SplitExamples(
        tuple(train),
        tuple(validation),
        ExampleCounts(
            duplicates=counts["duplicates"],
            over_prompt_cap=counts["over_prompt_cap"],
            near_held_out_state=counts["near_held_out_state"],
            beyond_search_depth=counts["beyond_search_depth"],
            prefix_examples=counts["prefix_examples"],
            prefix_proofs=counts["prefix_proofs"],
        ),
        dict(sorted(lengths.items())),
    )


@dataclass(frozen=True)
class BandWalks:
    band: str
    # Per walk status, the proofs.
    statuses: dict[str, int]


def band_walks(
    walks: Sequence[WalkedProof], characters: Mapping[str, int], edges: Sequence[int]
) -> tuple[BandWalks, ...]:
    """Per band of proof characters, the walks' statuses: the walk's selection by proof length."""
    by_band: dict[str, Counter[str]] = {character_stratum(low, edges): Counter() for low in (0, *edges)}
    for walked in walks:
        by_band[character_stratum(characters[walked.name], edges)][walked.walk.status] += 1
    return tuple(BandWalks(band, dict(sorted(statuses.items()))) for band, statuses in by_band.items())


# The share of the host's memory limit the training ranks' tokenized data may take together.
MAX_HOST_MEMORY_SHARE = 0.8


def ranks_fit(peak_bytes: int, ranks: int, limit_bytes: int) -> bool:
    """Whether `ranks` processes of a dry run's peak memory fit the host (each rank tokenizes all the data)."""
    return ranks * peak_bytes <= MAX_HOST_MEMORY_SHARE * limit_bytes


def median_step_tokens_per_second(records: Sequence[StepRecord], warmup_steps: int) -> float | None:
    """The median step's rate after the first `warmup_steps`: what a step costs when nothing stalls it; None before
    any. Not for planning wall time (`sustained_tokens_per_second` is)."""
    if len(records) <= warmup_steps:
        return None
    seconds = [record.training_seconds for record in records]
    rates = [
        record.tokens / (seconds[index] - (seconds[index - 1] if index else 0.0))
        for index, record in enumerate(records)
        if index >= warmup_steps
    ]
    return statistics.median(rates)


def sustained_tokens_per_second(records: Sequence[StepRecord], warmup_steps: int) -> float | None:
    """All tokens over all training seconds after the first `warmup_steps`, stalls included; None before any."""
    if len(records) <= warmup_steps:
        return None
    start = records[warmup_steps - 1].training_seconds if warmup_steps else 0.0
    return sum(record.tokens for record in records[warmup_steps:]) / (records[-1].training_seconds - start)


# Under src/lean_search: the walk and the search code it runs a block with (naming, planning, identifier check,
# normalization, the REPL's block execution); a change to any of them can change a walk's output.
WALK_SOURCES = (
    "rl/offline_walk.py",
    "search/search.py",
    "lean/plans.py",
    "lean/text.py",
    "lean/hypotheses.py",
    "lean/identifiers.py",
    "lean/repl.py",
    "policy/prompts.py",
)


@dataclass(frozen=True)
class WalkFingerprint:
    # Per source in WALK_SOURCES, its sha256.
    sources: dict[str, str]
    # The walk settings, the block draw and the completion cap, as canonical JSON.
    settings: str
    # proofs.jsonl's sha256: the proofs walked, after the exclusions.
    proofs_sha256: str


def walk_settings_text(settings: WalkSettings, config: WalkConfig, tokenizer: str, max_completion_tokens: int) -> str:
    fields = dataclasses.asdict(settings) | {
        "forbidden_tokens": sorted(settings.forbidden_tokens),
        "seed": config.seed,
        "max_block_tactics": config.max_block_tactics,
        "tokenizer": tokenizer,
        "max_completion_tokens": max_completion_tokens,
    }
    return json.dumps(fields, sort_keys=True)


def walk_fingerprint(package: Path, settings_text: str, proofs_sha256: str) -> WalkFingerprint:
    sources = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in WALK_SOURCES}
    return WalkFingerprint(sources, settings_text, proofs_sha256)


def fingerprint_differences(recorded: WalkFingerprint, current: WalkFingerprint) -> list[str]:
    """What differs, by name: a source, the walk settings, the proofs."""
    names = sorted({*recorded.sources, *current.sources})
    differences = [name for name in names if recorded.sources.get(name) != current.sources.get(name)]
    if recorded.settings != current.settings:
        differences.append("the walk settings")
    if recorded.proofs_sha256 != current.proofs_sha256:
        differences.append("proofs.jsonl")
    return differences
