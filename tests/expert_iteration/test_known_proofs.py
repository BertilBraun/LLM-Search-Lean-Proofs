from pathlib import Path

import pytest
from loop_fixtures import verified

from lean_search.corpora.records import ProofRecord, StatementRecord
from lean_search.expert_iteration.known_proofs import (
    StatementProofs,
    add_proof,
    easiest_first,
    is_negation,
    known_proof,
    read_verified,
    skipped_statement,
)
from lean_search.search.records import to_json

STATEMENT = "theorem t (x : ℕ) : x + 0 = x := by"


def proof(tactic_proof: str, source: str = "goedel_sft_v2", statement: str = STATEMENT) -> ProofRecord:
    return ProofRecord(source, f"{source}/{len(tactic_proof)}", "t@1", "import Mathlib", statement, tactic_proof, "")


def test_a_proof_counts_its_top_level_tactics() -> None:
    record = known_proof(proof("have h : x + 0 = x := by\n  simp\nexact h"))
    assert (record.top_level_tactics, record.characters) == (2, 39)


def test_a_statement_keeps_its_shortest_distinct_proofs() -> None:
    groups: dict[str, StatementProofs] = {}
    for text in ("simp\nrfl\nrfl", "simp", "omega\nrfl", "simp"):
        add_proof(groups, "key", proof(text), proofs_per_statement=2)
    assert [candidate.tactic_proof for candidate in groups["key"].proofs] == ["simp", "omega\nrfl"]


def test_the_first_corpus_names_the_statement_and_every_corpus_is_listed() -> None:
    groups: dict[str, StatementProofs] = {}
    add_proof(groups, "key", proof("simp", source="leanabell_sft"), proofs_per_statement=2)
    add_proof(groups, "key", proof("omega", source="goedel_sft_v2"), proofs_per_statement=2)
    (statement,) = easiest_first(groups)
    assert (statement.statement.source, statement.proof_sources) == (
        "leanabell_sft",
        ("goedel_sft_v2", "leanabell_sft"),
    )


def test_statements_come_easiest_first() -> None:
    groups: dict[str, StatementProofs] = {}
    add_proof(groups, "long", proof("simp\nring\nlinarith", statement="theorem a : True := by"), 3)
    add_proof(groups, "short", proof("trivial", statement="theorem b : True := by"), 3)
    assert [statement.statement_key for statement in easiest_first(groups)] == ["short", "long"]


def test_reading_verified_records_waits_for_a_line_being_written(tmp_path: Path) -> None:
    path = tmp_path / "verified.jsonl"
    complete = to_json(verified(0, 1)) + "\n"
    path.write_bytes((complete + to_json(verified(1, 1))[:20]).encode())
    records, offset = read_verified(path)
    assert ([record.name for record in records], offset) == (["s.t0"], len(complete.encode()))


@pytest.mark.parametrize(
    ("statement", "negation"),
    [
        ("theorem extracted_7d0b_negation : ¬ (∀ x : ℝ, x = 2) := by", True),
        ("theorem lean_workbook_1 (x : ℝ) : x = x := by", False),
        ("example : (1 : ℕ) = 1 := by", False),
    ],
)
def test_proved_negations_are_recognized_by_name(statement: str, negation: bool) -> None:
    assert is_negation(StatementRecord("s", "t", "", statement, "", "")) == negation


def test_a_skipped_statement_is_recorded_but_not_usable() -> None:
    groups: dict[str, StatementProofs] = {}
    add_proof(groups, "key", proof("simp"), proofs_per_statement=2)
    (candidate,) = easiest_first(groups)
    record = skipped_statement(candidate)
    assert (record.skipped, record.verified, record.proof_tactics) == (True, False, 1)
