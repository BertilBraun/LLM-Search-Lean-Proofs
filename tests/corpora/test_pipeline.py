import json
from pathlib import Path

from lean_search.corpora.decontamination import SimilarityAssessment
from lean_search.corpora.leandojo import tactic_examples
from lean_search.corpora.pipeline import (
    TACTIC_COUNT_BUCKETS,
    NormalizedProof,
    cap_proofs_per_statement,
    length_distribution,
    merge_proof_sources,
    select_for_tracing,
)
from lean_search.corpora.records import (
    PremiseReference,
    ProofRecord,
    TacticExample,
    read_proof_records,
    read_tactic_examples,
    write_jsonl,
)

CLEAN = SimilarityAssessment(None, 0.0, "", 0.0, "")


def proof(source: str, statement_key: str, proof_key: str) -> NormalizedProof:
    record = ProofRecord(
        source=source,
        identifier=f"{source}/{statement_key}/{proof_key}",
        statement_identifier=statement_key,
        header="import Mathlib",
        formal_statement=f"theorem {statement_key} : True := by",
        tactic_proof=proof_key,
        lean_version_hint="hint",
    )
    return NormalizedProof(record, statement_key, proof_key, 1, CLEAN, None)


def test_cap_keeps_at_most_cap_proofs_per_statement() -> None:
    kept, _ = cap_proofs_per_statement([proof("a", "s1", f"p{index}") for index in range(5)], cap=3)
    assert len(kept) == 3


def test_cap_records_distinct_proof_count_before_capping() -> None:
    kept, _ = cap_proofs_per_statement([proof("a", "s1", f"p{index}") for index in range(5)], cap=3)
    assert {item.record.distinct_proofs_for_statement for item in kept} == {5}


def test_cap_counts_statements_over_the_cap() -> None:
    proofs = [proof("a", "s1", f"p{index}") for index in range(5)] + [proof("a", "s2", "p0")]
    assert cap_proofs_per_statement(proofs, cap=3)[1] == 1


def test_merge_prefers_sources_in_priority_order() -> None:
    kept_by_source = {"first": [proof("first", "s1", "p1")], "second": [proof("second", "s1", "p2")]}
    merged = merge_proof_sources(kept_by_source, ("first", "second"), cap=1)
    assert [item.record.source for item in merged] == ["first"]


def test_merge_drops_identical_proofs_from_other_sources() -> None:
    kept_by_source = {"first": [proof("first", "s1", "p1")], "second": [proof("second", "s1", "p1")]}
    merged = merge_proof_sources(kept_by_source, ("first", "second"), cap=3)
    assert len(merged) == 1


def test_selection_keeps_every_proof_of_fully_included_sources() -> None:
    merged = [proof("complete", "s1", "p1"), proof("complete", "s1", "p2"), proof("sampled", "s2", "p3")]
    selected = select_for_tracing(merged, frozenset({"complete"}), budget=2)
    assert [item.record.source for item in selected] == ["complete", "complete"]


def test_selection_samples_one_proof_per_statement_up_to_the_budget() -> None:
    merged = [proof("sampled", f"s{index}", f"p{index}{copy}") for index in range(4) for copy in range(2)]
    selected = select_for_tracing(merged, frozenset(), budget=3)
    assert len({item.statement_key for item in selected}) == len(selected) == 3


def test_length_distribution_buckets_values() -> None:
    distribution = length_distribution([1, 1, 2, 7, 60], TACTIC_COUNT_BUCKETS)
    assert distribution.histogram == {"1": 2, "2": 1, "3": 0, "4-5": 0, "6-10": 1, "11-20": 0, "21-50": 0, "51+": 1}


def test_proof_records_round_trip_through_jsonl(tmp_path: Path) -> None:
    record = proof("a", "s1", "simp").record
    write_jsonl(tmp_path / "proofs.jsonl", [record])
    assert list(read_proof_records(tmp_path / "proofs.jsonl")) == [record]


def test_tactic_examples_round_trip_through_jsonl(tmp_path: Path) -> None:
    example = TacticExample(
        source="leandojo",
        identifier="Nat.foo#0",
        split="random/train",
        file_path="Mathlib/Foo.lean",
        theorem_full_name="Nat.foo",
        theorem_start_line=3,
        tactic_index=0,
        state_before="⊢ True",
        tactic="simp [bar]",
        annotated_tactic="simp [<a>bar</a>]",
        state_after="no goals",
        premises=(PremiseReference("Nat.bar", "Mathlib/Bar.lean"),),
    )
    write_jsonl(tmp_path / "tactics.jsonl", [example])
    assert list(read_tactic_examples(tmp_path / "tactics.jsonl")) == [example]


def test_leandojo_tactic_examples_carry_premises(tmp_path: Path) -> None:
    (tmp_path / "random").mkdir()
    theorem = {
        "full_name": "Nat.foo",
        "file_path": "Mathlib/Foo.lean",
        "start": [3, 1],
        "traced_tactics": [
            {
                "tactic": "simp [bar]",
                "annotated_tactic": [
                    "simp [<a>bar</a>]",
                    [
                        {
                            "full_name": "Nat.bar",
                            "def_path": "Mathlib/Bar.lean",
                            "def_pos": [1, 1],
                            "def_end_pos": [1, 4],
                        }
                    ],
                ],
                "state_before": "⊢ True",
                "state_after": "no goals",
            }
        ],
    }
    (tmp_path / "random" / "train.json").write_text(json.dumps([theorem]), encoding="utf-8")
    examples = list(tactic_examples(tmp_path, "random", "train"))
    assert examples[0].premises == (PremiseReference("Nat.bar", "Mathlib/Bar.lean"),)
