"""Expert-iteration data from the GRPO loop's own trees (rl/README.md, "Expert iteration"): the verified blocks at
proof-graph states exactly as the policy sampled them (the recorded prompt and token ids, the sequence GRPO trains on),
selected with caps per state, per statement and on easy states, and split by statement into training and validation."""

import dataclasses
import hashlib
import json
import random
import tomllib
import zlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.mixing import is_held_out
from lean_search.policy.prompts import render_prompt, visible_explanation
from lean_search.rl.policy_data import CompletionTokens, PolicyTokenizer, completion_tokens
from lean_search.search.graph_labels import (
    EdgeKind,
    GoalKey,
    GraphLabels,
    NodeClass,
    goal_key,
    label_graph,
    shortest_distances,
)
from lean_search.search.records import TreeRecord, from_json_object, read_tree, to_json
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome, policy_tactics
from lean_search.search.texts import ExpansionTexts, SampledCompletion
from lean_search.search.tree import StepSource
from lean_search.training.sft import SftConfig
from lean_search.training.sft_data import SftExample, TokenizedExample

EXAMPLE_SOURCE = "expert_iteration"
# Block lengths in the summary: 1 to 7 tactics, then 8 or more.
LONGEST_COUNTED_BLOCK = 8


@dataclass(frozen=True)
class ExpertIterationDataConfig:
    # The loop's run directory under $LEAN_SEARCH_RUNS.
    loop: str = "grpo_loop_v1"
    # Phases from the reward fix's first phase (reward_fix.json) to this one; 0: up to the phase before the one
    # collecting now, whose trees are partial.
    last_phase: int = 0
    blocks_per_state: int = 2
    states_per_statement: int = 6
    # Of all examples, at most this share at easy states (every first-round sample a block on the proof graph).
    max_easy_share: float = 0.2
    validation_fraction: float = 0.05
    seed: str = "grpo-expert-iteration-1"
    # As the phases' [reward] off_graph_min_expanded_nodes.
    off_graph_min_expanded_nodes: int = 4


@dataclass(frozen=True)
class ReplayConfig:
    # Under $LEAN_SEARCH_DATA, as the loop's [training] lean_replay and math_replay.
    lean_replay: str
    math_replay: str
    # Shares of all training tokens.
    lean_token_share: float = 0.3
    math_token_share: float = 0.1
    # Under $LEAN_SEARCH_DATA: replay validation examples added to the expert-iteration validation set.
    validation: str = ""
    validation_examples: int = 1000
    seed: str = "grpo-expert-iteration-1/replay"


@dataclass(frozen=True)
class ExpertIterationConfig:
    # The adapter goes to $LEAN_SEARCH_CHECKPOINTS/<run_name>/adapter, the summary to $LEAN_SEARCH_RUNS/<run_name>.
    run_name: str
    data: ExpertIterationDataConfig
    replay: ReplayConfig
    # `data` names $LEAN_SEARCH_DATA/grpo_expert_iteration/<data>; `initial_adapter` is filled in at training time
    # with the loop's current policy adapter.
    sft: SftConfig


def parse_expert_iteration_config(text: str) -> ExpertIterationConfig:
    config = from_json_object(ExpertIterationConfig, tomllib.loads(text))
    data = config.data
    if data.blocks_per_state < 1 or data.states_per_statement < 1:
        raise ValueError("data needs blocks_per_state >= 1 and states_per_statement >= 1.")
    if not 0 <= data.max_easy_share < 1 or not 0 <= data.validation_fraction < 1:
        raise ValueError("data needs 0 <= max_easy_share < 1 and 0 <= validation_fraction < 1.")
    replay = config.replay
    if (
        min(replay.lean_token_share, replay.math_token_share) < 0
        or replay.lean_token_share + replay.math_token_share >= 1
    ):
        raise ValueError("replay token shares must be non-negative and sum to less than 1.")
    return config


