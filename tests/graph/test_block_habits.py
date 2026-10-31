import pytest
from graph_trees import GraphBuilder
from tactic_trees import AFTER_FIRST_HAVE, BARE_HAVE, CLAIM, CONTEXT, ROOT, TARGET, claim_tree, example_tree

from lean_search.rl.advantages import CreditMode
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.tree_summary import (
    BlockHabits,
    OpeningCount,
    binned_median,
    block_habits,
    explanation_bins,
    is_bare_have,
    is_linarith_opening,
    is_proof_have,
    opening,
    opening_head,
    summed_habits,
    tree_summary,
)
from lean_search.search import TreeRecord
from lean_search.search.graph_labels import label_graph
from lean_search.search.tactic_labels import policy_tactics

FILLER = f"{CONTEXT}\nh₂ : 0 < (1:ℝ)\n{TARGET}"
MIN_EXPANDED_NODES = RewardConfig().off_graph_min_expanded_nodes


def habits(record: TreeRecord) -> BlockHabits:
    return block_habits(record, policy_tactics(record, label_graph(record), MIN_EXPANDED_NODES))


def filler_tree() -> TreeRecord:
    builder = GraphBuilder(ROOT)
    builder.child(builder.root, FILLER, text="have h₂ : 0 < (1:ℝ) := by norm_num", tactic_goals=((FILLER,),))
    return builder.record(builder.child(builder.root, text="close"))


@pytest.mark.parametrize(
    ("block", "bare"),
    [
        ("have h₂ : x = -4", True),
        ("have : x = -4\nlinarith", True),
        ("have h₂ : x = -4 := by linarith", False),
        ("have h₂ : x = -4 := by\n  linarith", False),
        ("haveI : Fact p := ⟨hp⟩", False),
        ("nlinarith [h₀]", False),
        ("try have h₂ : x = -4", True),
        ("all_goals have h₂ : x = -4", True),
        ("norm_num <;> have h₂ : x = -4", True),
        ("haveI : Fact p", True),
        ("letI : Fact p", True),
        ("rsuffices h₂ : x = -4", True),
        ("apply have_lemma", False),
    ],
)
def test_bare_have_opening(block: str, bare: bool) -> None:
    assert is_bare_have(opening(block)) is bare


@pytest.mark.parametrize(
    ("block", "head"),
    [
        ("have h₂ : x = -4", "have"),
        ("nlinarith [sq_nonneg x]", "nlinarith"),
        ("try have h₂ : x = -4", "try"),
        ("rw [h₀] at h₁", "rw"),
        ("obtain ⟨x, hx⟩ : ∃ x, x = 1", "obtain"),
        ("· simp", "·"),
    ],
)
def test_opening_head(block: str, head: str) -> None:
    assert opening_head(opening(block)) == head


def test_openings_are_counted_by_head() -> None:
    assert habits(claim_tree()).openings == (OpeningCount("have", 1), OpeningCount("close", 1))


def test_summed_openings_merge_heads_most_frequent_first() -> None:
    first = BlockHabits(block_samples=1, openings=(OpeningCount("simp", 1),))
    second = BlockHabits(block_samples=3, openings=(OpeningCount("have", 3),))
    assert summed_habits([first, second, first]).openings == (OpeningCount("have", 3), OpeningCount("simp", 2))


def test_top_openings_are_shares_of_the_judged_samples() -> None:
    found = BlockHabits(block_samples=4, openings=(OpeningCount("have", 3), OpeningCount("simp", 1)))
    assert found.top_openings(1) == [("have", 0.75)]


def test_block_samples_count_every_judged_block() -> None:
    assert habits(claim_tree()).block_samples == 2


def test_bare_have_openings_are_counted() -> None:
    assert habits(claim_tree()).bare_have_openings == 1


@pytest.mark.parametrize(
    ("block", "proof_have"),
    [("have h₂ : x = -4 := by linarith", True), ("have h := h₀.1", True), ("have h₂ : x = -4", False), ("simp", False)],
)
def test_have_with_its_proof_opening(block: str, proof_have: bool) -> None:
    assert is_proof_have(opening(block)) is proof_have


