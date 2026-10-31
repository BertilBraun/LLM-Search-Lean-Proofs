from lean_search.rl.grpo_groups import GroupSample, PolicyGroup, RewardConfig, judged_in_block, tactic_reward
from lean_search.search.graph_labels import EdgeKind
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome

REWARDS = RewardConfig()
# The group node's remaining steps.
NODE_STEPS = 4
PROOF_GRAPH = TacticLabel.PROOF_GRAPH
OFF_GRAPH = TacticLabel.OFF_GRAPH
UNKNOWN = TacticLabel.UNKNOWN
NO_PROGRESS = TacticLabel.NO_PROGRESS
REDUNDANT = TacticLabel.REDUNDANT_HYPOTHESIS
FAILING = TacticLabel.FAILING
MASKED = TacticLabel.MASKED
UNPROVED_CLAIM = TacticLabel.UNPROVED_CLAIM


def sample(
    text: str,
    *labels: TacticLabel,
    multiplicity: int = 1,
    edge_id: int = 0,
    closed: int = 0,
    steps: tuple[int, ...] = (),
) -> GroupSample:
    """The last tactic closes `closed` goals; proof-graph tactics reach `steps`, by default one step closer each."""
    proof_graph_steps = iter(steps or range(NODE_STEPS - 1, -1, -1))
    outcomes = [
        TacticOutcome(label, remaining_steps=next(proof_graph_steps) if label == PROOF_GRAPH else None)
        for label in labels
    ]
    outcomes[-1] = TacticOutcome(labels[-1], goals_closed=closed, remaining_steps=outcomes[-1].remaining_steps)
    rewards = [tactic_reward(outcome, REWARDS, NODE_STEPS) for outcome in outcomes]
    return GroupSample(
        text=text,
        edge_ids=(edge_id,),
        multiplicity=multiplicity,
        kind=EdgeKind.NEW_STATE,
        tactics=judged_in_block(rewards, REWARDS),
    )


def group(*samples: GroupSample, node_id: int = 0) -> PolicyGroup:
    return PolicyGroup("p", node_id, ("⊢ p",), samples)
