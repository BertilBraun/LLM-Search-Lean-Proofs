"""What the loop keeps of every finished search in the tree index: computed once per tree as it finishes, so the
phase trigger (trainable groups) and the per-phase budget and health signals never re-read the trees."""

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
    # Policy expansions, their samples, and per expansion the distinct blocks (identical blocks run once) and the
    # distinct sample texts, summed.
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
    generated_tokens: int = 0


def executed_edge(record: TreeRecord, edge: Edge) -> Edge:
    """The edge that ran: a repeated block's first run."""
    while edge.repeat_of is not None:
        edge = record.edges[edge.repeat_of]
    return edge


def ran_completely(edge: Edge) -> bool:
    return edge.failure is None and edge.outcome != EdgeOutcome.REJECTED and edge.target_id is not None


def judged_by_lean(edge: Edge) -> bool:
    return edge.failure is None or edge.failure.kind != FailureKind.REPL_FAILURE


def trainable_groups(record: TreeRecord, reward: RewardConfig, credit: CreditMode) -> tuple[int, int | None]:
    """The groups the trainer would train and the root's remaining steps. μ is left out: it only adds μ · q to
    off-graph states, which hardly decides whether a group has a signal."""
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, reward.off_graph_min_expanded_nodes)
    groups = policy_groups(record, labels, tactics, [None] * len(record.nodes), reward).groups
    return sum(group_advantages(group).has_signal(credit) for group in groups), labels.remaining_steps[0]


def tree_summary(
    record: TreeRecord, reward: RewardConfig, credit: CreditMode, expansion_budget: int, arm: str = ""
) -> TreeSummary:
    blocks_by_expansion: defaultdict[int, int] = defaultdict(int)
    samples = 0
    executed = []
    for edge in record.edges:
        if edge.source == StepSource.POLICY:
            blocks_by_expansion[edge.expansion_index] += 1
            samples += edge.sample_count
            executed.append(executed_edge(record, edge))
    judged = [edge for edge in executed if judged_by_lean(edge)]
    completions = [completion for expansion in record.expansions for completion in expansion.completions]
    cut_off = [completion for completion in completions if is_forced(completion)]
    groups, proof_steps = trainable_groups(record, reward, credit) if record.result.proved else (0, None)
    solved_at = record.result.solved_at
    return TreeSummary(
        expansion_budget=expansion_budget,
        solved_at_expansion=None if solved_at is None else solved_at.expansions,
        proof_steps=proof_steps,
        trainable_groups=groups,
        policy_expansions=len(blocks_by_expansion),
        policy_samples=samples,
        distinct_blocks=sum(blocks_by_expansion.values()),
        distinct_texts=sum(
            len({completion.text for completion in expansion.completions}) for expansion in record.expansions
        ),
        cut_off_samples=len(cut_off),
        repetition_loops=sum(repeats_itself(completion.text) for completion in cut_off),
        judged_blocks=len(judged),
        valid_blocks=sum(ran_completely(edge) for edge in judged),
        arm=arm,
        generated_tokens=record.result.accounting.generated_tokens,
    )
