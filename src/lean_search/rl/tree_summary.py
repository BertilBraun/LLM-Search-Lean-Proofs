"""What the loop keeps of every finished search in the tree index: computed once per tree as it finishes, so the
phase trigger (trainable groups), the per-phase budget and health signals and the search options A/B never re-read the
trees. The per-sample health fields count the first round's samples only: the feedback round (`policy.feedback`) runs
where the first round failed, so its samples would shift thresholds taken from phases without it."""

import dataclasses
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from lean_search.lean.hypotheses import adds_only_closed_form_hypotheses
from lean_search.lean.text import split_tactics
from lean_search.policy.prompts import visible_explanation
from lean_search.rl.advantages import CreditMode, group_advantages
from lean_search.rl.grpo_groups import RewardConfig, policy_groups
from lean_search.rl.phase_metrics import is_forced, repeats_itself
from lean_search.search.graph_labels import GraphLabels, label_graph
from lean_search.search.records import TreeRecord
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome, policy_tactics
from lean_search.search.tree import Edge, EdgeOutcome, FailureKind, StepSource

BARE_HAVE = re.compile(r"have(?![\w'!?])")
LINARITH = re.compile(r"n?linarith(?![\w'!?])")
EXPLANATION_BIN_CHARACTERS = 10
# The last bin holds every explanation from 1,990 characters on.
EXPLANATION_BINS = 200


@dataclass(frozen=True)
class BlockHabits:
    """The habits behind the reward hacking of phases 1-10 (DESIGN.md, 2026-10-31), over the first round's policy
    samples."""

    # Samples with a block Lean judged, and those of them opening with a bare `have h : A` (no `:=`).
    block_samples: int = 0
    bare_have_openings: int = 0
    # Bare-have openings whose block leaves the claim open (`TacticOutcome.leaves_claim_open`), and those of them whose
    # claim the tree proves (no `unproved_claim` label).
    open_claims: int = 0
    proved_claims: int = 0
    # Samples with a tactic adding only closed-form hypotheses to the state before it (`0 < (1:ℝ)`), on the proof
    # graph or off it.
    closed_form_fillers: int = 0
    # Explanation characters (before the opening fence) per sample, in 10-character bins.
    explanation_character_bins: tuple[int, ...] = ()
    # Samples opening with `have … :=` (a claim with its proof), and with linarith or nlinarith.
    proof_have_openings: int = 0
    linarith_openings: int = 0
    # Samples whose block ran completely, and their tactics after flattening.
    valid_blocks: int = 0
    valid_block_tactics: int = 0
    # Tactics reaching a proof-graph state with goals left, and those of them a further tactic of the block follows.
    proof_graph_steps: int = 0
    continued_proof_graph_steps: int = 0


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
    # The root's first-round blocks: distinct, judged by Lean and of those run completely (the A/B's balance check).
    root_blocks: int = 0
    root_judged_blocks: int = 0
    root_valid_blocks: int = 0
    # The published policy versions that sampled the tree's expansions.
    sampling_versions: tuple[int, ...] = ()
    # The curriculum fed the statement from below its band (`below_band_share`), not from the band.
    below_band: bool = False
    habits: BlockHabits = field(default_factory=BlockHabits)


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


def trainable_groups(
    record: TreeRecord,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
    reward: RewardConfig,
    credit: CreditMode,
) -> TrainableGroups:
    """The groups the trainer would train. μ is left out: it only adds μ · q to off-graph states, which hardly decides
    whether a group has a signal."""
    groups = policy_groups(record, labels, tactics, [None] * len(record.nodes), reward).groups
    trained = [group for group in groups if group_advantages(group).has_signal(credit)]
    return TrainableGroups(len(trained), sum(group.feedback for group in trained), labels.remaining_steps[0])


def opening(block: str) -> str:
    tactics = split_tactics(block)
    return tactics[0] if tactics else ""


def is_bare_have(block: str) -> bool:
    first = opening(block)
    return BARE_HAVE.match(first) is not None and ":=" not in first


def is_proof_have(block: str) -> bool:
    first = opening(block)
    return BARE_HAVE.match(first) is not None and ":=" in first


def is_linarith_opening(block: str) -> bool:
    return LINARITH.match(opening(block)) is not None


def proof_graph_steps(outcomes: Sequence[TacticOutcome]) -> list[bool]:
    """Per tactic reaching a proof-graph state with goals left: whether another tactic follows it."""
    return [
        index + 1 < len(outcomes)
        for index, outcome in enumerate(outcomes)
        if outcome.label == TacticLabel.PROOF_GRAPH and outcome.remaining_steps
    ]


