"""Sibling ranking pairs for the value model: only among the distinct states one expanded node reached."""

from dataclasses import dataclass
from enum import StrEnum

from lean_search.search.graph_labels import GraphLabels, NodeClass
from lean_search.value.graph_targets import size_weight


class PairKind(StrEnum):
    PROOF_OVER_DEAD_END = "proof_over_dead_end"
    PROOF_OVER_EXPANDED = "proof_over_expanded"
    PROOF_OVER_NEVER_EXPANDED = "proof_over_never_expanded"
    EXPANDED_OVER_DEAD_END = "expanded_over_dead_end"


@dataclass(frozen=True)
class RankingConfig:
    proof_over_dead_end_weight: float = 1.0
    # Scaled by the expanded sibling's subtree size, see `half_weight_expanded_nodes`.
    proof_over_expanded_weight: float = 0.5
    proof_over_never_expanded_weight: float = 0.0
    expanded_over_dead_end_weight: float = 0.5
    # A subtree of this many expanded nodes (the node itself included) has half the full weight.
    half_weight_expanded_nodes: float = 4.0
    # "Large subtree" for an expanded sibling ranked above a dead end.
    minimum_expanded_nodes: int = 4
    # The design names expanded-over-dead-end pairs for unsolved trees only.
    expanded_over_dead_end_in_solved_trees: bool = False


@dataclass(frozen=True)
class SiblingPair:
    parent_id: int
    preferred_id: int
    other_id: int
    kind: PairKind
    weight: float


def expanded_nodes(labels: GraphLabels, node_id: int) -> int:
    return 1 + len(labels.expanded_descendants.get(node_id, ()))


def sibling_pairs(labels: GraphLabels, config: RankingConfig) -> list[SiblingPair]:
    pairs = []
    solved = labels.solved
    for parent_id, successors in labels.successors.items():
        by_class: dict[NodeClass, list[int]] = {}
        for node_id in successors:
            by_class.setdefault(labels.node_classes[node_id], []).append(node_id)
        proofs = by_class.get(NodeClass.PROOF_GRAPH, [])
        dead_ends = by_class.get(NodeClass.DEAD_END, [])
        expanded = by_class.get(NodeClass.EXPANDED_OFF_GRAPH, [])
        never_expanded = by_class.get(NodeClass.NEVER_EXPANDED, [])
        for proof_id in proofs:
            pairs.extend(
                SiblingPair(
                    parent_id, proof_id, dead_id, PairKind.PROOF_OVER_DEAD_END, config.proof_over_dead_end_weight
                )
                for dead_id in dead_ends
            )
            pairs.extend(
                SiblingPair(
                    parent_id,
                    proof_id,
                    expanded_id,
                    PairKind.PROOF_OVER_EXPANDED,
                    config.proof_over_expanded_weight
                    * size_weight(expanded_nodes(labels, expanded_id), config.half_weight_expanded_nodes),
                )
                for expanded_id in expanded
            )
            pairs.extend(
                SiblingPair(
                    parent_id,
                    proof_id,
                    never_id,
                    PairKind.PROOF_OVER_NEVER_EXPANDED,
                    config.proof_over_never_expanded_weight,
                )
                for never_id in never_expanded
            )
        if solved and not config.expanded_over_dead_end_in_solved_trees:
            continue
        for expanded_id in expanded:
            size = expanded_nodes(labels, expanded_id)
            if size < config.minimum_expanded_nodes:
                continue
            pairs.extend(
                SiblingPair(
                    parent_id,
                    expanded_id,
                    dead_id,
                    PairKind.EXPANDED_OVER_DEAD_END,
                    config.expanded_over_dead_end_weight * size_weight(size, config.half_weight_expanded_nodes),
                )
                for dead_id in dead_ends
            )
    return [pair for pair in pairs if pair.weight > 0]
