from pathlib import Path

from expert_trees import TreeBuilder

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.expert_iteration.shards import AttemptRecord, Decision, ShardWriter
from lean_search.search import StopReason, TreeRecord


def statement(source: str, number: int) -> StatementRecord:
    return StatementRecord(source, f"{source}_{number}", "", f"theorem t{number} : True := by", "", "")


def attempt(
    name: str,
    *,
    stage: int = 0,
    version: int = 0,
    proved: bool = False,
    decision: Decision = Decision.RETIRED_UNPROMISING,
    root_value: float | None = 3.0,
    best_frontier_value: float | None = 2.0,
    max_depth: int = 1,
    finished_at: str = "2026-10-12T10:00:00+00:00",
) -> AttemptRecord:
    return AttemptRecord(
        problem_name=name,
        source=name.split(".", 1)[0],
        stage=stage,
        model_version=version,
        max_expansions=32,
        started_at="2026-10-12T09:59:00+00:00",
        finished_at=finished_at,
        proved=proved,
        stop_reason=StopReason.PROVED if proved else StopReason.EXPANSION_BUDGET,
        proof_steps=1 if proved else 0,
        expansions=2,
        total_expansions=2,
        nodes=3,
        wall_seconds=5.0,
        lean_seconds=4.0,
        prompt_tokens=500,
        generated_tokens=100,
        value_prompt_tokens=200,
        root_value=root_value,
        best_frontier_value=best_frontier_value,
        frontier_exhausted=False,
        max_depth=max_depth,
        harvested_proofs=0,
        harvest_expansions=0,
        decision=decision,
        tree_file=None,
    )


def solved_tree(problem_name: str) -> TreeRecord:
    """A policy step that a failed sibling competes with, then a closing step."""
    builder = TreeBuilder(f"⊢ r {problem_name}", problem_name=problem_name)
    builder.failure(builder.root, "exact foo")
    middle = builder.child(builder.root, f"⊢ s {problem_name}", step="intro x")
    builder.child(middle, f"⊢ open {problem_name}")
    proved = builder.child(middle, step="linarith")
    return builder.record(proved)


def unsolved_tree(problem_name: str) -> TreeRecord:
    builder = TreeBuilder(f"⊢ r {problem_name}", problem_name=problem_name)
    dead = builder.child(builder.root, f"⊢ false {problem_name}", step="exfalso")
    builder.failure(dead, "simp")
    builder.child(builder.root, f"⊢ open {problem_name}", step="constructor")
    return builder.record()


def write_shard(directory: Path, version: int, names: list[str], solved: set[str]) -> None:
    writer = ShardWriter(directory, max_attempts=1000, max_seconds=1e9)
    for name in names:
        is_solved = name in solved
        record = solved_tree(name) if is_solved else unsolved_tree(name)
        decision = Decision.SOLVED if is_solved else Decision.RETIRED_UNPROMISING
        writer.write(attempt(name, version=version, proved=is_solved, decision=decision), record)
    writer.close()


def verified(number: int, tactics: int, automation_solved: bool = False, is_verified: bool = True) -> VerifiedStatement:
    statement = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return VerifiedStatement(
        statement, ("s",), is_verified, "s", tactics, 10 * tactics, (f"⊢ {number}",), automation_solved, False, (), 1.0
    )
