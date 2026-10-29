"""GRPO groups at proof-graph nodes: each policy sample's tactics with their rewards R = (1 − λ) · G + λ · L."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lean_search.search.graph_labels import EdgeKind, EdgeLabel, GraphLabels, NodeClass
from lean_search.search.records import TreeRecord
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome
from lean_search.search.tree import StepSource
from lean_search.value.graph_targets import ValueEstimate, value_part


@dataclass(frozen=True)
class RewardConfig:
    # λ: the local term's share of every tactic's reward.
    local_share: float = 0.15
    # L of the first failing tactic (errors and timeouts) and of a sample without a usable block.
    failure_local: float = -1.0
    # L of a tactic without progress or adding only redundant hypotheses: a wasted sample, like a failure.
    no_progress_local: float = -1.0
    # L per goal a tactic on the proof graph closes.
    goal_closed_bonus: float = 0.1
    # μ: an expanded off-graph state earns G = μ · q, q its value part; 0 until a value model passed the gate.
    value_share: float = 0.0
    # An off-graph state with live children and fewer expanded nodes in its subtree (itself included) is unknown.
    off_graph_min_expanded_nodes: int = 4
    # Only groups with a policy sample reaching the proof graph; the automation sweep's children do not count.
    require_policy_proof: bool = True


@dataclass(frozen=True)
class RewardParts:
    # (1 − λ) · G and λ · L.
    global_part: float
    local_part: float

    @property
    def total(self) -> float:
        return self.global_part + self.local_part


@dataclass(frozen=True)
class TacticReward:
    label: TacticLabel
    # None for unknown and masked tactics, which earn nothing and stay out of the score.
    parts: RewardParts | None


@dataclass(frozen=True)
class GroupSample:
    text: str
    # Identical texts of the expansion merged into one sample: their edges and the policy samples behind them.
    edge_ids: tuple[int, ...]
    multiplicity: int
    kind: EdgeKind
    tactics: tuple[TacticReward, ...]

    @property
    def known(self) -> list[RewardParts]:
        return [tactic.parts for tactic in self.tactics if tactic.parts is not None]

    @property
    def score(self) -> float | None:
        """The mean reward of the tactics with a known reward."""
        known = self.known
        return sum(parts.total for parts in known) / len(known) if known else None

    @property
    def complete(self) -> bool:
        return all(tactic.label not in (TacticLabel.FAILING, TacticLabel.MASKED) for tactic in self.tactics)


@dataclass(frozen=True)
class PolicyGroup:
    problem_name: str
    node_id: int
    goals: tuple[str, ...]
    samples: tuple[GroupSample, ...]

    @property
    def sample_count(self) -> int:
        return sum(sample.multiplicity for sample in self.samples)

    @property
    def has_policy_proof(self) -> bool:
        return any(tactic.label == TacticLabel.PROOF_GRAPH for sample in self.samples for tactic in sample.tactics)


@dataclass(frozen=True)
class TreeGroups:
    groups: tuple[PolicyGroup, ...]
    # Groups left out by `require_policy_proof`.
    without_policy_proof: int


def off_graph_value(
    node_id: int | None, labels: GraphLabels, estimates: Sequence[ValueEstimate | None], config: RewardConfig
) -> float:
    """G = μ · q of an expanded off-graph state: q averages its expanded descendants, else its own estimate."""
    if node_id is None or not config.value_share:
        return 0.0
    estimate = value_part(node_id, labels.expanded_descendants.get(node_id, ()), estimates, None)
    return 0.0 if estimate is None else config.value_share * estimate.proof_probability


def reward_parts(global_value: float, local_value: float, config: RewardConfig) -> RewardParts:
    local = min(1.0, max(-1.0, local_value))
    return RewardParts((1 - config.local_share) * global_value, config.local_share * local)


def tactic_reward(outcome: TacticOutcome, config: RewardConfig, off_graph_global: float = 0.0) -> TacticReward:
    """`off_graph_global`: G of an off-graph tactic's state (`off_graph_value`)."""
    match outcome.label:
        case TacticLabel.PROOF_GRAPH:
            parts = reward_parts(1.0, config.goal_closed_bonus * outcome.goals_closed, config)
        case TacticLabel.OFF_GRAPH:
            parts = reward_parts(off_graph_global, 0.0, config)
        case TacticLabel.NO_PROGRESS | TacticLabel.REDUNDANT_HYPOTHESIS:
            parts = reward_parts(0.0, config.no_progress_local, config)
        case TacticLabel.FAILING:
            parts = reward_parts(0.0, config.failure_local, config)
        case TacticLabel.UNKNOWN | TacticLabel.MASKED:
            parts = None
    return TacticReward(outcome.label, parts)


def group_sample(
    edges: Sequence[EdgeLabel],
    outcomes: Sequence[TacticOutcome],
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    config: RewardConfig,
) -> GroupSample:
    return GroupSample(
        text=edges[0].text.strip(),
        edge_ids=tuple(edge.edge_id for edge in edges),
        multiplicity=sum(edge.sample_count for edge in edges),
        kind=edges[0].effective_kind,
        tactics=tuple(
            tactic_reward(
                outcome,
                config,
                off_graph_value(outcome.node_id, labels, estimates, config)
                if outcome.label == TacticLabel.OFF_GRAPH
                else 0.0,
            )
            for outcome in outcomes
        ),
    )


def policy_groups(
    record: TreeRecord,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
    estimates: Sequence[ValueEstimate | None],
    config: RewardConfig,
) -> TreeGroups:
    """One group per expanded proof-graph node with policy samples; `tactics` from `policy_tactics`."""
    groups = []
    for node_id, edges in sorted(labels.edges_by_parent().items()):
        if labels.node_classes[node_id] != NodeClass.PROOF_GRAPH:
            continue
        by_text: dict[str, list[EdgeLabel]] = {}
        for edge in edges:
            if edge.source == StepSource.POLICY and edge.effective_kind != EdgeKind.INFRASTRUCTURE_FAILURE:
                by_text.setdefault(edge.text.strip(), []).append(edge)
        if not by_text:
            continue
        samples = tuple(
            group_sample(members, tactics[members[0].executed_edge_id], labels, estimates, config)
            for members in by_text.values()
        )
        groups.append(PolicyGroup(record.problem_name, node_id, record.nodes[node_id].goals, samples))
    kept = tuple(group for group in groups if group.has_policy_proof or not config.require_policy_proof)
    return TreeGroups(kept, len(groups) - len(kept))
