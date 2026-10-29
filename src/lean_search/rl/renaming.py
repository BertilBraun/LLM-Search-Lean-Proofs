"""Optional search-time renaming of statement hypotheses (the naming A/B's named policy), off by default.

Renamings are computed once with the data rewrite's namer (`grpo_fixed_sets.py rename`) and looked up by problem name,
so the loop, the evaluations and the gate search name a statement the same way the named training data did. The search
runs on the renamed statement; a proof it finds is verified against the original statement with a `rename'` prefix
(`data_rewrite.statement_renaming`), and one that does not verify counts as unsolved and keeps no tree. Statements
without a renaming are searched as they are and counted.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from lean_search.data import Problem
from lean_search.data_rewrite.naming import HypothesisNamer, NamingConfig
from lean_search.data_rewrite.statement_renaming import (
    StatementRenaming,
    rename_statements,
    verify_against_original,
)
from lean_search.lean import LeanRepl
from lean_search.search import CompletedSearch, Expander, PriorityFunction, SearchConfig, search_theorem
from lean_search.search.records import from_json_object, to_json


@dataclass(frozen=True)
class RenamingConfig:
    # On when the starting policy is the naming A/B's named arm.
    enabled: bool = False
    # Renaming files (`RenamedStatement` lines) under $LEAN_SEARCH_DATA.
    renamings: tuple[str, ...] = ("grpo/renamings.jsonl",)


@dataclass(frozen=True)
class RenamedStatement:
    problem_name: str
    renaming: StatementRenaming


@dataclass
class StatementRenamings:
    by_name: Mapping[str, StatementRenaming]
    # Problems searched without a renaming, and found proofs that failed the check against the original.
    missing: int = 0
    failed_original_checks: int = 0

    def renamed(self, problem: Problem) -> tuple[Problem, StatementRenaming | None]:
        renaming = self.by_name.get(problem.name)
        if renaming is None:
            self.missing += 1
            return problem, None
        assert renaming.original == problem.formal_statement, problem.name
        return replace(problem, formal_statement=renaming.statement), renaming


def write_renamings(path: Path, renamed: Iterable[RenamedStatement]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [to_json(item) + "\n" for item in renamed]
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(lines), encoding="utf-8")
    temporary.replace(path)
    return len(lines)


def read_renamings(paths: Sequence[Path]) -> StatementRenamings:
    by_name: dict[str, StatementRenaming] = {}
    for path in paths:
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    item = from_json_object(RenamedStatement, json.loads(line))
                    by_name[item.problem_name] = item.renaming
    return StatementRenamings(by_name)


def load_renamings(config: RenamingConfig, data_root: Path) -> StatementRenamings | None:
    if not config.enabled:
        return None
    return read_renamings([data_root / path for path in config.renamings])


async def rename_problems(
    problems: Sequence[Problem], namer: HypothesisNamer, naming: NamingConfig, reserved: frozenset[str]
) -> list[RenamedStatement]:
    renamings = await rename_statements([problem.formal_statement for problem in problems], namer, naming, reserved)
    return [RenamedStatement(problem.name, renaming) for problem, renaming in zip(problems, renamings, strict=True)]


async def search_problem(
    problem: Problem,
    repl: LeanRepl,
    expander: Expander,
    priority_function: PriorityFunction,
    config: SearchConfig,
    renamings: StatementRenamings | None,
) -> CompletedSearch:
    """The search of the problem, or of its renamed statement with the proof checked against the original."""
    if renamings is None:
        return await search_theorem(problem, repl, expander, priority_function, config)
    searched, renaming = renamings.renamed(problem)
    completed = await search_theorem(searched, repl, expander, priority_function, config)
    result = completed.result
    if renaming is None or not renaming.changes or not result.proved:
        return completed
    assert result.proof is not None, problem.name
    verification = await verify_against_original(
        repl, problem.header, renaming.original, renaming.changes, result.proof
    )
    if verification.verified:
        return CompletedSearch(replace(result, original_verified=True), completed.tree)
    renamings.failed_original_checks += 1
    return CompletedSearch(replace(result, proved=False, original_verified=False), None)
