import json
from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.rl.fixed_sets import CharacterCandidate, CharacterStrataConfig, Exclusions, HeldOutStatement
from lean_search.rl.training_overlap import (
    exhaustive_duplicates,
    fingerprints,
    goal_statement,
    lsh_duplicates,
    names_where,
    pool_twins,
    proof_records,
    select_clear_of_training,
    training_roots,
)

ROOT = ("x y : ℝ\nh₀ : 0 < x\nh₁ : 0 < y\nh₂ : x + y = 1\n⊢ x * y ≤ 1 / 4",)
RENAMED_ROOT = ("a b : ℝ\nha : 0 < a\nhb : 0 < b\nhab : a + b = 1\n⊢ a * b ≤ 1 / 4",)
REORDERED_ROOT = ("x y : ℝ\nh₂ : x + y = 1\nh₀ : 0 < x\nh₁ : 0 < y\n⊢ x * y ≤ 1 / 4",)
DIFFERENT_ROOT = ("n : ℕ\nh : n % 4 = 3\n⊢ ¬∃ a b, a ^ 2 + b ^ 2 = n",)
NO_EXCLUSIONS = Exclusions(frozenset(), frozenset(), frozenset(), frozenset())


def candidate(name: str, goals: tuple[str, ...], stratum: str = "0-499") -> CharacterCandidate:
    statement = StatementRecord("s", name, "", f"theorem {name} : True := by", "", "")
    return CharacterCandidate(HeldOutStatement(statement, 1.0, stratum), goals)


# In the default seed's hash order s.near comes before s.far, so the first draw takes the near-duplicate.
DRAWN_FIRST_IS_NEAR = [candidate("near", RENAMED_ROOT), candidate("far", DIFFERENT_ROOT)]


def write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_a_goal_state_reads_as_a_theorem() -> None:
    assert (
        goal_statement(("x y : ℝ\nh : 0 < x\n⊢ x * y ≤ 1",)) == "theorem goal (x y : ℝ) (h : 0 < x) : x * y ≤ 1 := by"
    )


def test_a_hypothesis_continued_on_indented_lines_is_one_binder() -> None:
    assert goal_statement(("h :\n  ∃ a,\n    a = 1\n⊢ True",)) == "theorem goal (h : ∃ a, a = 1) : True := by"


def test_a_case_tag_is_left_out() -> None:
    assert goal_statement(("case left\nx : ℕ\n⊢ x = x",)) == "theorem goal (x : ℕ) : x = x := by"


def test_reordered_hypotheses_give_the_same_statement() -> None:
    assert goal_statement(REORDERED_ROOT) == goal_statement(ROOT)


def test_variables_come_before_the_hypotheses_in_their_own_order() -> None:
    statement = goal_statement(("n : ℕ\nh : 0 < n\nm : ℕ\n⊢ n = m",))
    assert statement == "theorem goal (n : ℕ) (m : ℕ) (h : 0 < n) : n = m := by"


def test_records_without_a_proof_position_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "math.jsonl"
    write_records(path, [{"problem": "1 + 1", "solution": "2"}, {"goals": ["⊢ a"], "proof_identifier": "p"}])
    assert list(proof_records(path)) == []


def test_a_proof_without_a_first_step_contributes_its_earliest_state(tmp_path: Path) -> None:
    records = [
        {"goals": ["⊢ c"], "proof_identifier": "p", "step_index": 3},
        {"goals": ["⊢ b"], "proof_identifier": "p", "step_index": 2},
        {"goals": ["⊢ r"], "identifier": "q", "depth": 0},
        {"goals": ["⊢ s"], "identifier": "q", "depth": 1},
    ]
    write_records(tmp_path / "sft/v2/train.jsonl", records)
    assert training_roots([tmp_path / "sft"]).states == (("⊢ b",), ("⊢ r",))


def test_a_missing_training_directory_is_refused(tmp_path: Path) -> None:
    write_records(tmp_path / "sft/train.jsonl", [{"goals": ["⊢ a"], "proof_identifier": "p", "step_index": 0}])
    with pytest.raises(ValueError, match="No training data directory"):
        training_roots([tmp_path / "sft", tmp_path / "reasoning"])


def test_a_training_directory_without_records_is_refused(tmp_path: Path) -> None:
    write_records(tmp_path / "math/math.jsonl", [{"problem": "1 + 1", "solution": "2"}])
    with pytest.raises(ValueError, match="No training record"):
        training_roots([tmp_path / "math"])


def test_lsh_finds_a_candidate_whose_root_is_a_renamed_training_root() -> None:
    candidates = [candidate("renamed", RENAMED_ROOT), candidate("different", DIFFERENT_ROOT)]
    hits = lsh_duplicates(fingerprints([item.root_goals for item in candidates]), fingerprints([ROOT]), 0.7)
    assert names_where(candidates, hits) == {"s.renamed"}


def test_every_pair_comparison_finds_a_root_with_reordered_hypotheses() -> None:
    assert exhaustive_duplicates(fingerprints([REORDERED_ROOT]), fingerprints([ROOT]), 0.7) == [True]


def test_a_drawn_statement_matching_a_training_root_is_replaced_by_the_next_in_its_band() -> None:
    candidates = DRAWN_FIRST_IS_NEAR
    config = CharacterStrataConfig(curriculum=CurriculumConfig(), edges=(500,), counts=(1, 0))
    selection = select_clear_of_training(
        candidates, fingerprints([item.root_goals for item in candidates]), fingerprints([ROOT]), config, NO_EXCLUSIONS
    )
    assert [statement.name for statement in selection.statements] == ["s.far"]


def test_the_replaced_statement_is_counted_as_a_drawn_near_duplicate() -> None:
    candidates = DRAWN_FIRST_IS_NEAR
    config = CharacterStrataConfig(curriculum=CurriculumConfig(), edges=(500,), counts=(1, 0))
    selection = select_clear_of_training(
        candidates, fingerprints([item.root_goals for item in candidates]), fingerprints([ROOT]), config, NO_EXCLUSIONS
    )
    assert selection.strata[0].drawn_near_training_duplicates == 1


def test_a_pool_statement_matching_a_drawn_one_is_its_twin() -> None:
    candidates = [candidate("drawn", ROOT), candidate("twin", RENAMED_ROOT), candidate("other", DIFFERENT_ROOT)]
    prints = fingerprints([item.root_goals for item in candidates])
    twins = pool_twins(candidates, prints, frozenset({"s.drawn"}), 0.7)
    assert [twin.name for twin in twins] == ["s.twin"]
