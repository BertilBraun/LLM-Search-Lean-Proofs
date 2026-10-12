"""Per-shard digests: the policy and value samples of a closed shard's trees, extracted once.

Training reads each closed shard a single time (digests/<shard>/{policy,jumps,values}.jsonl and summary.json, written
to a temporary directory and renamed). Policy samples come from every verified proof of a tree (the first and
harvested ones, each step sequence once): at each policy step, the step against dead and failed siblings (per-kind
caps), or alone (its NLL) when no sibling qualifies and `chosen_only_steps` is set; automation steps give nothing, so
automation-only proofs add only value labels. Value-jump pairs are kept apart: training uses them only while the value
model passes its gate. Value samples are a tree's labels except the lossless open frontier, at most
`max_labels_per_tree`: exact ones first, then dead ones, then censored ones in a fixed pseudo-random order; dead
labels stay, as they teach the value model that dead ends are far from a proof. Every record carries the model version
that produced its tree, and pairs carry the reasoning behind their steps when the policy thought.
"""

import hashlib
import json
import os
import shutil
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.pool import problem_source
from lean_search.expert_iteration.preferences import NO_REASONING, ValueJumpConfig, node_pairs, value_jump_pairs
from lean_search.expert_iteration.proofs import EXPERT_ITERATION_SOURCE, FoundProof, found_proofs, uses_policy
from lean_search.expert_iteration.shards import (
    closed_shards,
    read_attempt_reasoning,
    read_attempt_tree,
    read_attempts,
    read_shard_summary,
)
from lean_search.expert_iteration.thinking import ThinkingContext, TreeReasoning, edge_reasoning
from lean_search.expert_iteration.value_data import carries_no_loss
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search import TreeRecord
from lean_search.search.records import from_json_object, to_json
from lean_search.training.dpo_data import PreferencePair, pair_key
from lean_search.value.labels import LabelKind, TreeLabelConfig, ValueExample, tree_examples

SUMMARY_FILE = "summary.json"
POLICY_FILE = "policy.jsonl"
JUMPS_FILE = "jumps.jsonl"
VALUES_FILE = "values.jsonl"
CONTEXTS_FILE = "contexts.jsonl"
LABEL_PRIORITY = {LabelKind.EXACT: 0, LabelKind.DEAD: 1, LabelKind.AT_LEAST: 2}


@dataclass(frozen=True)
class DigestConfig:
    preferences: PreferenceConfig
    chosen_only_steps: bool
    value_jumps: ValueJumpConfig
    labels: TreeLabelConfig
    max_labels_per_tree: int


@dataclass(frozen=True)
class VersionedPair:
    model_version: int
    pair: PreferencePair


@dataclass(frozen=True)
class VersionedValueExample:
    model_version: int
    example: ValueExample
    # The value model's h for the state when the search scored it; None for unscored nodes.
    estimate: float | None


@dataclass(frozen=True)
class DigestSummary:
    shard: str
    attempts: int
    trees: int
    proofs: int
    # Of the proofs, those with at least one policy step.
    policy_proofs: int
    policy_samples: int
    jump_pairs: int
    value_samples: int
    versions: tuple[int, ...]
    shard_closed_at: str


@dataclass(frozen=True)
class ShardDigest:
    proofs: int
    policy_proofs: int
    policy: list[VersionedPair]
    jumps: list[VersionedPair]
    values: list[VersionedValueExample]
    contexts: list[ThinkingContext]


def label_order(example: VersionedValueExample) -> tuple[int, bytes]:
    goals = "\0".join((example.example.identifier, *example.example.goals))
    return LABEL_PRIORITY[example.example.kind], hashlib.sha256(goals.encode()).digest()


def tree_value_samples(record: TreeRecord, version: int, config: DigestConfig) -> list[VersionedValueExample]:
    examples = tree_examples(record, problem_source(record.problem_name), config.labels)
    labelled_nodes = [node for node in record.nodes if node.goals]
    samples = [
        VersionedValueExample(version, example, node.value_estimate)
        for node, example in zip(labelled_nodes, examples, strict=True)
        if not carries_no_loss(example)
    ]
    return sorted(samples, key=label_order)[: config.max_labels_per_tree]


def thinking_context(record: TreeRecord, proof: FoundProof, step_index: int, header: str, key: str) -> ThinkingContext:
    steps = proof.steps
    return ThinkingContext(
        key,
        header,
        record.statement,
        tuple(step.step for step in steps[:step_index]),
        steps[step_index].goals,
        tuple(record.nodes[step.child_id].goals for step in steps[step_index:]),
    )


def proof_policy_samples(
    record: TreeRecord, proof: FoundProof, version: int, config: DigestConfig, reasoning: TreeReasoning | None
) -> tuple[list[VersionedPair], list[ThinkingContext]]:
    """The proof's pairs, and the context of each pair whose chosen step has reasoning."""
    edges = NO_REASONING if reasoning is None else edge_reasoning(record, reasoning.steps)
    samples = []
    contexts = []
    for node in node_pairs(record, proof, config.preferences, edges):
        step = proof.steps[node.step_index]
        pairs = list(node.pairs)
        if not pairs and config.chosen_only_steps:
            pairs.append(
                PreferencePair(
                    EXPERT_ITERATION_SOURCE,
                    proof.identifier,
                    node.step_index,
                    step.goals,
                    normalize_tactic_block(step.step),
                    None,
                    "none",
                    edges.get(record.nodes[step.child_id].edge_id),
                )
            )
        samples.extend(VersionedPair(version, pair) for pair in pairs)
        if reasoning is not None:
            contexts.extend(
                thinking_context(record, proof, node.step_index, reasoning.header, pair_key(pair).hex())
                for pair in pairs
                if pair.chosen_reasoning is not None
            )
    return samples, contexts


