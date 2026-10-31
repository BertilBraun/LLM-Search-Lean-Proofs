"""GRPO groups at proof-graph nodes: each policy sample's tactics with their rewards R = (1 − λ) · G + λ · L."""

import dataclasses
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
    # L of a state off the proof graph with a claim (`have h : A`, `suffices`) nothing in the tree proves.
    unproved_claim_local: float = -1.0
    # L of an unknown state (too little evidence) and of an explored off-graph one: below the proof graph, above a
    # failure. Only a block's first state with a reward scores it; a later unknown one is an unverified continuation.
    unknown_local: float = -0.5
    # L per goal a tactic on the proof graph closes.
    goal_closed_bonus: float = 0.1
    # δ: a proof-graph state earns this per remaining step it is closer to a proof than the group's node (negative
    # when farther), its global part never below the best off-graph state's (1 − λ) · μ.
    progress_per_step: float = 0.2
    # c: the advantage of a failing, no-progress or redundant tactic other than the block's anchor (the block's prefix
    # is kept, so only its tokens are wasted), of a later unproved claim, of an unknown state ending a block after a
    # state with evidence, and of the closing tokens after a block stopping on an open claim. Continuing pays when
    # P(correct) > c / (c + δ).
    wasted_tactic_cost: float = 0.1
    # μ: an expanded off-graph state earns G = μ · q, q its value part; the loop's μ, 0 until set by hand.
    value_share: float = 0.0
    # An off-graph state with live children and fewer expanded nodes in its subtree (itself included) is unknown.
    off_graph_min_expanded_nodes: int = 4
    # Only groups with a policy sample reaching the proof graph; the automation sweep's children do not count.
    require_policy_proof: bool = True


@dataclass(frozen=True)
class RewardParts:
    # (1 − λ) · G plus δ per step of progress on the proof graph, and λ · L.
    global_part: float
    local_part: float

    @property
    def total(self) -> float:
        return self.global_part + self.local_part

    def __add__(self, other: "RewardParts") -> "RewardParts":
        return RewardParts(self.global_part + other.global_part, self.local_part + other.local_part)

    def __sub__(self, other: "RewardParts") -> "RewardParts":
        return RewardParts(self.global_part - other.global_part, self.local_part - other.local_part)


# Labels of a tactic reaching a state with a reward, and of those the tree has evidence on.
REACHED_STATE_LABELS = (
    TacticLabel.PROOF_GRAPH,
    TacticLabel.OFF_GRAPH,
    TacticLabel.UNKNOWN,
    TacticLabel.UNPROVED_CLAIM,
)
EVIDENCE_LABELS = (TacticLabel.PROOF_GRAPH, TacticLabel.OFF_GRAPH)
NO_GAIN = RewardParts(0.0, 0.0)


@dataclass(frozen=True)
class TacticReward:
    label: TacticLabel
    # R of the state reached; None for masked tactics, which earn nothing.
    parts: RewardParts | None
    # Judged within the block (`judged_in_block`). None with parts: the block's anchor, judged against the group's
    # first-tactic baseline.
    gain: RewardParts | None = None


@dataclass(frozen=True)
class JudgedBlock:
    tactics: tuple[TacticReward, ...]
    # The closing tokens' gain after a complete block: −c when it stops on an open claim, else 0.
    closing: RewardParts = NO_GAIN


