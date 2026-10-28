"""Value targets from labelled search graphs: y = (1 − μ) · z + μ · q, a concrete label z mixed with a value part q."""

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from lean_search.search.graph_labels import GraphLabels, NodeClass, ReachedNode
from lean_search.search.records import TreeRecord
from lean_search.search.tree import NodeStatus
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, STEP_BIN_COUNT, Readout


@dataclass(frozen=True)
class ValueEstimate:
    proof_probability: float
    remaining_steps: float


@dataclass(frozen=True)
class RemainingStepsReadout:
    """Reads a proof probability from the scalar h a tree records, linear between a sure one-step proof and dead."""

    dead_steps: float = Readout().dead_steps
    fewest_steps: float = 1.0

    def estimate(self, remaining_steps: float) -> ValueEstimate:
        share = (self.dead_steps - remaining_steps) / (self.dead_steps - self.fewest_steps)
        return ValueEstimate(min(1.0, max(0.0, share)), remaining_steps)


def bin_estimate(probabilities: Sequence[float], readout: Readout) -> ValueEstimate:
    """The value model's bins 1..7, 8+, dead: proof probability 1 - p_dead, steps given alive."""
    return ValueEstimate(1.0 - probabilities[DEAD_BIN], readout.alive_remaining_steps(probabilities))


def recorded_estimates(record: TreeRecord, readout: RemainingStepsReadout) -> tuple[ValueEstimate | None, ...]:
    """The search-time estimates per node; a verified proof is exact, a node never scored has none."""
    estimates: list[ValueEstimate | None] = []
    for node in record.nodes:
        if not node.goals:
            estimates.append(ValueEstimate(1.0, 0.0) if node.status == NodeStatus.PROVED else None)
        elif node.value_estimate is None:
            estimates.append(None)
        else:
            estimates.append(readout.estimate(node.value_estimate))
    return tuple(estimates)


class TargetSource(StrEnum):
    PROOF_GRAPH = "proof_graph"
    # Expanded, no route to a proof in this tree: "no proof within this budget", in solved and unsolved trees.
    OFF_GRAPH = "off_graph"


@dataclass(frozen=True)
class ValueTargetConfig:
    # μ: the value part's share of every target; 0 trains on the concrete labels alone (before a value model passed
    # the gate).
    value_share: float = 0.15
    proof_graph_weight: float = 1.0
    off_graph_weight: float = 0.5
    # An off-graph target has half its weight at this many expanded nodes (itself and its expanded descendants).
    half_weight_expanded_nodes: float = 4.0
    # None: q is the plain average; smaller values slide it toward the best descendant.
    temperature: float | None = None
    # 0: no cap.
    max_targets_per_tree: int = 0


@dataclass(frozen=True)
class ValueTarget:
    problem_name: str
    node_id: int
    goals: tuple[str, ...]
    # The concrete label z: 1 with exact remaining steps on the proof graph, 0 off it.
    source: TargetSource
    exact_steps: int | None
    # q: the average over the expanded descendants, else the node's own estimate; None when neither has one.
    value_part: ValueEstimate | None
    value_share: float
    weight: float
    expanded_descendants: int

    @property
    def concrete_proof_probability(self) -> float:
        return 1.0 if self.source == TargetSource.PROOF_GRAPH else 0.0

    @property
    def proof_probability(self) -> float:
        concrete = self.concrete_proof_probability
        if self.value_part is None:
            return concrete
        return (1 - self.value_share) * concrete + self.value_share * self.value_part.proof_probability


def size_weight(count: int, half_weight_count: float) -> float:
    return count / (count + half_weight_count)


def value_part(
    node_id: int,
    descendants: Sequence[ReachedNode],
    estimates: Sequence[ValueEstimate | None],
    temperature: float | None,
) -> ValueEstimate | None:
    """The mean proof probability and mean distance + h over the expanded descendants with an estimate."""
    values = [
        (descendant.distance, estimate)
        for descendant in descendants
        if (estimate := estimates[descendant.node_id]) is not None
    ]
    if not values:
        return estimates[node_id]
    if temperature is None:
        weights = [1.0] * len(values)
    else:
        best = max(estimate.proof_probability for _, estimate in values)
        weights = [math.exp((estimate.proof_probability - best) / temperature) for _, estimate in values]
    total = sum(weights)
    proof_probability = sum(
        weight * estimate.proof_probability for weight, (_, estimate) in zip(weights, values, strict=True)
    )
    steps = sum(
        weight * (distance + estimate.remaining_steps)
        for weight, (distance, estimate) in zip(weights, values, strict=True)
    )
    return ValueEstimate(proof_probability / total, steps / total)


