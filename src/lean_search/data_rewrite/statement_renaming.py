"""Search-time renaming: a statement's hypotheses renamed with the data's namer, and proofs checked on the original.

The renamed statement is alpha-equivalent to the original. A proof found for it is checked against the original
statement by prefixing Mathlib's `rename' old => new, …`, which gives the original's root state the renamed names, so
the found proof runs unchanged; `verify_proof` then elaborates the original theorem and audits its axioms.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.data_rewrite.naming import (
    HypothesisNamer,
    NameChange,
    NamingConfig,
    assign_names,
    renamed_text,
    statement_request,
)
from lean_search.lean import LeanRepl, VerificationResult
from lean_search.lean.text import join_tactics


@dataclass(frozen=True)
class StatementRenaming:
    original: str
    statement: str
    changes: tuple[NameChange, ...]


async def rename_statements(
    statements: Sequence[str],
    namer: HypothesisNamer,
    config: NamingConfig,
    reserved: frozenset[str] = frozenset(),
) -> list[StatementRenaming]:
    """Each statement with its numbered hypotheses renamed (unchanged when it has none)."""
    requests = {statement: statement_request(statement, config) for statement in dict.fromkeys(statements)}
    pending = {statement: request for statement, request in requests.items() if request is not None}
    named = dict(zip(pending, await assign_names(list(pending.values()), namer, config, reserved), strict=True))
    return [
        StatementRenaming(statement, renamed_text(statement, named.get(statement, ())), named.get(statement, ()))
        for statement in statements
    ]


def renaming_tactic(changes: Sequence[NameChange]) -> str | None:
    if not changes:
        return None
    return "rename' " + ", ".join(f"{change.old} => {change.new}" for change in changes)


def proof_of_original(changes: Sequence[NameChange], proof: str) -> str:
    """The proof found for the renamed statement, as a proof of the original statement."""
    tactic = renaming_tactic(changes)
    return proof if tactic is None else join_tactics([tactic, proof])


async def verify_against_original(
    repl: LeanRepl, header: str, original_statement: str, changes: Sequence[NameChange], proof: str
) -> VerificationResult:
    return await repl.verify_proof(original_statement, proof_of_original(changes, proof), header)
