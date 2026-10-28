from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardConfig, tactic_reward
from lean_search.search.graph_labels import EdgeKind
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome

REWARDS = RewardConfig()
PROOF_GRAPH = TacticLabel.PROOF_GRAPH
OFF_GRAPH = TacticLabel.OFF_GRAPH
UNKNOWN = TacticLabel.UNKNOWN
NO_PROGRESS = TacticLabel.NO_PROGRESS
REDUNDANT = TacticLabel.REDUNDANT_HYPOTHESIS
FAILING = TacticLabel.FAILING
MASKED = TacticLabel.MASKED


def sample(text: str, *labels: TacticLabel, multiplicity: int = 1, edge_id: int = 0, closed: int = 0) -> GroupSample:
    """A sample whose tactics carry these labels; the last one closes `closed` goals."""
    outcomes = [TacticOutcome(label) for label in labels]
    if closed:
        outcomes[-1] = TacticOutcome(labels[-1], goals_closed=closed)
    return GroupSample(
        text=text,
        edge_ids=(edge_id,),
        multiplicity=multiplicity,
        kind=EdgeKind.NEW_STATE,
        tactics=tuple(tactic_reward(outcome, REWARDS) for outcome in outcomes),
    )


def group(*samples: GroupSample, node_id: int = 0) -> PolicyGroup:
    return PolicyGroup("p", node_id, ("⊢ p",), samples)
