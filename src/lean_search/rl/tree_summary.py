"""What the loop keeps of every finished search in the tree index: computed once per tree as it finishes, so the
phase trigger (trainable groups), the per-phase budget and health signals and the search options A/B never re-read the
trees. The per-sample health fields count the first round's samples only: the feedback round (`policy.feedback`) runs
where the first round failed, so its samples would shift thresholds taken from phases without it."""

from collections import defaultdict
from dataclasses import dataclass

from lean_search.rl.advantages import CreditMode, group_advantages
from lean_search.rl.grpo_groups import RewardConfig, policy_groups
from lean_search.rl.phase_metrics import is_forced, repeats_itself
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import TreeRecord
from lean_search.search.tactic_labels import policy_tactics
from lean_search.search.tree import Edge, EdgeOutcome, FailureKind, StepSource


@dataclass(frozen=True)
class TreeSummary:
    # The search's expansion budget (`sampling.max_expansions` when it ran).
    expansion_budget: int = 0
    # The expansion that found the first proof, from 1; None when unsolved.
    solved_at_expansion: int | None = None
    # Top-level tactics of the shortest proof on the proof graph; None when unsolved.
    proof_steps: int | None = None
    # Groups the policy trains on: at proof-graph nodes, with a policy proof, with a non-zero advantage.
    trainable_groups: int = 0
    # First-round policy expansions, their samples, and per expansion the distinct blocks (identical blocks run once)
    # and the distinct sample texts, summed.
    policy_expansions: int = 0
    policy_samples: int = 0
    distinct_blocks: int = 0
    distinct_texts: int = 0
    # Samples cut off at the token cap (their answer forced), and those of them repeating their own text.
    cut_off_samples: int = 0
    repetition_loops: int = 0
    # Distinct policy blocks Lean judged (infrastructure failures left out), and those of them that ran completely:
    # the held-out states' valid-Lean criterion. A block whose names the search repaired is judged by its own run.
    judged_blocks: int = 0
    valid_blocks: int = 0
    # The search options A/B arm the statement fell into (`sampling.options_arm`); "" with the A/B off.
    arm: str = ""
    # Generated tokens of the whole tree (both rounds, harvesting included), and of those up to the first proof (all of
    # them when unsolved).
    generated_tokens: int = 0
    generated_tokens_to_first_proof: int = 0
    # Of `trainable_groups`, those of a node's feedback round.
    feedback_trainable_groups: int = 0
    lean_seconds: float = 0.0
    # Feedback rounds and their samples.
    feedback_expansions: int = 0
    feedback_samples: int = 0


def executed_edge(record: TreeRecord, edge: Edge) -> Edge:
    """The edge that ran: a repeated block's first run."""
    while edge.repeat_of is not None:
        edge = record.edges[edge.repeat_of]
    return edge


def ran_completely(edge: Edge) -> bool:
    return edge.failure is None and edge.outcome != EdgeOutcome.REJECTED and edge.target_id is not None


def judged_by_lean(edge: Edge) -> bool:
    return edge.failure is None or edge.failure.kind != FailureKind.REPL_FAILURE


@dataclass(frozen=True)
class TrainableGroups:
    groups: int
    feedback_groups: int
    # The root's remaining steps.
    proof_steps: int | None


def trainable_groups(record: TreeRecord, reward: RewardConfig, credit: CreditMode) -> TrainableGroups:
    """The groups the trainer would train. μ is left out: it only adds μ · q to off-graph states, which hardly decides
    whether a group has a signal."""
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, reward.off_graph_min_expanded_nodes)
    groups = policy_groups(record, labels, tactics, [None] * len(record.nodes), reward).groups
    trained = [group for group in groups if group_advantages(group).has_signal(credit)]
    return TrainableGroups(len(trained), sum(group.feedback for group in trained), labels.remaining_steps[0])


def tree_summary(
    record: TreeRecord, reward: RewardConfig, credit: CreditMode, expansion_budget: int, arm: str = ""
) -> TreeSummary:
    blocks_by_expansion: defaultdict[int, int] = defaultdict(int)
    samples = 0
    executed = []
    feedback_rounds: set[int] = set()
    feedback_samples = 0
    for edge in record.edges:
        if edge.source != StepSource.POLICY:
            continue
        if edge.feedback:
            feedback_rounds.add(edge.expansion_index)
            feedback_samples += edge.sample_count
            continue
        blocks_by_expansion[edge.expansion_index] += 1
        samples += edge.sample_count
        executed.append(executed_edge(record, edge))
    judged = [edge for edge in executed if judged_by_lean(edge)]
    first_round = [expansion for expansion in record.expansions if not expansion.feedback]
    completions = [completion for expansion in first_round for completion in expansion.completions]
    cut_off = [completion for completion in completions if is_forced(completion)]
    groups = trainable_groups(record, reward, credit) if record.result.proved else TrainableGroups(0, 0, None)
    accounting = record.result.accounting
    solved_at = record.result.solved_at
    return TreeSummary(
        expansion_budget=expansion_budget,
        solved_at_expansion=None if solved_at is None else solved_at.expansions,
        proof_steps=groups.proof_steps,
        trainable_groups=groups.groups,
        policy_expansions=len(blocks_by_expansion),
        policy_samples=samples,
        distinct_blocks=sum(blocks_by_expansion.values()),
        distinct_texts=sum(len({completion.text for completion in expansion.completions}) for expansion in first_round),
        cut_off_samples=len(cut_off),
        repetition_loops=sum(repeats_itself(completion.text) for completion in cut_off),
        judged_blocks=len(judged),
        valid_blocks=sum(ran_completely(edge) for edge in judged),
        arm=arm,
        generated_tokens=accounting.generated_tokens,
        feedback_trainable_groups=groups.feedback_groups,
        generated_tokens_to_first_proof=accounting.generated_tokens
        if solved_at is None
        else solved_at.generated_tokens,
        lean_seconds=accounting.lean_seconds,
        feedback_expansions=len(feedback_rounds),
        feedback_samples=feedback_samples,
    )
