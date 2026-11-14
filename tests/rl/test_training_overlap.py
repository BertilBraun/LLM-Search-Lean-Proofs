import json
from pathlib import Path

from lean_search.corpora.records import StatementRecord
from lean_search.rl.fixed_sets import CharacterCandidate, HeldOutStatement
from lean_search.rl.training_overlap import (
    goal_statement,
    near_training_duplicates,
    root_states,
    training_root_states,
)

ROOT = ("x y : ℝ\nh₀ : 0 < x\nh₁ : 0 < y\nh₂ : x + y = 1\n⊢ x * y ≤ 1 / 4",)
RENAMED_ROOT = ("a b : ℝ\nha : 0 < a\nhb : 0 < b\nhab : a + b = 1\n⊢ a * b ≤ 1 / 4",)
DIFFERENT_ROOT = ("n : ℕ\nh : n % 4 = 3\n⊢ ¬∃ a b, a ^ 2 + b ^ 2 = n",)


def candidate(name: str, goals: tuple[str, ...]) -> CharacterCandidate:
    statement = StatementRecord("s", name, "", f"theorem {name} : True := by", "", "")
    return CharacterCandidate(HeldOutStatement(statement, 1.0, "0-499"), goals)


def test_a_goal_state_reads_as_a_theorem() -> None:
    assert (
        goal_statement(("x y : ℝ\nh : 0 < x\n⊢ x * y ≤ 1",)) == "theorem goal (x y : ℝ) (h : 0 < x) : x * y ≤ 1 := by"
    )


def test_a_hypothesis_continued_on_indented_lines_is_one_binder() -> None:
    assert goal_statement(("h :\n  ∃ a,\n    a = 1\n⊢ True",)) == "theorem goal (h : ∃ a, a = 1) : True := by"


def test_a_case_tag_is_left_out() -> None:
    assert goal_statement(("case left\nx : ℕ\n⊢ x = x",)) == "theorem goal (x : ℕ) : x = x := by"


def test_root_states_are_the_first_steps_and_the_value_datas_depth_zero(tmp_path: Path) -> None:
    records = [
        {"goals": ["⊢ a"], "step_index": 0},
        {"goals": ["⊢ b"], "step_index": 1},
        {"goals": ["⊢ c"], "depth": 0},
        {"goals": ["⊢ d"], "depth": 2},
        {"problem": "1 + 1", "solution": "2"},
    ]
    path = tmp_path / "train.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    assert list(root_states(path)) == [("⊢ a",), ("⊢ c",)]


def test_training_root_states_read_every_jsonl_file_below_the_directories(tmp_path: Path) -> None:
    for directory, goal in (("sft/v2", "⊢ a"), ("value/v0", "⊢ b")):
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "train.jsonl").write_text(
            json.dumps({"goals": [goal], "step_index": 0}) + "\n", encoding="utf-8"
        )
    assert training_root_states([tmp_path / "sft", tmp_path / "value"]) == {("⊢ a",), ("⊢ b",)}


def test_a_candidate_whose_root_state_is_a_renamed_training_root_is_a_near_duplicate() -> None:
    candidates = [candidate("renamed", RENAMED_ROOT), candidate("different", DIFFERENT_ROOT)]
    assert near_training_duplicates(candidates, {ROOT}, threshold=0.7) == {"s.renamed"}