@dataclass(frozen=True)
class CompletionFilter:
    """What the loop must not train on again, and what the evaluations hold out."""

    # Samples of earlier versions, and of unrecorded ones, predate the reward fix.
    minimum_version: int
    rejected_versions: frozenset[int] = frozenset()
    held_out_statements: frozenset[str] = frozenset()
    held_out_goal_keys: frozenset[GoalKey] = frozenset()


class Verdict(StrEnum):
    """Per recorded sample at an expanded proof-graph node: the first filter that dropped it, else kept."""

    FEEDBACK_ROUND = "feedback_round"
    REJECTED_VERSION = "rejected_version"
    BEFORE_MINIMUM_VERSION = "before_minimum_version"
    HELD_OUT_STATE = "held_out_state"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    OFF_PROOF_GRAPH = "off_proof_graph"
    CLAIM_LEFT_OPEN = "claim_left_open"
    OFF_SHORTEST_ROUTE = "off_shortest_route"
    RETOKENIZED = "retokenized"
    FORCED = "forced"
    TOKEN_MISMATCH = "token_mismatch"
    KEPT = "kept"


@dataclass(frozen=True)
class FilterCounts:
    unreadable_trees: int = 0
    held_out_trees: int = 0
    feedback_round: int = 0
    rejected_version: int = 0
    before_minimum_version: int = 0
    held_out_state: int = 0
    infrastructure_failure: int = 0
    off_proof_graph: int = 0
    claim_left_open: int = 0
    off_shortest_route: int = 0
    retokenized: int = 0
    forced: int = 0
    token_mismatch: int = 0
    kept: int = 0

    @staticmethod
    def of(verdicts: Iterable[Verdict]) -> "FilterCounts":
        return FilterCounts(**Counter(verdict.value for verdict in verdicts))

    def __add__(self, other: "FilterCounts") -> "FilterCounts":
        return FilterCounts(
            *(mine + theirs for mine, theirs in zip(dataclasses.astuple(self), dataclasses.astuple(other), strict=True))
        )


@dataclass(frozen=True)
class ProofGraphCompletion:
    """A verified block at a proof-graph state as sampled: `tokenized` is the recorded prompt's ids and the recorded
    completion ids, the loop's `PolicySequence.tokenized`."""

    problem_name: str
    goals: tuple[str, ...]
    block: str
    tokenized: TokenizedExample
    policy_version: int
    tactics: int
    explanation_characters: int
    ended_turn: bool
    # Every first-round sample at the state ran a block whose every tactic is on the proof graph.
    easy: bool
    # On a shortest route from the root to a proof.
    on_root_route: bool
    # The recorded prompt is the replay's (render_prompt with visible reasoning, nothing else in it).
    prompt_like_replay: bool

    @property
    def state(self) -> tuple[str, GoalKey]:
        return self.problem_name, goal_key(self.goals)


@dataclass(frozen=True)
class TreeCompletions:
    completions: tuple[ProofGraphCompletion, ...] = ()
    counts: FilterCounts = field(default_factory=FilterCounts)


def seeded_order(seed: str, *parts: str) -> bytes:
    return hashlib.sha256("\0".join((seed, *parts)).encode()).digest()


def block_order(completion: ProofGraphCompletion, seed: str) -> bytes:
    """Independent of the tree and the sample, so a state's blocks rank alike wherever they were sampled."""
    problem_name, key = completion.state
    return seeded_order(seed, problem_name, *key, completion.block)


def completion_order(completion: ProofGraphCompletion, seed: str) -> bytes:
    return seeded_order(seed, completion.problem_name, repr(completion.tokenized.input_ids))


def root_route_nodes(labels: GraphLabels) -> frozenset[int]:
    root_steps = labels.remaining_steps[0]
    if root_steps is None:
        return frozenset()
    distances = shortest_distances([0], labels.successors)
    return frozenset(
        node_id
        for node_id, distance in distances.items()
        if (steps := labels.remaining_steps[node_id]) is not None and distance + steps == root_steps
    )


