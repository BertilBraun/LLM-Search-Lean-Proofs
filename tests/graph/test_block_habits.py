import pytest
from graph_trees import GraphBuilder
from tactic_trees import CONTEXT, ROOT, TARGET, claim_tree

from lean_search.rl.advantages import CreditMode
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.tree_summary import binned_median, block_habits, explanation_bins, is_bare_have, tree_summary
from lean_search.search import TreeRecord

FILLER = f"{CONTEXT}\nh₂ : 0 < (1:ℝ)\n{TARGET}"


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
    ],
)
def test_bare_have_opening(block: str, bare: bool) -> None:
    assert is_bare_have(block) is bare


def test_block_samples_count_every_judged_block() -> None:
    assert block_habits(claim_tree()).block_samples == 2


def test_bare_have_openings_are_counted() -> None:
    assert block_habits(claim_tree()).bare_have_openings == 1


def test_bare_have_leaving_its_claim_open_is_an_open_claim() -> None:
    assert block_habits(claim_tree()).open_claims == 1


def test_claim_never_proved_is_not_counted_as_proved() -> None:
    assert block_habits(claim_tree()).proved_claims == 0


def test_claim_proved_below_its_child_is_counted_as_proved() -> None:
    assert block_habits(claim_tree(proved_below=True)).proved_claims == 1


def test_closed_form_filler_is_counted() -> None:
    assert block_habits(filler_tree()).closed_form_fillers == 1


def test_explanations_fall_into_ten_character_bins() -> None:
    assert explanation_bins(["x" * 25 + "\n\n```lean\nsimp\n```"]) == (0, 0, 1)


def test_binned_median_interpolates_within_its_bin() -> None:
    assert binned_median(explanation_bins(["x" * 15, "x" * 25, "x" * 35])) == pytest.approx(25.0)


def test_the_tree_summary_keeps_the_block_habits() -> None:
    summary = tree_summary(claim_tree(), RewardConfig(), CreditMode.PER_TACTIC, 32)
    assert summary.habits == block_habits(claim_tree())
