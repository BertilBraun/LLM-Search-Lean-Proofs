import tomllib
from pathlib import Path

import pytest

from lean_search.corpora.records import DataSplit, ProofRecord
from lean_search.data_rewrite.dataset import BuildConfig, NameVariant
from lean_search.data_rewrite.naming import NameChange, NameSource, NamingConfig, RuleBasedNamer
from lean_search.data_rewrite.replay import has_nested_have_proof, tactic_plan
from lean_search.data_rewrite.rewrite import RewriteConfig, reasoning_items, select_proofs
from lean_search.data_rewrite.statement_renaming import proof_of_original, rename_statements
from lean_search.lean.plans import plan_block
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "data_rewrite"


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("have h : a = 2 := by\n  simp\nlinarith", False),
        ("have h (x : ℕ) : x = x := by\n  rfl", True),
        ("have h : a = 2 := by\n  all_goals simp", True),
        ("have h : a = 2 := h₀\nexact h", False),
        ("have h : a = c := calc a = b := by ring\n  _ = c := by simp", False),
        ("exact (by simp : a = 2)", False),
    ],
)
def test_nested_have_proofs_left_by_flattening_are_found(block: str, expected: bool) -> None:
    assert has_nested_have_proof(plan_block(block).texts) == expected


def test_tactic_plan_keeps_tactics_as_given() -> None:
    assert tactic_plan(["intro x", "have h : x = x := by\n  rfl"]).texts == ("intro x", "have h : x = x := by\n  rfl")


def record(identifier: str) -> ProofRecord:
    return ProofRecord("test", identifier, identifier, "", f"theorem t{identifier} : True := by", "trivial", "")


def test_proof_selection_takes_the_listed_proofs() -> None:
    selected = select_proofs([record("a"), record("b"), record("c")], {"a", "c"}, 0, "seed")
    assert sorted(entry.identifier for entry in selected) == ["a", "c"]


def test_proof_selection_is_capped_in_a_fixed_order() -> None:
    records = [record(str(index)) for index in range(20)]
    assert select_proofs(records, None, 5, "seed") == select_proofs(list(reversed(records)), None, 5, "seed")


def test_reasoning_items_skip_replay_examples() -> None:
    reasoning = ReasoningExample("s", "p", 0, ("⊢ True",), "trivial", "Trivial.", "", ReasoningOrigin.SAMPLED, True)
    replay = ReasoningExample("s", "p", 0, ("⊢ True",), "trivial", None, "", ReasoningOrigin.REPLAY)
    items = reasoning_items([reasoning, replay], [reasoning])
    assert [(item.example.reasoning, item.split) for item in items] == [
        ("Trivial.", DataSplit.TRAIN),
        ("Trivial.", DataSplit.VALIDATION),
    ]


async def test_statement_renaming_renames_binders_and_references() -> None:
    statement = "theorem t (x : ℝ) (h₀ : 0 < x) (h₁ : f h₀ = 1) : x > 0 := by"
    (renaming,) = await rename_statements([statement], RuleBasedNamer(NamingConfig()), NamingConfig())
    assert renaming.statement == "theorem t (x : ℝ) (hx_pos : 0 < x) (h_fact : f hx_pos = 1) : x > 0 := by"


async def test_statement_without_numbered_hypotheses_is_unchanged() -> None:
    statement = "theorem t (x : ℝ) (hx : 0 < x) : x > 0 := by"
    (renaming,) = await rename_statements([statement], RuleBasedNamer(NamingConfig()), NamingConfig())
    assert (renaming.statement, renaming.changes) == (statement, ())


def test_proof_of_original_renames_first() -> None:
    changes = (NameChange("h₀", "hx_pos", NameSource.MODEL), NameChange("h₁", "h_sum", NameSource.RULES))
    assert proof_of_original(changes, "linarith [hx_pos]") == "rename' h₀ => hx_pos, h₁ => h_sum\nlinarith [hx_pos]"


def test_rewrite_config_loads() -> None:
    text = (CONFIGS / "rewrite_visible_student_v2.toml").read_text(encoding="utf-8")
    assert from_json_object(RewriteConfig, tomllib.loads(text)).namer.model == "namer"


@pytest.mark.parametrize(
    ("name", "variant"), [("build_numbered", NameVariant.NUMBERED), ("build_named", NameVariant.NAMED)]
)
def test_build_configs_load(name: str, variant: NameVariant) -> None:
    text = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    assert from_json_object(BuildConfig, tomllib.loads(text)).variant is variant


def test_build_configs_differ_only_in_the_variant() -> None:
    numbered, named = (
        from_json_object(BuildConfig, tomllib.loads((CONFIGS / f"{name}.toml").read_text(encoding="utf-8")))
        for name in ("build_numbered", "build_named")
    )
    assert numbered == BuildConfig(**{**vars(named), "variant": NameVariant.NUMBERED})


@pytest.mark.parametrize("name", ["sft_numbered", "sft_named"])
def test_sft_configs_load(name: str) -> None:
    pytest.importorskip("torch")
    from lean_search.training.sft import SftConfig

    text = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    assert from_json_object(SftConfig, tomllib.loads(text)).data.startswith("visible_student_v3_")
