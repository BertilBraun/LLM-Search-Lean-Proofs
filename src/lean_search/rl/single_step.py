"""Single-step GRPO on fixed proof states (DESIGN.md "Order of work", cheap tests) and per-sample success on them.

A state is a traced step of a held-out proof (`ReasoningState`, the per-step evaluation's 512 states). One policy
request per state samples n blocks, each executed in Lean from the state, rebuilt by replay; the result is a search
tree with one expansion (`search_theorem` with `start_state`), recorded like the loop's (tokens, tactic states).

Which tactics are on the proof graph: the state is provable (its traced proof proves it), and so is every state of
that proof after it. A tactic is on the proof graph when it closes the goals or reaches the reference proof's next or
a later state (the per-step evaluation's success criterion, by goal key); other new states are unknown and neutral.
So every state has a known-provable anchor without a further search; a state forms no group when no sample reaches
the proof graph (`RewardConfig.require_policy_proof`). Remaining steps are the reference proof's (or a found proof's
tactics, if fewer), so reaching a later reference state earns more progress. A sample succeeds when its block runs
completely and ends on the proof graph.
"""

import asyncio
import contextlib
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.corpora.tracing import state_before
from lean_search.data import Problem, Split
from lean_search.lean import LeanReplConfig, LeanReplPool, ProofState
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.grpo_groups import RewardConfig, TreeGroups, policy_groups
from lean_search.rl.policy_data import PolicyTree
from lean_search.rl.search_models import open_search_models
from lean_search.rl.training_phase import LabelledPhaseData
from lean_search.rl.tree_statistics import graph_statistics, total_statistics
from lean_search.search import ExpanderKind, PriorityKind, RunConfig, TreeRecord, search_theorem, tree_record
from lean_search.search.graph_labels import EdgeKind, GoalKey, GraphLabels, NodeClass, goal_key, label_graph
from lean_search.search.records import read_tree, write_tree
from lean_search.search.tactic_labels import TacticLabel, TacticOutcome, policy_tactics
from lean_search.search.tree import EdgeOutcome, StepSource


@dataclass(frozen=True)
class SingleStepArm:
    # Its run directory under the experiment's, and the training phase config (credit mode) it trains with.
    name: str
    phase_config: str


@dataclass(frozen=True)
class SingleStepConfig:
    # $LEAN_SEARCH_RUNS/<name>/.
    name: str
    # The search template: the policy servers (serving the policy as `policy.model`) and the harness.
    search_config: str
    # The weights the arms' adapters apply to (the phase configs' `policy.model`).
    policy_base_model: str
    # States files (ReasoningState lines) under $LEAN_SEARCH_RUNS: the trained states and a disjoint set.
    train_states: str
    disjoint_states: str
    arms: tuple[SingleStepArm, ...]
    # Sampling and training rounds; each trains `passes_per_phase` passes over its round's groups.
    rounds: int = 3
    concurrency: int = 64
    # Overrides the template's policy servers (e.g. the three serving GPUs); empty keeps them.
    policy_server_urls: tuple[str, ...] = ()
    # The starting policy's own adapter on policy_base_model, which every arm continues and the KL reference;
    # empty: policy_base_model is the starting policy and the arms train fresh adapters.
    policy_adapter: str = ""


@dataclass(frozen=True)
class StateProblem:
    problem: Problem
    start: ProofState
    # The reference proof's next state and every later one (the last is empty: proved), with the reference's
    # remaining steps from each.
    reference_steps: Mapping[GoalKey, int]

    @property
    def reference_keys(self) -> frozenset[GoalKey]:
        return frozenset(self.reference_steps)


@dataclass(frozen=True)
class SampleSuccess:
    states: int
    samples: int
    successes: int

    @property
    def rate(self) -> float:
        return self.successes / self.samples if self.samples else 0.0


def state_problem_name(state: ReasoningState) -> str:
    return state.identifier.replace("/", "_").replace("#", ".")


def state_problem(state: ReasoningState) -> StateProblem:
    step = state.step
    problem = Problem(state_problem_name(state), Split.VALID, step.header, step.formal_statement, "", "")
    return StateProblem(problem, state_before(step), reference_steps(state.reference_goal_keys))


def reference_steps(keys: Sequence[GoalKey]) -> dict[GoalKey, int]:
    """Each reference state's fewest remaining steps; `keys` in the reference proof's order, the proof last."""
    return {key: len(keys) - 1 - index for index, key in enumerate(keys)}


def single_step_run_config(template: RunConfig) -> RunConfig:
    """One policy request per state, no automation sweep, no value model, nothing after it."""
    search = dataclasses.replace(
        template.search,
        max_expansions=1,
        harvest=dataclasses.replace(template.search.harvest, enabled=False),
        exploration=dataclasses.replace(template.search.exploration, enabled=False),
    )
    return dataclasses.replace(
        template,
        search=search,
        expander=dataclasses.replace(template.expander, kind=ExpanderKind.POLICY, overlap=False),
        priority=dataclasses.replace(template.priority, kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY),
        value=dataclasses.replace(template.value, model=""),
    )


