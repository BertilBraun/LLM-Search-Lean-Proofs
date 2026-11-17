"""Held-out success for the offline arm's rate choice that also accepts a block ending inside the reference next step's
nested proof, where the offline examples' 1-5-step blocks often end (review AX, S1)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lean_search.corpora.tracing import state_before
from lean_search.lean import LeanRepl
from lean_search.lean.plans import plan_block
from lean_search.reasoning.states import GoalKey, ReasoningState, goal_key
from lean_search.rl.rate_ranking import HeldOutStates
from lean_search.rl.single_step import StateProblem, sample_success, state_tree_path
from lean_search.search import read_tree
from lean_search.search.records import from_json_object

MAX_FAILURE_CHARACTERS = 300


@dataclass(frozen=True)
class FlatReference:
    identifier: str
    # The open states after each flattened tactic of the reference next step, before its end; empty when it failed.
    goal_keys: tuple[GoalKey, ...]
    failure: str = ""


async def flat_reference(repl: LeanRepl, state: ReasoningState) -> FlatReference:
    """A held-out state keeps its reference next step's text but not the later steps': only that step is flattened."""
    result = await repl.apply_block(state_before(state.step), plan_block(state.step.step, flatten=True))
    if result.failure is not None:
        return FlatReference(state.identifier, (), result.failure.message.strip()[:MAX_FAILURE_CHARACTERS])
    keys = tuple(dict.fromkeys(goal_key(tactic.goals) for tactic in result.tactic_states if tactic.goals))
    return FlatReference(state.identifier, keys)


def read_flat_references(path: Path) -> dict[str, FlatReference]:
    with path.open(encoding="utf-8") as lines:
        references = [from_json_object(FlatReference, json.loads(line)) for line in lines if line.strip()]
    return {reference.identifier: reference for reference in references}


def flattened_keys(problem: StateProblem, reference: FlatReference) -> frozenset[GoalKey]:
    return problem.reference_keys | frozenset(reference.goal_keys)


@dataclass(frozen=True)
class HeldOutMeasures:
    standard: HeldOutStates
    flattened: HeldOutStates


def held_out_measures(
    label: str, trees: Path, problems: Mapping[str, StateProblem], references: Mapping[str, FlatReference]
) -> HeldOutMeasures:
    """`problems` and `references` keyed by the state's identifier."""
    standard = {}
    flattened = {}
    for identifier, problem in problems.items():
        record = read_tree(state_tree_path(trees, problem))
        standard[problem.problem.name] = sample_success(record, problem.reference_keys)
        flattened[problem.problem.name] = sample_success(record, flattened_keys(problem, references[identifier]))
    return HeldOutMeasures(HeldOutStates(label, standard), HeldOutStates(label, flattened))