def block_verdict(outcomes: Sequence[TacticOutcome], node_steps: int) -> Verdict:
    """One tactic gains at most one step, so a block whose last state is as many steps closer as it has tactics never
    detours."""
    if any(outcome.label != TacticLabel.PROOF_GRAPH for outcome in outcomes):
        return Verdict.OFF_PROOF_GRAPH
    if any(outcome.leaves_claim_open for outcome in outcomes):
        return Verdict.CLAIM_LEFT_OPEN
    if outcomes[-1].remaining_steps != node_steps - len(outcomes):
        return Verdict.OFF_SHORTEST_ROUTE
    return Verdict.KEPT


def expansion_verdict(
    expansion: ExpansionTexts, goals: tuple[str, ...], completion_filter: CompletionFilter
) -> Verdict:
    if expansion.feedback:
        return Verdict.FEEDBACK_ROUND
    if expansion.policy_version in completion_filter.rejected_versions:
        return Verdict.REJECTED_VERSION
    if expansion.policy_version is None or expansion.policy_version < completion_filter.minimum_version:
        return Verdict.BEFORE_MINIMUM_VERSION
    if goal_key(goals) in completion_filter.held_out_goal_keys:
        return Verdict.HELD_OUT_STATE
    return Verdict.KEPT


class TreeBlocks:
    """The labelled tree's policy blocks per recorded sample."""

    def __init__(self, record: TreeRecord, config: ExpertIterationDataConfig) -> None:
        self.labels = label_graph(record)
        self.tactics = policy_tactics(record, self.labels, config.off_graph_min_expanded_nodes)

    def outcomes(self, completion: SampledCompletion) -> tuple[TacticOutcome, ...] | None:
        """None for a sample the search could not run (an infrastructure failure)."""
        label = self.labels.edges[completion.edge_id]
        if label.source != StepSource.POLICY or label.effective_kind == EdgeKind.INFRASTRUCTURE_FAILURE:
            return None
        return self.tactics[label.executed_edge_id]

    def easy(self, expansion: ExpansionTexts) -> bool:
        return all(
            (outcomes := self.outcomes(completion)) is not None
            and all(outcome.label == TacticLabel.PROOF_GRAPH for outcome in outcomes)
            for completion in expansion.completions
        )


def token_verdict(tokens: CompletionTokens) -> Verdict:
    if tokens.retokenized:
        return Verdict.RETOKENIZED
    if tokens.inserted:
        return Verdict.FORCED
    if tokens.offsets is None:
        return Verdict.TOKEN_MISMATCH
    return Verdict.KEPT


def proof_graph_completions(
    record: TreeRecord,
    tokenizer: PolicyTokenizer,
    config: ExpertIterationDataConfig,
    completion_filter: CompletionFilter,
) -> TreeCompletions:
    """The tree's kept samples, at most `blocks_per_state` distinct blocks per state (those `selected_completions`
    would keep of them), and every recorded sample's verdict."""
    if record.problem_name in completion_filter.held_out_statements:
        return TreeCompletions(counts=FilterCounts(held_out_trees=1))
    blocks = TreeBlocks(record, config)
    labels = blocks.labels
    on_root_route = root_route_nodes(labels)
    verdicts: list[Verdict] = []
    kept: list[ProofGraphCompletion] = []
    for expansion in record.expansions:
        if labels.node_classes[expansion.node_id] != NodeClass.PROOF_GRAPH:
            continue
        node = record.nodes[expansion.node_id]
        node_steps = labels.remaining_steps[node.node_id]
        assert node_steps is not None
        shared = expansion_verdict(expansion, node.goals, completion_filter)
        if shared != Verdict.KEPT:
            verdicts += [shared] * len(expansion.completions)
            continue
        easy = blocks.easy(expansion)
        prompt_like_replay = expansion.prompt == render_prompt(tokenizer, node.goals, visible=True)
        prompt_ids: list[int] | None = None
        for completion in expansion.completions:
            outcomes = blocks.outcomes(completion)
            verdict = Verdict.INFRASTRUCTURE_FAILURE if outcomes is None else block_verdict(outcomes, node_steps)
            tokens = completion_tokens(tokenizer, completion) if verdict == Verdict.KEPT else None
            if tokens is not None:
                verdict = token_verdict(tokens)
            verdicts.append(verdict)
            if verdict != Verdict.KEPT:
                continue
            assert outcomes is not None and tokens is not None and expansion.policy_version is not None
            if prompt_ids is None:
                prompt_ids = tokenizer.encode(expansion.prompt, add_special_tokens=False)
            block = record.edges[completion.edge_id].text.strip()
            example = SftExample(
                EXAMPLE_SOURCE, f"{record.problem_name}#{node.node_id}", completion.edge_id, node.goals, block
            )
            kept.append(
                ProofGraphCompletion(
                    problem_name=record.problem_name,
                    goals=node.goals,
                    block=block,
                    tokenized=TokenizedExample(example, (*prompt_ids, *tokens.token_ids), len(prompt_ids)),
                    policy_version=expansion.policy_version,
                    tactics=len(outcomes),
                    explanation_characters=len(visible_explanation(completion.text)),
                    ended_turn=completion.ended_turn,
                    easy=easy,
                    on_root_route=node.node_id in on_root_route,
                    prompt_like_replay=prompt_like_replay,
                )
            )
    return TreeCompletions(tuple(capped_blocks(kept, config)), FilterCounts.of(verdicts))