def adds_closed_form_filler(record: TreeRecord, edge: Edge) -> bool:
    states = [record.nodes[edge.parent_id].goals, *edge.tactic_goals]
    return any(adds_only_closed_form_hypotheses(before, after) for before, after in pairwise(states))


def explanation_bins(texts: Iterable[str]) -> tuple[int, ...]:
    bins = [0] * EXPLANATION_BINS
    for text in texts:
        bins[min(len(visible_explanation(text)) // EXPLANATION_BIN_CHARACTERS, EXPLANATION_BINS - 1)] += 1
    while bins and not bins[-1]:
        bins.pop()
    return tuple(bins)


def summed_bins(histograms: Iterable[Sequence[int]]) -> tuple[int, ...]:
    totals: list[int] = []
    for histogram in histograms:
        totals.extend([0] * (len(histogram) - len(totals)))
        for index, count in enumerate(histogram):
            totals[index] += count
    return tuple(totals)


def binned_median(bins: Sequence[int]) -> float | None:
    """In characters, interpolated within the median's bin."""
    half = sum(bins) / 2
    below = 0
    for index, count in enumerate(bins):
        if count and below + count >= half:
            return EXPLANATION_BIN_CHARACTERS * (index + (half - below) / count)
        below += count
    return None


def block_habits(record: TreeRecord, tactics: Mapping[int, Sequence[TacticOutcome]]) -> BlockHabits:
    """`tactics`: `policy_tactics`."""
    habits = []
    for edge in record.edges:
        if edge.source != StepSource.POLICY or edge.feedback:
            continue
        executed = executed_edge(record, edge)
        if not executed.text.strip() or not judged_by_lean(executed):
            continue
        samples = edge.sample_count
        first = tactics[executed.edge_id][0]
        bare = is_bare_have(executed.text)
        open_claim = bare and first.leaves_claim_open
        valid = ran_completely(executed)
        steps = proof_graph_steps(tactics[executed.edge_id])
        habits.append(
            BlockHabits(
                block_samples=samples,
                bare_have_openings=samples * bare,
                open_claims=samples * open_claim,
                proved_claims=samples * (open_claim and first.label != TacticLabel.UNPROVED_CLAIM),
                closed_form_fillers=samples * adds_closed_form_filler(record, executed),
                proof_have_openings=samples * is_proof_have(executed.text),
                linarith_openings=samples * is_linarith_opening(executed.text),
                valid_blocks=samples * valid,
                valid_block_tactics=samples * valid * executed.applied_tactics,
                proof_graph_steps=samples * len(steps),
                continued_proof_graph_steps=samples * sum(steps),
            )
        )
    texts = (
        completion.text
        for expansion in record.expansions
        if not expansion.feedback
        for completion in expansion.completions
    )
    return summed_habits([*habits, BlockHabits(explanation_character_bins=explanation_bins(texts))])


def summed_habits(habits: Iterable[BlockHabits]) -> BlockHabits:
    habits = list(habits)
    counts = {
        item.name: sum(getattr(habit, item.name) for habit in habits)
        for item in dataclasses.fields(BlockHabits)
        if item.name != "explanation_character_bins"
    }
    return BlockHabits(
        **counts, explanation_character_bins=summed_bins(habit.explanation_character_bins for habit in habits)
    )


def tree_summary(
    record: TreeRecord,
    reward: RewardConfig,
    credit: CreditMode,
    expansion_budget: int,
    arm: str = "",
    below_band: bool = False,
) -> TreeSummary:
    blocks_by_expansion: defaultdict[int, int] = defaultdict(int)
    samples = 0
    executed = []
    root_executed = []
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
        if edge.parent_id == 0:
            root_executed.append(executed[-1])
    judged = [edge for edge in executed if judged_by_lean(edge)]
    root_judged = [edge for edge in root_executed if judged_by_lean(edge)]
    first_round = [expansion for expansion in record.expansions if not expansion.feedback]
    completions = [completion for expansion in first_round for completion in expansion.completions]
    cut_off = [completion for completion in completions if is_forced(completion)]
    labels = label_graph(record)
    tactics = policy_tactics(record, labels, reward.off_graph_min_expanded_nodes)
    groups = (
        trainable_groups(record, labels, tactics, reward, credit)
        if record.result.proved
        else TrainableGroups(0, 0, None)
    )
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
        root_blocks=len(root_executed),
        root_judged_blocks=len(root_judged),
        root_valid_blocks=sum(ran_completely(edge) for edge in root_judged),
        sampling_versions=tuple(
            sorted({version for expansion in record.expansions if (version := expansion.policy_version) is not None})
        ),
        below_band=below_band,
        habits=block_habits(record, tactics),
    )
