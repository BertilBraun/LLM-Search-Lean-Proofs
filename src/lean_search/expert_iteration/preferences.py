"""DPO pairs from search trees.

At each policy step of a found proof, the on-path step is chosen against sibling candidates, by priority: siblings
that led into a dead subtree (at most `max_dead_per_node`), then siblings Lean rejected or that timed out (at most
`max_failed_per_node`; they mostly teach syntax), the policy's most likely mistakes first. Value-jump pairs set a
child the value model puts near a proof against an alive sibling it puts much further away, at any expanded node;
they are only as good as the value model and are used while it passes a quality gate.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.proofs import EXPERT_ITERATION_SOURCE, FoundProof
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search import Edge, EdgeOutcome, FailureKind, NodeRecord, NodeStatus, StepSource, TreeRecord
from lean_search.training.dpo_data import PreferencePair
from lean_search.value.labels import distances_to, frontier_ids, predecessors

TIMEOUT_FAILURES = frozenset({FailureKind.HEARTBEAT_TIMEOUT, FailureKind.WALL_CLOCK_TIMEOUT})


class RejectionKind(StrEnum):
    # The block led to a state whose whole subtree was expanded without a proof.
    DEAD = "dead"
    # Lean rejected the block's first tactic (or the search refused it).
    ERROR = "error"
    TIMEOUT = "timeout"
    # An alive sibling the value model puts much further from a proof than the chosen child.
    VALUE_JUMP = "value_jump"


@dataclass(frozen=True)
class ValueJumpConfig:
    enabled: bool = True
    # The chosen child: on a proof path, or within this many steps of done by the value model's h.
    chosen_max_value: float = 1.5
    # The rejected sibling's h is at least the chosen one's plus this.
    margin: float = 3.0
    max_per_node: int = 2
    # Used only while the value model ranks held-out fresh trees well: Spearman of h with the exact remaining
    # steps, and h separating dead from exact states, over at least `gate_minimum_states` exact states.
    gate_spearman: float = 0.7
    gate_dead_auc: float = 0.75
    gate_minimum_states: int = 50


@dataclass(frozen=True)
class NodePairs:
    step_index: int
    chosen_source: StepSource
    pairs: tuple[PreferencePair, ...]
    # Rejectable siblings before the per-node caps.
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


def capped_by_kind(
    rejectable: Sequence[tuple[Edge, RejectionKind, str]], config: PreferenceConfig
) -> list[tuple[Edge, RejectionKind, str]]:
    """Dead-subtree siblings first, then failed ones, each up to its cap, in the given order within a kind."""
    dead = [entry for entry in rejectable if entry[1] == RejectionKind.DEAD][: config.max_dead_per_node]
    failed = [entry for entry in rejectable if entry[1] != RejectionKind.DEAD][: config.max_failed_per_node]
    return dead + failed


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
        kept = capped_by_kind(rejectable, config)
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


def step_text(node: NodeRecord) -> str:
    assert node.step is not None, node.node_id
    return normalize_tactic_block(node.step)


def chosen_value(node: NodeRecord) -> float | None:
    """The h a chosen child counts with: a proof-path child counts as done when it was never scored."""
    if node.status == NodeStatus.PROVED:
        return node.value_estimate if node.value_estimate is not None else 0.0
    return node.value_estimate


def value_jump_pairs(record: TreeRecord, run: str, config: ValueJumpConfig) -> list[PreferencePair]:
    dead = dead_node_ids(record)
    pairs = []
    for parent in record.nodes:
        children = [record.nodes[child_id] for child_id in parent.child_ids]
        policy_children = [child for child in children if child.source == StepSource.POLICY and child.step]
        for chosen in policy_children:
            chosen_h = chosen_value(chosen)
            if chosen_h is None or (chosen.status != NodeStatus.PROVED and chosen_h > config.chosen_max_value):
                continue
            rejected = sorted(
                (
                    sibling
                    for sibling in policy_children
                    if sibling is not chosen
                    and sibling.goals
                    and sibling.node_id not in dead
                    and sibling.status != NodeStatus.PROVED
                    and sibling.value_estimate is not None
                    and sibling.value_estimate >= chosen_h + config.margin
                ),
                key=lambda sibling: (-(sibling.value_estimate or 0.0), sibling.node_id),
            )[: config.max_per_node]
            pairs.extend(
                PreferencePair(
                    EXPERT_ITERATION_SOURCE,
                    f"{run}/{record.problem_name}",
                    parent.depth,
                    parent.goals,
                    step_text(chosen),
                    step_text(sibling),
                    RejectionKind.VALUE_JUMP,
                )
                for sibling in rejected
            )
    return pairs