def file_completions(
    path: Path, tokenizer: PolicyTokenizer, config: ExpertIterationDataConfig, completion_filter: CompletionFilter
) -> TreeCompletions:
    """An unreadable tree (truncated, corrupt) is counted and skipped."""
    try:
        record = read_tree(path)
    except (OSError, EOFError, ValueError, zlib.error):
        return TreeCompletions(counts=FilterCounts(unreadable_trees=1))
    return proof_graph_completions(record, tokenizer, config, completion_filter)


def capped_blocks(
    completions: Iterable[ProofGraphCompletion], config: ExpertIterationDataConfig
) -> list[ProofGraphCompletion]:
    """Per state its first `blocks_per_state` distinct blocks in the seeded block order, each as its first sample in
    the seeded sample order; both orders are global, so capping each tree first keeps what capping all at once would."""
    chosen: dict[tuple[str, GoalKey], dict[str, ProofGraphCompletion]] = defaultdict(dict)
    for completion in completions:
        by_block = chosen[completion.state]
        earlier = by_block.get(completion.block)
        if earlier is None or completion_order(completion, config.seed) < completion_order(earlier, config.seed):
            by_block[completion.block] = completion
    return [
        completion
        for by_block in chosen.values()
        for completion in sorted(by_block.values(), key=lambda completion: block_order(completion, config.seed))[
            : config.blocks_per_state
        ]
    ]


@dataclass(frozen=True)
class SelectedCompletions:
    train: tuple[ProofGraphCompletion, ...]
    validation: tuple[ProofGraphCompletion, ...]
    # Distinct states with a kept block, those left after the per-statement cap, and the easy examples the share
    # cap dropped.
    states: int
    capped_states: int
    dropped_easy_examples: int


def selected_completions(
    completions: Iterable[ProofGraphCompletion], config: ExpertIterationDataConfig
) -> SelectedCompletions:
    """Deduplicated by state across trees, at most `blocks_per_state` blocks per state, `states_per_statement` states
    per statement (those on the root's shortest route first) and `max_easy_share` of the examples at easy states (a
    state is easy only if it was easy in every tree, on the root's route if it was in any)."""
    by_state: dict[tuple[str, GoalKey], list[ProofGraphCompletion]] = defaultdict(list)
    for completion in completions:
        by_state[completion.state].append(completion)
    by_statement: dict[str, list[list[ProofGraphCompletion]]] = defaultdict(list)
    for (problem_name, _), members in by_state.items():
        easy = all(member.easy for member in members)
        on_root_route = any(member.on_root_route for member in members)
        blocks = [
            dataclasses.replace(completion, easy=easy, on_root_route=on_root_route)
            for completion in capped_blocks(members, config)
        ]
        by_statement[problem_name].append(blocks)
    kept_states = [
        blocks
        for states in by_statement.values()
        for blocks in sorted(
            states,
            key=lambda blocks: (
                not blocks[0].on_root_route,
                seeded_order(config.seed, blocks[0].problem_name, *goal_key(blocks[0].goals)),
            ),
        )[: config.states_per_statement]
    ]
    examples = [completion for blocks in kept_states for completion in blocks]
    hard = [completion for completion in examples if not completion.easy]
    easy = sorted(
        (completion for completion in examples if completion.easy),
        key=lambda completion: completion_order(completion, config.seed),
    )
    allowed_easy = int(config.max_easy_share * len(hard) / (1 - config.max_easy_share))
    kept = sorted([*hard, *easy[:allowed_easy]], key=lambda completion: completion_order(completion, config.seed))
    train: list[ProofGraphCompletion] = []
    validation: list[ProofGraphCompletion] = []
    for completion in kept:
        held_out = is_held_out(completion.problem_name, config.seed, config.validation_fraction)
        (validation if held_out else train).append(completion)
    return SelectedCompletions(
        tuple(train),
        tuple(validation),
        len(by_state),
        len(kept_states),
        max(0, len(easy) - allowed_easy),
    )


