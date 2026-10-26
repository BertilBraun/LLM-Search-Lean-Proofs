"""GRPO groups from labelled search graphs: the policy samples of one expanded node with their reward components."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from lean_search.search.graph_labels import EdgeKind, EdgeLabel, GraphLabels, NodeClass
from lean_search.search.records import TreeRecord
from lean_search.search.tree import FailureKind, NodeStatus, StepSource
from lean_search.value.graph_targets import TargetSource, ValueEstimate, ValueTarget


class RewardMode(StrEnum):
    # r_local + beta * G.
    DENSE = "dense"
    # The control run: only G from the proof graph (1 on it, 0 elsewhere).
    OUTCOME_ONLY = "outcome_only"


@dataclass(frozen=True)
class RewardConfig:
    mode: RewardMode = RewardMode.DENSE
    # beta: large enough that the global term dominates whenever it is known.
    global_weight: float = 4.0
    lean_error_reward: float = -1.0
    # A sample without a usable block, e.g. a repetition loop cut off at the token cap.
    unparsed_sample_reward: float = -1.0
    heartbeat_timeout_reward: float = -1.0
    wall_clock_timeout_reward: float = -1.0
    no_progress_reward: float = 0.0
    already_seen_reward: float = 0.0
    # Times h(parent) - h(state reached).
    shaping_weight: float = 0.1
    # Per goal fewer than the parent's.
    goal_closed_bonus: float = 0.1
    # G on the proof graph is 1 + shorter_proof_bonus / (1 + remaining steps of the state reached).
    shorter_proof_bonus: float = 0.0
    # Expanded off-graph states get their averaged value as G once a value model passed the gate; 0 before.
    use_backed_up_values: bool = False


@dataclass(frozen=True)
class RewardComponents:
    failure: float
    no_progress: float
    already_seen: float
    shaping: float
    goals_closed: float
    # G, before the factor beta.
    global_value: float

    @property
    def local(self) -> float:
        return self.failure + self.no_progress + self.already_seen + self.shaping + self.goals_closed


@dataclass(frozen=True)
class TokenCredit:
    """Inputs for per-token advantages: tactics before `first_failing_tactic` reach `prefix_state_id`."""

    applied_tactics: int
    total_tactics: int
    # The index of the first failing top-level tactic; None when the block ran completely.
    first_failing_tactic: int | None
    prefix_state_id: int | None
    # The reward of the valid prefix as if the sample had ended there; None without a prefix.
    prefix_reward: float | None
    # The components behind `prefix_reward`.
    prefix_components: RewardComponents | None = None


@dataclass(frozen=True)
class GroupSample:
    text: str
    # Identical texts of the expansion merged into one sample: their edges and the policy samples behind them.
    edge_ids: tuple[int, ...]
    multiplicity: int
    kind: EdgeKind
    target_id: int | None
    components: RewardComponents
    reward: float
    credit: TokenCredit


@dataclass(frozen=True)
class PolicyGroup:
    problem_name: str
    node_id: int
    goals: tuple[str, ...]
    node_class: NodeClass
    # False when the expansion was cut off by the budget or stopped at a proof.
    complete: bool
    samples: tuple[GroupSample, ...]

    @property
    def sample_count(self) -> int:
        return sum(sample.multiplicity for sample in self.samples)

    @property
    def mean_reward(self) -> float:
        return sum(sample.reward * sample.multiplicity for sample in self.samples) / self.sample_count

    @property
    def has_mixed_rewards(self) -> bool:
        return len({sample.reward for sample in self.samples}) > 1


def global_value(target_id: int, labels: GraphLabels, backed_up: Mapping[int, float], config: RewardConfig) -> float:
    match labels.node_classes[target_id]:
        case NodeClass.PROOF_GRAPH:
            if config.mode == RewardMode.OUTCOME_ONLY:
                return 1.0
            steps = labels.remaining_steps[target_id]
            assert steps is not None
            return 1.0 + config.shorter_proof_bonus / (1 + steps)
        case NodeClass.EXPANDED_OFF_GRAPH if config.use_backed_up_values and config.mode == RewardMode.DENSE:
            return backed_up.get(target_id, 0.0)
        case _:
            return 0.0


def failure_reward(edge: EdgeLabel, config: RewardConfig) -> float:
    if edge.effective_kind == EdgeKind.UNVERIFIED_PROOF:
        return config.lean_error_reward
    match edge.failure_kind:
        case None:
            return 0.0
        case FailureKind.HEARTBEAT_TIMEOUT:
            return config.heartbeat_timeout_reward
        case FailureKind.WALL_CLOCK_TIMEOUT:
            return config.wall_clock_timeout_reward
        case FailureKind.UNPARSED:
            return config.unparsed_sample_reward
        case FailureKind.ERROR | FailureKind.FORBIDDEN | FailureKind.UNKNOWN_IDENTIFIER | FailureKind.REPL_FAILURE:
            return config.lean_error_reward


def shaping(parent_id: int, target_id: int, estimates: Sequence[ValueEstimate | None], config: RewardConfig) -> float:
    parent = estimates[parent_id]
    target = estimates[target_id]
    if parent is None or target is None:
        return 0.0
    return config.shaping_weight * (parent.remaining_steps - target.remaining_steps)


def sample_components(
    edge: EdgeLabel,
    record: TreeRecord,
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    backed_up: Mapping[int, float],
    config: RewardConfig,
) -> tuple[RewardComponents, RewardComponents | None]:
    """The sample's components and those of its valid prefix alone (None when no state was reached)."""
    if config.mode == RewardMode.OUTCOME_ONLY:
        if edge.target_id is None or edge.effective_kind == EdgeKind.UNVERIFIED_PROOF:
            return RewardComponents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), None
        reached = 0.0 if edge.effective_kind.is_no_progress else global_value(edge.target_id, labels, backed_up, config)
        prefix = RewardComponents(0.0, 0.0, 0.0, 0.0, 0.0, reached)
        return RewardComponents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0 if edge.failure_kind is not None else reached), prefix
    failure = failure_reward(edge, config)
    if edge.target_id is None or edge.effective_kind == EdgeKind.UNVERIFIED_PROOF:
        return RewardComponents(failure, 0.0, 0.0, 0.0, 0.0, 0.0), None
    no_progress = edge.effective_kind.is_no_progress
    parent_goals = len(record.nodes[edge.parent_id].goals)
    target_goals = len(record.nodes[edge.target_id].goals)
    prefix = RewardComponents(
        failure=0.0,
        no_progress=config.no_progress_reward if no_progress else 0.0,
        already_seen=config.already_seen_reward
        if edge.effective_kind in (EdgeKind.SIBLING_STATE, EdgeKind.TRANSPOSITION)
        else 0.0,
        shaping=shaping(edge.parent_id, edge.target_id, estimates, config),
        goals_closed=0.0 if no_progress else config.goal_closed_bonus * max(0, parent_goals - target_goals),
        global_value=0.0 if no_progress else global_value(edge.target_id, labels, backed_up, config),
    )
    return replace(prefix, failure=failure), prefix