@pytest.mark.parametrize(
    ("block", "linarith"),
    [("nlinarith [sq_nonneg x]", True), ("linarith", True), ("linarith_helper", False), ("have h : 0 < 1", False)],
)
def test_linarith_opening(block: str, linarith: bool) -> None:
    assert is_linarith_opening(opening(block)) is linarith


def test_bare_have_leaving_its_claim_open_is_an_open_claim() -> None:
    assert habits(claim_tree()).open_claims == 1


def test_claim_never_proved_is_not_counted_as_proved() -> None:
    assert habits(claim_tree()).proved_claims == 0


def test_claim_proved_below_its_child_is_counted_as_proved() -> None:
    assert habits(claim_tree(proved_below=True)).proved_claims == 1


def test_closed_form_filler_is_counted() -> None:
    assert habits(filler_tree()).closed_form_fillers == 1


def test_explanations_fall_into_ten_character_bins() -> None:
    assert explanation_bins(["x" * 25 + "\n\n```lean\nsimp\n```"]) == (0, 0, 1)


def test_binned_median_interpolates_within_its_bin() -> None:
    assert binned_median(explanation_bins(["x" * 15, "x" * 25, "x" * 35])) == pytest.approx(25.0)


def test_claim_proved_by_a_sibling_is_counted_as_proved() -> None:
    builder = GraphBuilder(ROOT)
    builder.child(builder.root, *CLAIM, text=BARE_HAVE, tactic_goals=(CLAIM,))
    sibling = builder.child(builder.root, AFTER_FIRST_HAVE, text="have h₂ : x = -4 := by linear_combination h₁ - h₀")
    assert habits(builder.record(builder.child(sibling, text="close"))).proved_claims == 1


def test_claim_left_after_swapping_and_closing_the_main_goal_is_an_open_claim() -> None:
    builder = GraphBuilder(ROOT)
    claim_goal, main_goal = CLAIM
    text = f"{BARE_HAVE}\nswap\nlinear_combination h₀ - h₂"
    goals = (CLAIM, (main_goal, claim_goal), (claim_goal,))
    builder.child(builder.root, claim_goal, text=text, tactics=3, tactic_goals=goals)
    assert habits(builder.record(builder.child(builder.root, text="close"))).open_claims == 1


def test_have_with_its_proof_openings_are_counted() -> None:
    assert habits(example_tree()).proof_have_openings == 5


def test_valid_block_tactics_count_the_flattened_tactics_of_complete_blocks() -> None:
    assert habits(example_tree()).valid_block_tactics == 3 + 1 + 1 + 1 + 3


def stop_tree() -> TreeRecord:
    builder = GraphBuilder("⊢ p")
    stop = builder.child(builder.root, "⊢ q", text="stop")
    builder.duplicate(builder.root, stop, text="stop\nsimp", tactics=2, tactic_goals=(("⊢ q",), ("⊢ q",)))
    return builder.record(builder.child(stop, text="close"))


def test_proof_graph_steps_with_goals_left_are_counted() -> None:
    assert habits(stop_tree()).proof_graph_steps == 2


def test_proof_graph_steps_a_further_tactic_follows_are_continued() -> None:
    assert habits(stop_tree()).continued_proof_graph_steps == 1


def test_summed_habits_add_the_counts_and_the_bins() -> None:
    first = BlockHabits(block_samples=2, explanation_character_bins=(1,))
    second = BlockHabits(block_samples=3, explanation_character_bins=(0, 2))
    assert summed_habits([first, second]) == BlockHabits(block_samples=5, explanation_character_bins=(1, 2))


def test_the_tree_summary_keeps_the_block_habits() -> None:
    summary = tree_summary(claim_tree(), RewardConfig(), CreditMode.PER_TACTIC, 32)
    assert summary.habits == habits(claim_tree())