def digest_shard(shard: Path, config: DigestConfig) -> ShardDigest:
    proofs = policy_proofs = 0
    policy: list[VersionedPair] = []
    jumps: list[VersionedPair] = []
    values: list[VersionedValueExample] = []
    contexts: list[ThinkingContext] = []
    for attempt in read_attempts(shard):
        if attempt.tree_file is None:
            continue
        record = read_attempt_tree(shard, attempt)
        reasoning = read_attempt_reasoning(shard, attempt)
        edges = NO_REASONING if reasoning is None else edge_reasoning(record, reasoning.steps)
        version = attempt.model_version
        run = f"v{version}"
        values.extend(tree_value_samples(record, version, config))
        if config.value_jumps.enabled:
            jumps.extend(
                VersionedPair(version, pair) for pair in value_jump_pairs(record, run, config.value_jumps, edges)
            )
        for proof in found_proofs(run, record):
            proofs += 1
            if uses_policy(proof):
                policy_proofs += 1
                proof_samples, proof_contexts = proof_policy_samples(record, proof, version, config, reasoning)
                policy.extend(proof_samples)
                contexts.extend(proof_contexts)
    return ShardDigest(proofs, policy_proofs, policy, jumps, values, contexts)


def write_lines(path: Path, records: Sequence[object]) -> None:
    path.write_text("".join(to_json(record) + "\n" for record in records), encoding="utf-8")


def write_digest(digests: Path, shard: Path, digest: ShardDigest) -> DigestSummary:
    shard_summary = read_shard_summary(shard)
    summary = DigestSummary(
        shard=shard.name,
        attempts=shard_summary.attempts,
        trees=sum(attempt.tree_file is not None for attempt in read_attempts(shard)),
        proofs=digest.proofs,
        policy_proofs=digest.policy_proofs,
        policy_samples=len(digest.policy),
        jump_pairs=len(digest.jumps),
        value_samples=len(digest.values),
        versions=shard_summary.versions,
        shard_closed_at=shard_summary.closed_at,
    )
    temporary = digests / f"{shard.name}.tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    write_lines(temporary / POLICY_FILE, digest.policy)
    write_lines(temporary / JUMPS_FILE, digest.jumps)
    write_lines(temporary / VALUES_FILE, digest.values)
    write_lines(temporary / CONTEXTS_FILE, digest.contexts)
    (temporary / SUMMARY_FILE).write_text(to_json(summary), encoding="utf-8")
    os.replace(temporary, digests / shard.name)
    return summary


def digested(digests: Path) -> list[Path]:
    if not digests.exists():
        return []
    return sorted(path for path in digests.iterdir() if path.is_dir() and (path / SUMMARY_FILE).exists())


def read_digest_summary(digest: Path) -> DigestSummary:
    return from_json_object(DigestSummary, json.loads((digest / SUMMARY_FILE).read_text(encoding="utf-8")))


def digest_new_shards(shards: Path, digests: Path, config: DigestConfig) -> list[DigestSummary]:
    """Digests every closed shard not digested yet; returns their summaries in shard order."""
    done = {digest.name for digest in digested(digests)}
    return [
        write_digest(digests, shard, digest_shard(shard, config))
        for shard in closed_shards(shards)
        if shard.name not in done
    ]


def read_pairs_file(path: Path) -> Iterator[VersionedPair]:
    with path.open(encoding="utf-8") as lines:
        yield from (from_json_object(VersionedPair, json.loads(line)) for line in lines)


def read_policy(digest: Path) -> Iterator[VersionedPair]:
    return read_pairs_file(digest / POLICY_FILE)


def read_jumps(digest: Path) -> Iterator[VersionedPair]:
    return read_pairs_file(digest / JUMPS_FILE)


def read_contexts(digest: Path) -> Iterator[ThinkingContext]:
    with (digest / CONTEXTS_FILE).open(encoding="utf-8") as lines:
        yield from (from_json_object(ThinkingContext, json.loads(line)) for line in lines)


def write_policy(digest: Path, pairs: Sequence[VersionedPair]) -> None:
    """Replaces a digest's policy pairs (e.g. with shortened reasoning), atomically."""
    temporary = digest / (POLICY_FILE + ".tmp")
    write_lines(temporary, pairs)
    os.replace(temporary, digest / POLICY_FILE)


def read_values(digest: Path) -> Iterator[VersionedValueExample]:
    with (digest / VALUES_FILE).open(encoding="utf-8") as lines:
        yield from (from_json_object(VersionedValueExample, json.loads(line)) for line in lines)


def all_values(digests: Path) -> Iterator[VersionedValueExample]:
    for digest in digested(digests):
        yield from read_values(digest)
