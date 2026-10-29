"""Priority functions (lower is expanded first) and the batch value-estimator protocol used by A*."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lean_search.search.tree import Node, SearchTree, StepSource


@dataclass(frozen=True)
class Scores:
    priorities: tuple[float, ...]
    value_estimates: tuple[float, ...] | None = None
    prompt_tokens: int = 0
    # Per node, the value model's probabilities of its bins; empty for priorities without a binned value model.
    value_distributions: tuple[tuple[float, ...], ...] = ()


class PriorityFunction(Protocol):
    """Scores the new children of one expansion in one call."""

    async def score(self, nodes: Sequence[Node], tree: SearchTree) -> Scores: ...


@dataclass(frozen=True)
class ValueEstimates:
    remaining_steps: tuple[float, ...]
    prompt_tokens: int = 0
    # Per node, the probabilities of the value model's bins 1..7, 8+, dead; empty for estimators without bins.
    distributions: tuple[tuple[float, ...], ...] = ()


class ValueEstimator(Protocol):
    """Estimates the remaining proof steps h of each node, all nodes in one batch."""

    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates: ...


class DepthPlusGoals:
    async def score(self, nodes: Sequence[Node], tree: SearchTree) -> Scores:
        return Scores(tuple(float(node.depth + len(node.goals)) for node in nodes))


class CumulativeLogProbability:
    """-(sum of step log-probabilities on the path) / depth^length_exponent; automation steps use a fixed value."""

    def __init__(self, length_exponent: float, automation_log_probability: float) -> None:
        self.length_exponent = length_exponent
        self.automation_log_probability = automation_log_probability

    async def score(self, nodes: Sequence[Node], tree: SearchTree) -> Scores:
        return Scores(tuple(self.priority(node, tree) for node in nodes))

    def priority(self, node: Node, tree: SearchTree) -> float:
        if node.depth == 0:
            return 0.0
        path_log_probability = sum(self.step_log_probability(step) for step in tree.path(node)[1:])
        return -path_log_probability / node.depth**self.length_exponent

    def step_log_probability(self, node: Node) -> float:
        match node.source:
            case StepSource.AUTOMATION:
                return self.automation_log_probability
            case StepSource.POLICY:
                assert node.log_probability is not None, node.node_id
                return node.log_probability
            case None:
                raise AssertionError("The root has no step.")


class AStar:
    """f = depth_weight * depth + value_weight * h + policy_prior_weight * (-mean step log-probability on the path)."""

    def __init__(
        self,
        value_estimator: ValueEstimator,
        value_weight: float,
        depth_weight: float = 1.0,
        policy_prior_weight: float = 0.0,
        automation_log_probability: float = -1.0,
    ) -> None:
        self.value_estimator = value_estimator
        self.value_weight = value_weight
        self.depth_weight = depth_weight
        self.policy_prior_weight = policy_prior_weight
        self.policy_prior = CumulativeLogProbability(1.0, automation_log_probability)

    async def score(self, nodes: Sequence[Node], tree: SearchTree) -> Scores:
        estimates = await self.value_estimator.estimate(nodes)
        assert len(estimates.remaining_steps) == len(nodes)
        priorities = tuple(
            self.depth_weight * node.depth + self.value_weight * remaining + self.prior(node, tree)
            for node, remaining in zip(nodes, estimates.remaining_steps, strict=True)
        )
        return Scores(priorities, estimates.remaining_steps, estimates.prompt_tokens, estimates.distributions)

    def prior(self, node: Node, tree: SearchTree) -> float:
        if not self.policy_prior_weight:
            return 0.0
        return self.policy_prior_weight * self.policy_prior.priority(node, tree)


class GoalCountEstimator:
    async def estimate(self, nodes: Sequence[Node]) -> ValueEstimates:
        return ValueEstimates(tuple(float(len(node.goals)) for node in nodes))


class PriorityKind(StrEnum):
    DEPTH_PLUS_GOALS = "depth_plus_goals"
    CUMULATIVE_LOG_PROBABILITY = "cumulative_log_probability"
    A_STAR = "a_star"


class ValueEstimatorKind(StrEnum):
    GOAL_COUNT = "goal_count"


@dataclass(frozen=True)
class PriorityConfig:
    kind: PriorityKind = PriorityKind.DEPTH_PLUS_GOALS
    length_exponent: float = 1.0
    automation_log_probability: float = -1.0
    value_weight: float = 1.0
    # A*'s weight on the depth, and on the path's mean negative step log-probability (automation steps count as
    # automation_log_probability); 0 leaves the policy prior out.
    depth_weight: float = 1.0
    policy_prior_weight: float = 0.0
    value_estimator: ValueEstimatorKind = ValueEstimatorKind.GOAL_COUNT


def build_value_estimator(kind: ValueEstimatorKind) -> ValueEstimator:
    match kind:
        case ValueEstimatorKind.GOAL_COUNT:
            return GoalCountEstimator()


def build_priority_function(config: PriorityConfig, value_estimator: ValueEstimator | None = None) -> PriorityFunction:
    match config.kind:
        case PriorityKind.DEPTH_PLUS_GOALS:
            return DepthPlusGoals()
        case PriorityKind.CUMULATIVE_LOG_PROBABILITY:
            return CumulativeLogProbability(config.length_exponent, config.automation_log_probability)
        case PriorityKind.A_STAR:
            estimator = value_estimator or build_value_estimator(config.value_estimator)
            return AStar(
                estimator,
                config.value_weight,
                config.depth_weight,
                config.policy_prior_weight,
                config.automation_log_probability,
            )
