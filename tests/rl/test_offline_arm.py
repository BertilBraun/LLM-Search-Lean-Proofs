from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.corpora.pipeline import PROOFS_PER_STATEMENT, statement_key  # noqa: E402
from lean_search.corpora.records import StatementRecord  # noqa: E402
from lean_search.expert_iteration.known_proofs import VerifiedStatement  # noqa: E402
from lean_search.rl.offline_arm import (  # noqa: E402
    CorpusProof,
    ExampleTokens,
    Exclusion,
    MatchedConfig,
    ProofExamples,
    ProofTarget,
    Subset,
    band_sizes,
    held_out_references,
    load_offline_arm_config,
    matched_sample,
    pool_selection,
    recovered_candidates,
    run_name,
    subset_epochs,
)
from lean_search.training.sft_data import SftExample  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY / "experiments/configs/grpo/followup/offline/offline_arm.toml"
EDGES = (500, 1000, 1500, 2000, 3000, 4500)
HEADER = "import Mathlib"
STATEMENTS = (
    "theorem alpha (x : ℕ) (h : x = 2) : x + x = 4 := by",
    "theorem beta (a b : ℝ) (h₀ : 0 < a) (h₁ : a < b) : a ^ 2 < b ^ 2 := by",
    "theorem gamma (n : ℤ) (h : n % 4 = 3) : n ^ 2 % 4 = 1 := by",
    "theorem delta (f : ℕ → ℕ) (h : ∀ k, f (k + 1) > f k) : f 3 > f 0 := by",
)


def statement(index: int) -> StatementRecord:
    return StatementRecord("goedel_sft_v2", f"s{index}", HEADER, STATEMENTS[index], "", "pinned")


ROOTS = (
    "x : ℕ\nh : x = 2\n⊢ x + x = 4",
    "a b : ℝ\nh₀ : 0 < a\nh₁ : a < b\n⊢ a ^ 2 < b ^ 2",
    "n : ℤ\nh : n % 4 = 3\n⊢ n ^ 2 % 4 = 1",
    "f : ℕ → ℕ\nh : ∀ (k : ℕ), f (k + 1) > f k\n⊢ f 3 > f 0",
)


def verified(index: int, usable: bool = True, roots: tuple[str, ...] = ()) -> VerifiedStatement:
    goals = roots or (ROOTS[index],)
    return VerifiedStatement(
        statement(index), ("goedel_sft_v2",), usable, "goedel_sft_v2", 3, 100, goals, False, False, (), 1.0
    )


def references(held_out: tuple[int, ...] = (), states: tuple[str, ...] = (), pool: tuple[VerifiedStatement, ...] = ()):
    return held_out_references([statement(index) for index in held_out], states, pool)


def test_unusable_statement_is_dropped_as_unusable() -> None:
    selection = pool_selection([verified(0, usable=False)], references(), 0.7)
    assert selection.dropped[Exclusion.UNUSABLE] == 1


def test_statement_of_a_held_out_set_is_dropped_as_held_out() -> None:
    selection = pool_selection([verified(1)], references(held_out=(1,)), 0.7)
    assert selection.dropped[Exclusion.HELD_OUT_SET] == 1


def test_statement_of_a_held_out_state_is_dropped_up_to_whitespace() -> None:
    state_statement = STATEMENTS[2].replace(" : ", "  :  ")
    selection = pool_selection([verified(2)], references(states=(state_statement,)), 0.7)
    assert selection.dropped[Exclusion.HELD_OUT_STATE] == 1


def test_statement_renamed_from_a_held_out_one_is_a_near_duplicate() -> None:
    renamed = StatementRecord("leanabell_sft", "other", HEADER, STATEMENTS[1].replace("beta", "beta_copy"), "", "")
    candidate = VerifiedStatement(renamed, (), True, "leanabell_sft", 3, 100, ("⊢ other",), False, False, (), 1.0)
    selection = pool_selection([candidate], references(held_out=(1,)), 0.7)
    assert selection.dropped[Exclusion.NEAR_HELD_OUT_STATEMENT] == 1


def test_statement_with_a_held_out_root_state_is_a_near_duplicate() -> None:
    root = ("x y : ℝ\nh : 0 < x\n⊢ x * y ≤ x ^ 2 + y ^ 2",)
    held = verified(3, roots=root)
    candidate = verified(0, roots=root)
    selection = pool_selection([candidate], references(held_out=(3,), pool=(held,)), 0.7)
    assert selection.dropped[Exclusion.NEAR_HELD_OUT_ROOT] == 1


def test_unrelated_usable_statements_are_kept() -> None:
    selection = pool_selection([verified(0), verified(2)], references(held_out=(1,), pool=(verified(1),)), 0.7)
    assert [record.statement.identifier for record in selection.kept] == ["s0", "s2"]


KEY = "statementkey"
TARGET = {KEY: ProofTarget("goedel_sft_v2", 2, 9)}


def proof(identifier: str, text: str, tactics: int = 2, source: str = "goedel_sft_v2", key: str = KEY) -> CorpusProof:
    return CorpusProof(key, source, f"{source}/{identifier}", text, tactics)