@dataclass(frozen=True)
class GroupSample:
    text: str
    # Identical texts of the expansion merged into one sample: their edges and the policy samples behind them.
    edge_ids: tuple[int, ...]
    multiplicity: int
    kind: EdgeKind
    tactics: tuple[TacticReward, ...]
    closing: RewardParts = NO_GAIN

    @property
    def known(self) -> list[RewardParts]:
        return [tactic.parts for tactic in self.tactics if tactic.parts is not None]

    @property
    def anchor_parts(self) -> RewardParts | None:
        """R of the block's first state with a reward, else of its first tactic when that one failed or was a no-op,
        or of the failure ending an attempt at a claim."""
        return next((tactic.parts for tactic in self.tactics if tactic.parts is not None and tactic.gain is None), None)

    @property
    def score_parts(self) -> RewardParts | None:
        """The anchor plus every gain and the closing's: the reference state's R minus the wasted costs."""
        score = self.anchor_parts
        if score is None:
            return None
        for tactic in self.tactics:
            if tactic.gain is not None:
                score += tactic.gain
        return score + self.closing

    @property
    def score(self) -> float | None:
        parts = self.score_parts
        return None if parts is None else parts.total

    @property
    def complete(self) -> bool:
        return all(tactic.label not in (TacticLabel.FAILING, TacticLabel.MASKED) for tactic in self.tactics)


@dataclass(frozen=True)
class PolicyGroup:
    problem_name: str
    node_id: int
    goals: tuple[str, ...]
    samples: tuple[GroupSample, ...]
    # The node's feedback round: its own prompt, so its own group.
    feedback: bool = False

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


def tactic_reward(
    outcome: TacticOutcome, config: RewardConfig, node_steps: int, off_graph_global: float = 0.0
) -> TacticReward:
    """`node_steps`: the group node's remaining steps; `off_graph_global`: an off-graph state's G, `off_graph_value`."""
    match outcome.label:
        case TacticLabel.PROOF_GRAPH:
            assert outcome.remaining_steps is not None
            progress = config.progress_per_step * (node_steps - outcome.remaining_steps)
            on_graph = reward_parts(1.0, config.goal_closed_bonus * outcome.goals_closed, config)
            best_off_graph = reward_parts(config.value_share, 0.0, config)
            parts = RewardParts(max(on_graph.global_part + progress, best_off_graph.global_part), on_graph.local_part)
        case TacticLabel.OFF_GRAPH:
            parts = reward_parts(off_graph_global, config.unknown_local, config)
        case TacticLabel.NO_PROGRESS | TacticLabel.REDUNDANT_HYPOTHESIS:
            parts = reward_parts(0.0, config.no_progress_local, config)
        case TacticLabel.UNPROVED_CLAIM:
            parts = reward_parts(0.0, config.unproved_claim_local, config)
        case TacticLabel.UNKNOWN:
            parts = reward_parts(0.0, config.unknown_local, config)
        case TacticLabel.FAILING:
            parts = reward_parts(0.0, config.failure_local, config)
        case TacticLabel.MASKED:
            parts = None
    return TacticReward(outcome.label, parts)


def judged_in_block(rewards: Sequence[TacticReward], config: RewardConfig) -> JudgedBlock:
    """The anchor, the first tactic reaching a state with a reward (else the first tactic), keeps no gain. After it:
    - a proof-graph or off-graph state (evidence) gains over the reference, the last earlier such state or the anchor;
    - an unknown state after evidence keeps the reference: 0 when a later tactic reaches a state, −c when it ends the
      block's states (an unverified continuation, never below an error there); after an unknown anchor 0;
    - a failing, no-progress or redundant tactic and an unproved claim cost c.
    An unproved claim's tactics up to a failure are one failed attempt: 0 each, the failure judged where the claim
    was made (the anchor's failure R, or −c), so attempting never scores below the bare claim. The states after an
    open claim gain 0, and a complete block stopping on it costs c more at its closing tokens."""
    cost = RewardParts(0.0, -config.wasted_tactic_cost)
    labels = [reward.label for reward in rewards]
    claim = labels.index(TacticLabel.UNPROVED_CLAIM) if TacticLabel.UNPROVED_CLAIM in labels else None
    failure = labels.index(TacticLabel.FAILING) if TacticLabel.FAILING in labels else None
    attempt = range(claim, failure) if claim is not None and failure is not None else range(0)
    reached = [index for index, label in enumerate(labels) if label in REACHED_STATE_LABELS and index not in attempt]
    anchor = min(reached + ([failure] if attempt and failure is not None else []), default=0)
    reference: RewardParts | None = None
    evidence = False
    judged = []
    for index, reward in enumerate(rewards):
        gain = None
        after_claim = claim is not None and index > claim
        match reward.label:
            case _ if index in attempt:
                gain = NO_GAIN
            case TacticLabel.PROOF_GRAPH | TacticLabel.OFF_GRAPH | TacticLabel.UNKNOWN if after_claim:
                gain = NO_GAIN
            case TacticLabel.MASKED:
                pass
            case label if index == anchor:
                if label in REACHED_STATE_LABELS:
                    reference, evidence = reward.parts, label in EVIDENCE_LABELS
            case (
                TacticLabel.FAILING
                | TacticLabel.NO_PROGRESS
                | TacticLabel.REDUNDANT_HYPOTHESIS
                | TacticLabel.UNPROVED_CLAIM
            ):
                gain = cost
            case TacticLabel.UNKNOWN if evidence:
                gain = NO_GAIN if index < reached[-1] else cost
            case TacticLabel.PROOF_GRAPH | TacticLabel.OFF_GRAPH | TacticLabel.UNKNOWN:
                assert reward.parts is not None and reference is not None
                gain = reward.parts - reference
                reference, evidence = reward.parts, reward.label in EVIDENCE_LABELS
        judged.append(dataclasses.replace(reward, gain=gain))
    return JudgedBlock(tuple(judged), cost if claim is not None and failure is None else NO_GAIN)