def total_reward(components: RewardComponents, config: RewardConfig) -> float:
    if config.mode == RewardMode.OUTCOME_ONLY:
        return components.global_value
    return components.local + config.global_weight * components.global_value


def group_sample(
    edges: Sequence[EdgeLabel],
    record: TreeRecord,
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    backed_up: Mapping[int, float],
    config: RewardConfig,
) -> GroupSample:
    edge = edges[0]
    components, prefix = sample_components(edge, record, labels, estimates, backed_up, config)
    return GroupSample(
        text=edge.text.strip(),
        edge_ids=tuple(member.edge_id for member in edges),
        multiplicity=sum(member.sample_count for member in edges),
        kind=edge.effective_kind,
        target_id=edge.target_id,
        components=components,
        reward=total_reward(components, config),
        credit=TokenCredit(
            applied_tactics=edge.applied_tactics,
            total_tactics=edge.total_tactics,
            first_failing_tactic=None if edge.failure_kind is None else edge.applied_tactics,
            prefix_state_id=edge.target_id,
            prefix_reward=None if prefix is None else total_reward(prefix, config),
            prefix_components=prefix,
        ),
    )


def backed_up_values(targets: Sequence[ValueTarget]) -> dict[int, float]:
    return {target.node_id: target.proof_probability for target in targets if target.source == TargetSource.AVERAGED}


def policy_groups(
    record: TreeRecord,
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    targets: Sequence[ValueTarget],
    config: RewardConfig,
) -> list[PolicyGroup]:
    """One group per expanded node with policy samples; infrastructure failures are left out."""
    backed_up = backed_up_values(targets)
    groups = []
    for node_id, edges in sorted(labels.edges_by_parent().items()):
        by_text: dict[str, list[EdgeLabel]] = {}
        for edge in edges:
            if edge.source == StepSource.POLICY and edge.effective_kind != EdgeKind.INFRASTRUCTURE_FAILURE:
                by_text.setdefault(edge.text.strip(), []).append(edge)
        if not by_text:
            continue
        node = record.nodes[node_id]
        groups.append(
            PolicyGroup(
                problem_name=record.problem_name,
                node_id=node_id,
                goals=node.goals,
                node_class=labels.node_classes[node_id],
                complete=node.status != NodeStatus.OPEN and not is_proving_expansion(edges, labels),
                samples=tuple(
                    group_sample(members, record, labels, estimates, backed_up, config) for members in by_text.values()
                ),
            )
        )
    return groups


def is_proving_expansion(edges: Sequence[EdgeLabel], labels: GraphLabels) -> bool:
    return any(
        edge.kind == EdgeKind.NEW_STATE and edge.target_id is not None and labels.remaining_steps[edge.target_id] == 0
        for edge in edges
    )


def normalized_advantages(group: PolicyGroup) -> tuple[float, ...]:
    """Reward minus the group mean over its samples, divided by the standard deviation; all 0 without spread."""
    mean = group.mean_reward
    variance = sum(sample.multiplicity * (sample.reward - mean) ** 2 for sample in group.samples) / group.sample_count
    if variance == 0:
        return tuple(0.0 for _ in group.samples)
    deviation = math.sqrt(variance)
    return tuple((sample.reward - mean) / deviation for sample in group.samples)
