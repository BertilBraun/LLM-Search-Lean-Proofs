"""Sibling ranking pairs for the value model: only among the distinct states one expanded node reached."""

from dataclasses import dataclass
from enum import StrEnum

from lean_search.search.graph_labels import GraphLabels, NodeClass
from lean_search.value.graph_targets import size_weight


class PairKind(StrEnum):
    PROOF_OVER_EXPANDED = "proof_over_expanded"
    PROOF_OVER_NEVER_EXPANDED = "proof_over_never_expanded"


@dataclass(frozen=True)
class RankingConfig:
    # Scaled by the expanded sibling's subtree size, see `half_weight_expanded_nodes`.
    proof_over_expanded_weight: float = 0.5
    # Never-expanded siblings may be provable too.
    proof_over_never_expanded_weight: float = 0.0
    # A subtree of this many expanded nodes (the node itself included) has half the full weight.
    half_weight_expanded_nodes: float = 4.0


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
    """Each proof-graph child over its off-graph siblings; unsolved trees and two off-graph siblings give none."""
    pairs = []
    for parent_id, successors in labels.successors.items():
        proofs: list[int] = []
        expanded: list[int] = []
        never_expanded: list[int] = []
        for node_id in successors:
            match labels.node_classes[node_id]:
                case NodeClass.PROOF_GRAPH:
                    proofs.append(node_id)
                case NodeClass.EXPANDED_OFF_GRAPH | NodeClass.DEAD_END:
                    expanded.append(node_id)
                case NodeClass.NEVER_EXPANDED:
                    never_expanded.append(node_id)
                case NodeClass.UNVERIFIED_PROOF:
                    pass
        for proof_id in proofs:
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
    return [pair for pair in pairs if pair.weight > 0]