def value_targets(
    record: TreeRecord,
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    config: ValueTargetConfig,
) -> list[ValueTarget]:
    """One target per expanded state with goals; dead ends are ordinary off-graph states, never-expanded get none."""
    targets = []
    for node in record.nodes:
        descendants = labels.expanded_descendants.get(node.node_id, ())
        match labels.node_classes[node.node_id]:
            case NodeClass.PROOF_GRAPH if node.goals:
                source = TargetSource.PROOF_GRAPH
                exact_steps = labels.remaining_steps[node.node_id]
                weight = config.proof_graph_weight
            case NodeClass.EXPANDED_OFF_GRAPH | NodeClass.DEAD_END:
                source = TargetSource.OFF_GRAPH
                exact_steps = None
                weight = config.off_graph_weight * size_weight(1 + len(descendants), config.half_weight_expanded_nodes)
            case NodeClass.PROOF_GRAPH | NodeClass.NEVER_EXPANDED | NodeClass.UNVERIFIED_PROOF:
                continue
        targets.append(
            ValueTarget(
                problem_name=record.problem_name,
                node_id=node.node_id,
                goals=node.goals,
                source=source,
                exact_steps=exact_steps,
                value_part=value_part(node.node_id, descendants, estimates, config.temperature),
                value_share=config.value_share,
                weight=weight,
                expanded_descendants=len(descendants),
            )
        )
    return capped_targets(targets, config.max_targets_per_tree)


def stable_order(target: ValueTarget) -> str:
    return hashlib.sha256(f"{target.problem_name}/{target.node_id}".encode()).hexdigest()


def capped_targets(targets: Sequence[ValueTarget], max_targets: int) -> list[ValueTarget]:
    """At most `max_targets` (0: all): every proof-graph target first, then the others in a fixed hashed order."""
    if not max_targets or len(targets) <= max_targets:
        return list(targets)
    anchors = [target for target in targets if target.source == TargetSource.PROOF_GRAPH]
    others = sorted((target for target in targets if target.source != TargetSource.PROOF_GRAPH), key=stable_order)
    kept = {target.node_id for target in (anchors + others)[:max_targets]}
    return [target for target in targets if target.node_id in kept]


@dataclass(frozen=True)
class SourceShares:
    proof_graph: float = 0.4
    off_graph: float = 0.6

    def share(self, source: TargetSource) -> float:
        match source:
            case TargetSource.PROOF_GRAPH:
                return self.proof_graph
            case TargetSource.OFF_GRAPH:
                return self.off_graph


def balanced_weights(targets: Sequence[ValueTarget], shares: SourceShares) -> list[ValueTarget]:
    """Rescales weights so each source present holds its share of the total weight; relative weights within stay."""
    totals = {source: 0.0 for source in TargetSource}
    for target in targets:
        totals[target.source] += target.weight
    present = [source for source, total in totals.items() if total > 0]
    share_sum = sum(shares.share(source) for source in present)
    grand_total = sum(totals.values())
    scales = {
        source: shares.share(source) / share_sum * grand_total / totals[source] if source in present else 0.0
        for source in TargetSource
    }
    return [replace(target, weight=target.weight * scales[target.source]) for target in targets]


def step_bin_masses(steps: float, sigma: float) -> list[float]:
    """The mass of N(steps, sigma^2) on the step bins 1..7, 8+ (the first and last bin are open-ended)."""
    if sigma == 0:
        masses = [0.0] * STEP_BIN_COUNT
        masses[min(max(round(steps), 1), STEP_BIN_COUNT) - 1] = 1.0
        return masses
    cumulative = [0.0]
    for edge in range(1, STEP_BIN_COUNT):
        cumulative.append(0.5 * (1 + math.erf((edge + 0.5 - steps) / (sigma * math.sqrt(2)))))
    cumulative.append(1.0)
    return [upper - lower for lower, upper in zip(cumulative, cumulative[1:], strict=False)]


def mixed(first: Sequence[float], second: Sequence[float], second_share: float) -> tuple[float, ...]:
    return tuple((1 - second_share) * left + second_share * right for left, right in zip(first, second, strict=True))


def dead_bins() -> tuple[float, ...]:
    return tuple(float(index == DEAD_BIN) for index in range(BIN_COUNT))


def step_bins(steps: float, sigma: float) -> tuple[float, ...]:
    return (*step_bin_masses(steps, sigma), 0.0)


def estimate_bins(estimate: ValueEstimate, sigma: float) -> tuple[float, ...]:
    """The proof probability spread over the step bins around the estimate's steps, the rest dead."""
    return mixed(dead_bins(), step_bins(estimate.remaining_steps, sigma), estimate.proof_probability)


def concrete_bins(target: ValueTarget, sigma: float) -> tuple[float, ...]:
    return dead_bins() if target.exact_steps is None else step_bins(float(target.exact_steps), sigma)


def bin_target(target: ValueTarget, sigma: float) -> tuple[float, ...]:
    """(1 − μ) · z's bins + μ · q's bins, so 1 − p_dead is the mixed proof probability y."""
    if target.value_part is None:
        return concrete_bins(target, sigma)
    return mixed(concrete_bins(target, sigma), estimate_bins(target.value_part, sigma), target.value_share)
