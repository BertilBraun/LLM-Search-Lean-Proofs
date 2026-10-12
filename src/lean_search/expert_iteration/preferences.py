"""DPO pairs from search trees: at each node of a found proof, the on-path step against failed sibling candidates."""

import math
from dataclasses import dataclass
from enum import StrEnum

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.proofs import EXPERT_ITERATION_SOURCE, FoundProof
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search import Edge, EdgeOutcome, FailureKind, NodeStatus, StepSource, TreeRecord
from lean_search.training.dpo_data import PreferencePair
from lean_search.value.labels import distances_to, frontier_ids, predecessors

TIMEOUT_FAILURES = frozenset({FailureKind.HEARTBEAT_TIMEOUT, FailureKind.WALL_CLOCK_TIMEOUT})


class RejectionKind(StrEnum):
    # Lean rejected the block's first tactic (or the search refused it).
    ERROR = "error"
    TIMEOUT = "timeout"
    # The block led to a state whose whole subtree was expanded without a proof.
    DEAD = "dead"


@dataclass(frozen=True)
class NodePairs:
    step_index: int
    chosen_source: StepSource
    pairs: tuple[PreferencePair, ...]
    # Rejectable siblings before the per-node cap.
    rejectable: int
    # Rejected candidates the policy itself ranked above the chosen step.
    rejected_more_likely: int


def dead_node_ids(record: TreeRecord) -> frozenset[int]:
    """States the value labels call dead: fully expanded below, reaching neither a proof nor the frontier."""
    by_target = predecessors(record)
    proof_ids = [node.node_id for node in record.nodes if node.status == NodeStatus.PROVED and not node.goals]
    alive = distances_to(proof_ids, by_target).keys() | distances_to(frontier_ids(record), by_target).keys()
    return frozenset(node.node_id for node in record.nodes if node.goals and node.node_id not in alive)


def rejection_kind(edge: Edge, dead: frozenset[int], dead_subtrees: bool) -> RejectionKind | None:
    match edge.outcome:
        case EdgeOutcome.FAILED | EdgeOutcome.REJECTED if edge.failure is not None and edge.failure.is_negative_label:
            return RejectionKind.TIMEOUT if edge.failure.kind in TIMEOUT_FAILURES else RejectionKind.ERROR
        case EdgeOutcome.CHILD | EdgeOutcome.DUPLICATE if dead_subtrees and edge.target_id in dead:
            return RejectionKind.DEAD
        case _:
            return None


def likelihood_order(edge: Edge) -> tuple[float, int]:
    """Most likely first: the policy's most confident mistakes are the most informative rejections."""
    log_probability = -math.inf if edge.log_probability is None else edge.log_probability
    return -log_probability, edge.edge_id


def node_pairs(record: TreeRecord, proof: FoundProof, config: PreferenceConfig) -> list[NodePairs]:
    dead = dead_node_ids(record)
    edges_by_parent: dict[int, list[Edge]] = {}
    for edge in record.edges:
        edges_by_parent.setdefault(edge.parent_id, []).append(edge)
    results = []
    for step_index, step in enumerate(proof.steps):
        if config.policy_steps_only and step.source != StepSource.POLICY:
            continue
        chosen_edge_id = record.nodes[step.child_id].edge_id
        chosen = normalize_tactic_block(step.step)
        seen = {chosen}
        rejectable: list[tuple[Edge, RejectionKind, str]] = []
        for edge in sorted(edges_by_parent.get(step.node_id, ()), key=likelihood_order):
            if edge.edge_id == chosen_edge_id or (config.policy_steps_only and edge.source != StepSource.POLICY):
                continue
            kind = rejection_kind(edge, dead, config.dead_subtrees)
            text = normalize_tactic_block(edge.text)
            if kind is None or text in seen:
                continue
            seen.add(text)
            rejectable.append((edge, kind, text))
        kept = rejectable[: config.max_pairs_per_node]
        pairs = tuple(
            PreferencePair(EXPERT_ITERATION_SOURCE, proof.identifier, step_index, step.goals, chosen, text, kind)
            for _, kind, text in kept
        )
        more_likely = sum(
            step.log_probability is not None
            and edge.log_probability is not None
            and edge.log_probability > step.log_probability
            for edge, _, _ in kept
        )
        results.append(NodePairs(step_index, step.source, pairs, len(rejectable), more_likely))
    return results