def write_completions(path: Path, completions: Iterable[ProofGraphCompletion]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for completion in completions:
            handle.write(to_json(completion) + "\n")
            count += 1
    return count


def read_completions(path: Path) -> list[ProofGraphCompletion]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(ProofGraphCompletion, json.loads(line)) for line in lines if line.strip()]


def examples_within_tokens[T](
    items: Sequence[T], tokenize: Callable[[T], TokenizedExample], token_budget: int, seed: str
) -> list[TokenizedExample]:
    """Items in a seeded random order, tokenized until their tokens reach the budget."""
    order = list(items)
    random.Random(seed).shuffle(order)
    examples: list[TokenizedExample] = []
    tokens = 0
    for item in order:
        if tokens >= token_budget:
            break
        example = tokenize(item)
        examples.append(example)
        tokens += example.token_count
    return examples


def replay_token_budgets(expert_iteration_tokens: int, config: ReplayConfig) -> tuple[int, int]:
    """The Lean and math replay tokens that make up their shares of all training tokens."""
    total = expert_iteration_tokens / (1 - config.lean_token_share - config.math_token_share)
    return round(total * config.lean_token_share), round(total * config.math_token_share)


@dataclass(frozen=True)
class DataSummary:
    train_examples: int
    validation_examples: int
    statements: int
    states: int
    tokens: int
    completion_tokens: int
    easy_share: float
    ended_turn_share: float
    prompts_unlike_replay: int
    # Examples by block length: 1 to 7 tactics, then 8 or more.
    tactics: tuple[int, ...]
    # The explanation's characters before the fence: 10th percentile, median, 90th percentile.
    explanation_characters: tuple[int, ...]
    policy_versions: tuple[int, ...]


def percentile(ordered: Sequence[int], fraction: float) -> int:
    return ordered[round(fraction * (len(ordered) - 1))]


def data_summary(selected: SelectedCompletions) -> DataSummary:
    examples = [*selected.train, *selected.validation]
    count = max(1, len(examples))
    lengths = Counter(min(completion.tactics, LONGEST_COUNTED_BLOCK) for completion in examples)
    characters = sorted(completion.explanation_characters for completion in examples) or [0]
    return DataSummary(
        train_examples=len(selected.train),
        validation_examples=len(selected.validation),
        statements=len({completion.problem_name for completion in examples}),
        states=len({completion.state for completion in examples}),
        tokens=sum(completion.tokenized.token_count for completion in examples),
        completion_tokens=sum(completion.tokenized.completion_token_count for completion in examples),
        easy_share=sum(completion.easy for completion in examples) / count,
        ended_turn_share=sum(completion.ended_turn for completion in examples) / count,
        prompts_unlike_replay=sum(not completion.prompt_like_replay for completion in examples),
        tactics=tuple(lengths[length] for length in range(1, LONGEST_COUNTED_BLOCK + 1)),
        explanation_characters=tuple(percentile(characters, fraction) for fraction in (0.1, 0.5, 0.9)),
        policy_versions=tuple(sorted({completion.policy_version for completion in examples})),
    )
