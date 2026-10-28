from graph_trees import GraphBuilder

from lean_search.search import FailureKind, TreeRecord

CONTEXT = "x e : ℂ\nh₀ : x + e = 7\nh₁ : 2 * x + e = 3"
TARGET = "⊢ e = 11 ∧ x = -4"
ROOT = f"{CONTEXT}\n{TARGET}"
AFTER_FIRST_HAVE = f"{CONTEXT}\nh₂ : x = -4\n{TARGET}"
AFTER_SECOND_HAVE = f"{CONTEXT}\nh₂ : x = -4\nh₃ : e = 11\n{TARGET}"
E_FIRST = f"{CONTEXT}\nh₃ : e = 11\n{TARGET}"
REDUNDANT = f"{CONTEXT}\nh₄ : x + e = 7\n{TARGET}"
SIMPLIFIED = f"{CONTEXT}\nh₂ : x = -4\nh₃ : e = 11\n⊢ e = 11"

FIRST_HAVE = "have h₂ : x = -4 := by linear_combination h₁ - h₀"
SECOND_HAVE = "have h₃ : e = 11 := by linear_combination h₀ - h₂"
PROOF = f"{FIRST_HAVE}\n{SECOND_HAVE}\nexact ⟨h₃, h₂⟩"
FIRST_THEN_FAILING = (
    "have h₂ : x = -4 := by linear_combination h₁ - h₀\nhave h₃ : e = 11 := by linarith\nexact ⟨h₃, h₂⟩"
)
E_FIRST_THEN_FAILING = "have h₃ : e = 11 := by linear_combination 2 * h₀ - h₁\nexact ⟨h₃, by ring⟩\nrfl"
COPY = "have h₄ : x + e = 7 := h₀"
NO_OP = "norm_num"
ERROR = "linarith"
CONSTRUCTOR = "constructor"
THROUGH_SECOND_HAVE = (
    "have h₂ : x = -4 := by linear_combination h₁ - h₀\nhave h₃ : e = 11 := by linear_combination h₀ - h₂\nsimp"
)


def example_tree() -> TreeRecord:
    """The root of `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4` with the DESIGN's samples, one tactic per line."""
    builder = GraphBuilder(ROOT)
    root = builder.root
    proof = builder.child(root, text=PROOF, tactics=3, tactic_goals=((AFTER_FIRST_HAVE,), (AFTER_SECOND_HAVE,), ()))
    builder.child(root, AFTER_FIRST_HAVE, text=FIRST_THEN_FAILING, failure_after=1, tactic_goals=((AFTER_FIRST_HAVE,),))
    builder.child(root, E_FIRST, text=E_FIRST_THEN_FAILING, failure_after=1, tactic_goals=((E_FIRST,),))
    builder.child(root, REDUNDANT, text=COPY, tactic_goals=((REDUNDANT,),))
    builder.duplicate(root, root, text=NO_OP, tactic_goals=((ROOT,),))
    builder.failure(root, FailureKind.ERROR, text=ERROR)
    builder.unparsed(root)
    off_graph = builder.child(root, "⊢ e = 11", "⊢ x = -4", text=CONSTRUCTOR)
    builder.failure(off_graph, text="nlinarith")
    builder.child(
        root,
        SIMPLIFIED,
        text=THROUGH_SECOND_HAVE,
        tactics=3,
        tactic_goals=((AFTER_FIRST_HAVE,), (AFTER_SECOND_HAVE,), (SIMPLIFIED,)),
    )
    return builder.record(proof)
