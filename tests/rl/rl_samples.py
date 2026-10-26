import dataclasses

from lean_search.rl.grpo_groups import (
    GroupSample,
    PolicyGroup,
    RewardComponents,
    RewardConfig,
    TokenCredit,
    total_reward,
)
from lean_search.search.graph_labels import EdgeKind, NodeClass

DENSE = RewardConfig(no_progress_reward=-0.5)


def components(*, failure: float = 0.0, shaping: float = 0.0, global_value: float = 0.0) -> RewardComponents:
    return RewardComponents(failure, 0.0, 0.0, shaping, 0.0, global_value)


def sample(
    text: str,
    parts: RewardComponents,
    *,
    first_failing_tactic: int | None = None,
    reached: bool = True,
    multiplicity: int = 1,
    edge_id: int = 0,
    config: RewardConfig = DENSE,
) -> GroupSample:
    """A sample whose valid prefix (when `reached`) earned its components without the failure."""
    prefix = dataclasses.replace(parts, failure=0.0)
    return GroupSample(
        text=text,
        edge_ids=(edge_id,),
        multiplicity=multiplicity,
        kind=EdgeKind.NEW_STATE if reached else EdgeKind.LEAN_ERROR,
        target_id=1 if reached else None,
        components=parts,
        reward=total_reward(parts, config),
        credit=TokenCredit(
            applied_tactics=0 if first_failing_tactic is None else first_failing_tactic,
            total_tactics=3,
            first_failing_tactic=first_failing_tactic,
            prefix_state_id=1 if reached else None,
            prefix_reward=total_reward(prefix, config) if reached else None,
        ),
    )


def group(*samples: GroupSample, node_id: int = 0) -> PolicyGroup:
    return PolicyGroup("p", node_id, ("⊢ p",), NodeClass.EXPANDED_OFF_GRAPH, True, samples)