def test_proof_of_the_recorded_length_is_recovered() -> None:
    found = recovered_candidates(TARGET, [proof("0/1", "simp\nring"), proof("0/2", "norm_num\nlinarith")])
    assert found[KEY] == ("simp\nring",)


def test_proof_from_another_source_is_not_a_candidate() -> None:
    found = recovered_candidates(TARGET, [proof("0/1", "simp\nring", source="leanabell_sft")])
    assert KEY not in found


def test_whitespace_duplicates_keep_the_text_of_the_smallest_identifier() -> None:
    # "0/10" sorts before "0/9" as phase 2's identifiers do (as strings).
    found = recovered_candidates(TARGET, [proof("0/9", "simp\n ring"), proof("0/10", "simp\nring")])
    assert found[KEY] == ("simp\nring",)


def test_matching_proofs_beyond_phase_twos_cap_are_not_candidates() -> None:
    texts = [f"tac{number}\nring" for number in range(10)]
    found = recovered_candidates(
        {KEY: ProofTarget("goedel_sft_v2", 2, 9)}, [proof(f"0/{n}", text) for n, text in enumerate(texts)]
    )
    assert len(found[KEY]) == PROOFS_PER_STATEMENT


def test_several_matching_proofs_come_in_identifier_order() -> None:
    target = {KEY: ProofTarget("goedel_sft_v2", 2, 8)}
    found = recovered_candidates(target, [proof("1/0", "bbbb\nccc"), proof("0/5", "aaaa\nccc")])
    assert found[KEY] == ("aaaa\nccc", "bbbb\nccc")


def test_statement_key_ignores_whitespace() -> None:
    assert statement_key(STATEMENTS[0]) == statement_key(STATEMENTS[0].replace(" : ", "  :\n  "))


def proof_examples(name: str, characters: int, completion: int, examples: int = 1) -> ProofExamples:
    return ProofExamples(
        name,
        characters,
        tuple(SftExample("offline_arm", name, index, ("⊢ g",), "simp") for index in range(examples)),
        tuple(ExampleTokens(10, completion) for _ in range(examples)),
    )


MATCHED = MatchedConfig(completion_tokens=600, band_edges=EDGES, seed="test")


def test_matched_sample_takes_equal_proofs_per_band() -> None:
    proofs = [proof_examples(f"p{band}_{n}", low + 1, 50) for band, low in enumerate((0, *EDGES)) for n in range(5)]
    sizes = band_sizes(matched_sample(proofs, MATCHED), EDGES)
    assert [size.proofs for size in sizes] == [2, 2, 2, 2, 2, 1, 1]


def test_matched_sample_stops_once_the_completion_tokens_reach_the_target() -> None:
    proofs = [proof_examples(f"p{band}_{n}", low + 1, 50) for band, low in enumerate((0, *EDGES)) for n in range(5)]
    assert sum(proof.completion_tokens for proof in matched_sample(proofs, MATCHED)) == 600


def test_matched_sample_keeps_drawing_from_bands_that_have_proofs_left() -> None:
    proofs = [proof_examples("short", 10, 50), *(proof_examples(f"long{n}", 5000, 50) for n in range(20))]
    sizes = band_sizes(matched_sample(proofs, MATCHED), EDGES)
    assert (sizes[0].proofs, sizes[-1].proofs) == (1, 11)


def test_matched_sample_takes_everything_when_the_pool_is_smaller_than_the_target() -> None:
    proofs = [proof_examples(f"p{n}", 700, 50) for n in range(3)]
    assert len(matched_sample(proofs, MATCHED)) == 3


def test_matched_sample_is_the_same_whatever_the_input_order() -> None:
    proofs = [proof_examples(f"p{band}_{n}", low + 1, 50) for band, low in enumerate((0, *EDGES)) for n in range(5)]
    assert matched_sample(proofs, MATCHED) == matched_sample(list(reversed(proofs)), MATCHED)


def test_band_sizes_count_examples_and_tokens() -> None:
    sizes = band_sizes([proof_examples("p", 1200, 30, examples=3)], EDGES)
    assert (sizes[2].band, sizes[2].examples, sizes[2].prompt_tokens, sizes[2].completion_tokens) == (
        "1000-1499",
        3,
        30,
        90,
    )


def test_the_shipped_config_loads_with_two_learning_rates() -> None:
    assert load_offline_arm_config(CONFIG).learning_rates == ("5e-5", "1e-4")


def test_run_names_carry_subset_and_rate() -> None:
    assert run_name(load_offline_arm_config(CONFIG), Subset.MATCHED, "1e-4") == "offline_arm_matched_1e-4"


@pytest.mark.parametrize(("subset", "epochs"), [(Subset.MATCHED, 4), (Subset.POOL, 1)])
def test_the_matched_subset_trains_four_epochs_and_the_pool_one(subset: Subset, epochs: int) -> None:
    assert subset_epochs(load_offline_arm_config(CONFIG), subset) == epochs
