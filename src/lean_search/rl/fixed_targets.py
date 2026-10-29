"""The fixed targets of the loop as runnable jobs: the probe set, miniF2F-valid, the held-out states and the value A/B.

Each runs against whatever the servers serve with the loop's search template, at the target's budget, without
harvesting or ε-exploration, and with the loop's statement renaming when it is on (the held-out states are traced
states with their original names and are never renamed). The loop serves its published policy and, for the probe and
miniF2F, the fixed value model of `EvaluationConfig.value_model`; the value A/B's two arms run on part of the probe set
with the reference and with the published value model.
"""

import time
from collections.abc import Callable, Sequence
from itertools import zip_longest
from pathlib import Path

from lean_search.data import Split, load_minif2f
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    EvaluationProblem,
    EvaluationSummary,
    now,
    run_problem_set_evaluation,
)
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.loop_config import EvaluationConfig, EvaluationTarget
from lean_search.rl.renaming import StatementRenamings
from lean_search.rl.search_models import evaluation_run_config
from lean_search.rl.single_step import (
    sample_success,
    search_states,
    single_step_run_config,
    state_problem,
    total_success,
)
from lean_search.search import RunConfig
from lean_search.search.records import to_json


def target_config(evaluation: EvaluationConfig, kind: EvaluationKind) -> EvaluationTarget:
    match kind:
        case EvaluationKind.PROBE:
            return evaluation.probe
        case EvaluationKind.MINIF2F:
            return evaluation.minif2f
        case EvaluationKind.HELD_OUT_STATES:
            return evaluation.held_out_states
        case EvaluationKind.VALUE_AB:
            return evaluation.value_ab


def probe_problems(path: Path) -> list[EvaluationProblem]:
    return [EvaluationProblem(statement.problem, statement.stratum.value) for statement in read_fixed_set(path)]


def first_problems_by_stratum(problems: Sequence[EvaluationProblem], count: int) -> list[EvaluationProblem]:
    """The first problems of each stratum in the set's order, taking the strata in turn."""
    by_stratum: dict[str, list[EvaluationProblem]] = {}
    for problem in problems:
        by_stratum.setdefault(problem.stratum, []).append(problem)
    interleaved = [problem for turn in zip_longest(*by_stratum.values()) for problem in turn if problem is not None]
    return interleaved[:count]


async def evaluate_held_out_states(
    states_path: Path,
    template: RunConfig,
    target: EvaluationTarget,
    directory: Path,
    versions: tuple[int, int],
    log: Callable[[str], None],
) -> EvaluationSummary:
    started_at = now()
    started = time.monotonic()
    states = [state_problem(state) for state in read_records(states_path, ReasoningState)]
    states = states[: target.problems] if target.problems else states
    config = single_step_run_config(evaluation_run_config(template, target))
    records = await search_states(states, config, directory / "trees", log)
    success = total_success(
        [sample_success(record, state.reference_keys) for record, state in zip(records, states, strict=True)]
    )
    summary = EvaluationSummary(
        kind=EvaluationKind.HELD_OUT_STATES,
        run_name=directory.name,
        policy_version=versions[0],
        value_version=versions[1],
        problems=success.states,
        solved=success.successes,
        by_stratum=(),
        expansion_budget=1,
        expansions=sum(record.result.accounting.expansions for record in records),
        generated_tokens=sum(record.result.accounting.generated_tokens for record in records),
        lean_seconds=sum(record.result.accounting.lean_seconds for record in records),
        wall_seconds=time.monotonic() - started,
        started_at=started_at,
        finished_at=now(),
        samples=success.samples,
    )
    (directory / "summary.json").write_text(to_json(summary), encoding="utf-8")
    return summary


async def evaluate_target(
    kind: EvaluationKind,
    evaluation: EvaluationConfig,
    template: RunConfig,
    directory: Path,
    versions: tuple[int, int],
    data_root: Path,
    runs_root: Path,
    renamings: StatementRenamings | None,
    log: Callable[[str], None],
) -> EvaluationSummary:
    """`template`: the loop's search config on the served models; results under `directory` (resumable)."""
    target = target_config(evaluation, kind)
    match kind:
        case EvaluationKind.PROBE:
            problems = probe_problems(data_root / evaluation.probe_set)
            problems = first_problems_by_stratum(problems, target.problems) if target.problems else problems
        case EvaluationKind.MINIF2F:
            problems = [EvaluationProblem(problem) for problem in load_minif2f(Split.VALID)]
            problems = problems[: target.problems] if target.problems else problems
        case EvaluationKind.HELD_OUT_STATES:
            states_path = runs_root / evaluation.held_out_states_file
            return await evaluate_held_out_states(states_path, template, target, directory, versions, log)
        case EvaluationKind.VALUE_AB:
            problems = first_problems_by_stratum(
                probe_problems(data_root / evaluation.probe_set), evaluation.value_ab_test.problems
            )
    config = evaluation_run_config(template, target)
    paths = EvaluationPaths(directory)
    return await run_problem_set_evaluation(kind, directory.name, versions, problems, config, paths, log, renamings)