def group_sample(
    edges: Sequence[EdgeLabel],
    outcomes: Sequence[TacticOutcome],
    labels: GraphLabels,
    estimates: Sequence[ValueEstimate | None],
    config: RewardConfig,
) -> GroupSample:
    node_steps = labels.remaining_steps[edges[0].parent_id]
    assert node_steps is not None
    rewards = [
        tactic_reward(
            outcome,
            config,
            node_steps,
            off_graph_value(outcome.node_id, labels, estimates, config)
            if outcome.label == TacticLabel.OFF_GRAPH
            else 0.0,
        )
        for outcome in outcomes
    ]
    block = judged_in_block(rewards, config)
    return GroupSample(
        text=edges[0].text.strip(),
        edge_ids=tuple(edge.edge_id for edge in edges),
        multiplicity=sum(edge.sample_count for edge in edges),
        kind=edges[0].effective_kind,
        tactics=block.tactics,
        closing=block.closing,
    )


def policy_groups(
    record: TreeRecord,
    labels: GraphLabels,
    tactics: Mapping[int, Sequence[TacticOutcome]],
    estimates: Sequence[ValueEstimate | None],
    config: RewardConfig,
) -> TreeGroups:
    """One group per prompt (the expansion's, its feedback round's) at an expanded proof-graph node with policy samples;
    `tactics` from `policy_tactics`. A sample whose names the search repaired is in its group with its own failed run;
    the repair (a REPAIR edge) is a search step like the sweep's, in no group and no policy proof, so a node only the
    repair put on the proof graph forms no group under `require_policy_proof`."""
    groups = []
    for node_id, edges in sorted(labels.edges_by_parent().items()):
        if labels.node_classes[node_id] != NodeClass.PROOF_GRAPH:
            continue
        by_prompt: dict[bool, dict[str, list[EdgeLabel]]] = {False: {}, True: {}}
        for edge in edges:
            if edge.source == StepSource.POLICY and edge.effective_kind != EdgeKind.INFRASTRUCTURE_FAILURE:
                by_text = by_prompt[record.edges[edge.edge_id].feedback]
                by_text.setdefault(edge.text.strip(), []).append(edge)
        for feedback, by_text in by_prompt.items():
            if not by_text:
                continue
            samples = tuple(
                group_sample(members, tactics[members[0].executed_edge_id], labels, estimates, config)
                for members in by_text.values()
            )
            groups.append(PolicyGroup(record.problem_name, node_id, record.nodes[node_id].goals, samples, feedback))
    kept = tuple(group for group in groups if group.has_policy_proof or not config.require_policy_proof)
    return TreeGroups(kept, len(groups) - len(kept))
