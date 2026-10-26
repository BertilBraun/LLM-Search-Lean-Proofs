import pytest

from lean_search.lean.plans import (
    NO_GOALS_MESSAGE,
    OUTSIDE_MESSAGE,
    UNSOLVED_MESSAGE,
    FocusSegment,
    Proceed,
    Rejection,
    SegmentKind,
    Stop,
    TacticPlan,
    flatten_proof,
    plain_plan,
    plan_block,
    segment_verdict,
)


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("have h : 0 < 2 := by\n  norm_num\nlinarith", ["have h : 0 < 2", "norm_num", "linarith"]),
        (
            "have h : a = 2 := by simp [h₀] <;> linarith\nexact h",
            ["have h : a = 2", "simp [h₀] <;> linarith", "exact h"],
        ),
        ("have : a = 2 := by\n  rw [h₀]\n  rfl", ["have : a = 2", "rw [h₀]", "rfl"]),
        ("have h : a +\n    b = 5 := by\n  omega", ["have h : a +\n    b = 5", "omega"]),
        (
            "obtain ⟨x, hx⟩ : ∃ x, x = 2 := by\n  exact ⟨2, rfl⟩\nsimp",
            ["obtain ⟨x, hx⟩ : ∃ x, x = 2", "exact ⟨2, rfl⟩", "simp"],
        ),
        (
            "have h : a = 2 := by\n  have h' : b = 3 := by\n    exact h₁\n  simp\nomega",
            ["have h : a = 2", "have h' : b = 3", "exact h₁", "simp", "omega"],
        ),
        (
            "  have h : a = 2 := by\n    rw [h₀]\n    -- note\n    rfl\n  simp",
            ["have h : a = 2", "rw [h₀]", "rfl", "simp"],
        ),
    ],
)
def test_nested_have_proofs_become_top_level_steps(block: str, expected: list[str]) -> None:
    assert list(plan_block(block).texts) == expected


@pytest.mark.parametrize(
    "block",
    [
        "have h (x : ℕ) : x = x := by\n  rfl",
        "have h : _ = 2 := by\n  rfl",
        "have h : ?a = 2 := by\n  rfl",
        "have h : a = 2 := by\n  all_goals simp",
        "have h : a = 2 := by\n  repeat rw [h₀]",
        "have h : a = 2 := by simp\n  linarith",
        "have h : a = 2 := h₀",
        "have ⟨x, hx⟩ := h",
        "have h : a = 2 := by\n  simp\n<;> linarith",
        "exact «x»",
    ],
)
def test_ambiguous_or_unsafe_blocks_stay_unchanged(block: str) -> None:
    assert plan_block(block) == plain_plan(block)


def test_flattened_have_proof_is_a_segment_of_its_nested_tactics() -> None:
    plan = plan_block("have h : 0 < 2 := by\n  norm_num\n  done\nlinarith")
    assert plan.segments == (FocusSegment(SegmentKind.HAVE, 1, 2),)


def test_bullet_with_a_nested_have_is_dissolved_into_its_body() -> None:
    plan = plan_block("constructor\n· have h : a = 2 := by\n    simp\n  exact h\n· omega")
    assert list(plan.texts) == ["constructor", "have h : a = 2", "simp", "exact h", "· omega"]


def test_dissolved_bullet_is_a_segment_around_the_have_segment() -> None:
    plan = plan_block("constructor\n· have h : a = 2 := by\n    simp\n  exact h\n· omega")
    assert plan.segments == (FocusSegment(SegmentKind.HAVE, 2, 2), FocusSegment(SegmentKind.BULLET, 1, 3))


def test_bullet_without_a_nested_have_stays_one_step() -> None:
    assert list(plan_block("constructor\n· simp\n  ring\n· omega").texts) == [
        "constructor",
        "· simp\n  ring",
        "· omega",
    ]


def test_opener_span_covers_the_have_up_to_by() -> None:
    block = "have h : 0 < 2 := by\n  norm_num\nlinarith"
    opener = plan_block(block).tactics[0]
    assert block[opener.start : opener.end] == "have h : 0 < 2 := by"