def reference_labels(
    record: TreeRecord, reference_steps: Mapping[GoalKey, int], min_expanded_nodes: int
) -> tuple[GraphLabels, dict[int, tuple[TacticOutcome, ...]]]:
    """The tree's labels with the root on the proof graph, and tactics reaching a reference state on it too."""
    labels = label_graph(record)
    found_steps = labels.remaining_steps[0]
    reference_root_steps = 1 + max(reference_steps.values(), default=0)
    root_steps = reference_root_steps if found_steps is None else min(found_steps, reference_root_steps)
    labels = dataclasses.replace(
        labels,
        node_classes=(NodeClass.PROOF_GRAPH, *labels.node_classes[1:]),
        remaining_steps=(root_steps, *labels.remaining_steps[1:]),
    )
    tactics = policy_tactics(record, labels, min_expanded_nodes)
    for edge_id, outcomes in tactics.items():
        edge = record.edges[edge_id]
        previous = record.nodes[edge.parent_id].goals
        relabelled = list(outcomes)
        for index, goals in enumerate(edge.tactic_goals):
            key = goal_key(goals)
            if relabelled[index].label == TacticLabel.UNKNOWN and key in reference_steps:
                closed = max(0, len(previous) - len(goals))
                node_id = relabelled[index].node_id
                relabelled[index] = TacticOutcome(TacticLabel.PROOF_GRAPH, node_id, closed, reference_steps[key])
            previous = goals
        tactics[edge_id] = tuple(relabelled)
    return labels, tactics


def single_step_groups(
    record: TreeRecord, labels: GraphLabels, tactics: Mapping[int, Sequence[TacticOutcome]], config: RewardConfig
) -> TreeGroups:
    """`labels` and `tactics` from `reference_labels`."""
    tree_groups = policy_groups(record, labels, tactics, [None] * len(record.nodes), config)
    return dataclasses.replace(tree_groups, groups=tuple(group for group in tree_groups.groups if group.node_id == 0))


def sample_success(record: TreeRecord, reference_keys: frozenset[GoalKey]) -> SampleSuccess:
    """The root's policy samples whose block ran completely and ended closed or on a reference state."""
    labels = label_graph(record)
    samples = 0
    successes = 0
    for edge in labels.edges:
        if edge.parent_id != 0 or edge.source != StepSource.POLICY:
            continue
        if edge.effective_kind == EdgeKind.INFRASTRUCTURE_FAILURE:
            continue
        samples += edge.sample_count
        executed = record.edges[edge.executed_edge_id]
        if executed.failure is not None or executed.outcome == EdgeOutcome.REJECTED or executed.target_id is None:
            continue
        target = record.nodes[executed.target_id]
        goals = executed.tactic_goals[-1] if executed.tactic_goals else target.goals
        proved = not target.goals and labels.node_classes[target.node_id] == NodeClass.PROOF_GRAPH
        if proved or (goals and goal_key(goals) in reference_keys):
            successes += edge.sample_count
    return SampleSuccess(1, samples, successes)


def total_success(successes: Sequence[SampleSuccess]) -> SampleSuccess:
    return SampleSuccess(
        sum(success.states for success in successes),
        sum(success.samples for success in successes),
        sum(success.successes for success in successes),
    )


async def search_states(
    states: Sequence[StateProblem],
    config: RunConfig,
    trees_directory: Path,
    log: Callable[[str], None],
) -> list[TreeRecord]:
    """One single-step search per state (trees already written are read back); the records in the states' order."""
    pending = [state for state in states if not (trees_directory / f"{state.problem.name}.json.gz").exists()]
    if pending:
        async with contextlib.AsyncExitStack() as stack:
            models = await stack.enter_async_context(open_search_models(config))
            pool = await stack.enter_async_context(
                LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction)
            )
            await pool.start(sorted({state.problem.header for state in pending}))
            semaphore = asyncio.Semaphore(config.lean.concurrency)
            finished = 0

            async def search_one(state: StateProblem) -> None:
                nonlocal finished
                async with semaphore, pool.acquire() as repl:
                    completed = await search_theorem(
                        state.problem,
                        repl,
                        models.expander,
                        models.priority_function,
                        config.search,
                        state.start,
                    )
                assert completed.tree is not None, state.problem.name
                record = tree_record(completed.tree, state.problem.formal_statement, completed.result)
                await asyncio.to_thread(write_tree, trees_directory / f"{state.problem.name}.json.gz", record)
                finished += 1
                if finished % 64 == 0 or finished == len(pending):
                    log(f"{finished}/{len(pending)} states sampled")

            await asyncio.gather(*(search_one(state) for state in pending))
    return [read_tree(trees_directory / f"{state.problem.name}.json.gz") for state in states]


def single_step_phase_data(
    records: Sequence[TreeRecord], states: Sequence[StateProblem], config: RewardConfig
) -> LabelledPhaseData:
    """The root groups of the single-step trees, labelled against each state's reference proof."""
    policy_trees = []
    statistics = []
    for record, state in zip(records, states, strict=True):
        labels, tactics = reference_labels(record, state.reference_steps, config.off_graph_min_expanded_nodes)
        tree_groups = single_step_groups(record, labels, tactics, config)
        policy_trees.append(PolicyTree(tree_groups.groups, record.expansions))
        statistics.append(graph_statistics(record, labels, (), tactics, tree_groups))
    return LabelledPhaseData((), tuple(policy_trees), total_statistics(statistics))