@pytest.mark.parametrize(
    "block",
    [
        "have h : 0 < 2 := by\n  norm_num\nlinarith",
        "constructor\n· have h : a = 2 := by\n    simp [x,\n      y]\n  exact h\n· omega",
        "  have h : a = 2 := by simp <;> ring\n  exact h",
    ],
)
def test_nested_tactic_spans_point_at_their_source(block: str) -> None:
    plan = plan_block(block)
    nested = [tactic for tactic in plan.tactics if not tactic.text.startswith("have")]
    assert all(" ".join(block[tactic.start : tactic.end].split()) == " ".join(tactic.text.split()) for tactic in nested)


def test_plain_plan_keeps_the_top_level_pieces() -> None:
    assert list(plan_block("have h : 0 < 2 := by\n  norm_num", flatten=False).texts) == [
        "have h : 0 < 2 := by\n  norm_num"
    ]


def test_flatten_proof_writes_the_flattened_steps() -> None:
    assert flatten_proof("intro x\nhave h : x = x := by\n  rfl\nexact h") == "intro x\nhave h : x = x\nrfl\nexact h"


HAVE_PLAN = plan_block("have h : a = 2 := by\n  simp\n  try ring\n  norm_num\nexact h")
BULLET_PLAN = plan_block("· have h : a = 2 := by\n    simp\n  exact h")


@pytest.mark.parametrize(
    ("plan", "goals_before", "index", "goals_after", "expected"),
    [
        # Two goals at the opener (the have's goal first), one before it.
        (HAVE_PLAN, {0: 1, 1: 2}, 1, 2, Proceed(2)),
        (HAVE_PLAN, {0: 1, 1: 2, 2: 2, 3: 2}, 3, 1, Proceed(4)),
        (HAVE_PLAN, {0: 1, 1: 2, 2: 2, 3: 2}, 3, 2, Stop(UNSOLVED_MESSAGE, keep_state=True, applied_until=4)),
        (HAVE_PLAN, {0: 1, 1: 2, 2: 2}, 2, 1, Stop(NO_GOALS_MESSAGE, keep_state=True, applied_until=3)),
        (HAVE_PLAN, {0: 1, 1: 2}, 1, 0, Stop(OUTSIDE_MESSAGE, keep_state=False, applied_until=1)),
        (BULLET_PLAN, {0: 2, 1: 3, 2: 2}, 2, 1, Proceed(3)),
        (BULLET_PLAN, {0: 2, 1: 3, 2: 2}, 2, 2, Stop(UNSOLVED_MESSAGE, keep_state=True, applied_until=3)),
    ],
)
def test_segment_verdict(
    plan: TacticPlan, goals_before: dict[int, int], index: int, goals_after: int, expected: Proceed | Stop
) -> None:
    assert segment_verdict(plan, goals_before, index, goals_after) == expected


def test_closed_nested_proof_skips_its_trailing_try() -> None:
    plan = plan_block("have h : a = 2 := by\n  simp\n  try ring\nexact h")
    assert segment_verdict(plan, {0: 1, 1: 2}, 1, 1) == Proceed(3)


def test_merging_inside_a_segment_shrinks_it() -> None:
    merged = plan_block("have h : a = 2 := by\n  rw\n  simp\n  ring\nexact h").merged(1)
    assert merged is not None and merged.segments == (FocusSegment(SegmentKind.HAVE, 1, 2),)


def test_merging_across_a_segment_boundary_is_refused() -> None:
    assert plan_block("have h : a = 2 := by\n  simp\nexact h").merged(1) is None


def test_merging_moves_the_rejection_with_its_tactic() -> None:
    plan = plain_plan("rw [h] at\nh₂\nsimp").rejecting(Rejection(2, "unknown"))
    merged = plan.merged(0)
    assert merged is not None and merged.rejection == Rejection(1, "unknown")
