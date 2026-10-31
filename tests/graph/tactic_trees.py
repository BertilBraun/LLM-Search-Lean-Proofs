import dataclasses

from graph_trees import GraphBuilder

from lean_search.lean.text import TacticPiece
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


BARE_HAVE = "have h₂ : x = -4"
CLAIM = (f"{CONTEXT}\n⊢ x = -4", AFTER_FIRST_HAVE)


def claim_tree(*, proved_below: bool = False, on_proof_graph: bool = False) -> TreeRecord:
    """The root, a policy sample leaving the claim `x = -4` as a new goal, and a proof elsewhere or through it."""
    builder = GraphBuilder(ROOT)
    claim = builder.child(builder.root, *CLAIM, text=BARE_HAVE, tactic_goals=(CLAIM,))
    if proved_below or on_proof_graph:
        claimed = builder.child(claim, AFTER_FIRST_HAVE, text="linear_combination h₁ - h₀")
        if on_proof_graph:
            return builder.record(builder.child(claimed, text="close"))
    return builder.record(builder.child(builder.root, text="close"))


def with_pieces(record: TreeRecord, pieces: dict[str, list[str]]) -> TreeRecord:
    """Executed tactics as the search records them (flattened pieces), which GraphBuilder leaves out."""
    edges = []
    for edge in record.edges:
        if edge.text in pieces:
            executed = tuple(TacticPiece(text, 0, 0) for text in pieces[edge.text])
            edge = dataclasses.replace(edge, executed_tactics=executed)
        edges.append(edge)
    return dataclasses.replace(record, edges=tuple(edges))


# Attempts at the claim `x = -4`, which nothing in `open_claims_tree` proves.
ERRORING_HAVE = "have h₂ : x = -4 := by\n  nlinarith"
OPEN_ENDED_HAVE = "have h₂ : x = -4 := by\n  field_simp"
PARTIAL = f"{CONTEXT}\n⊢ x + 4 = 0"
# A failing attempt at `e = 11`, which a sibling proves under another name.
PROVABLE_CLAIM = (f"{CONTEXT}\n⊢ e = 11", f"{CONTEXT}\nh₉ : e = 11\n{TARGET}")
PROVABLE_ATTEMPT = "have h₉ : e = 11 := by\n  nlinarith"
SIBLING_PROOF = "have h₃ : e = 11 := by linear_combination 2 * h₀ - h₁"


def open_claims_tree() -> TreeRecord:
    """Review U's findings 1 and 2 in one group at the root, flattened as the search runs them: the invented claim
    `x = -4` with an erroring nlinarith, left open by a valid field_simp, and bare; a failing attempt at `e = 11`; the
    sibling proving `e = 11` and its closer."""
    builder = GraphBuilder(ROOT)
    claim = builder.child(builder.root, *CLAIM, text=ERRORING_HAVE, failure_after=1, tactic_goals=(CLAIM,))
    builder.child(
        builder.root,
        PARTIAL,
        AFTER_FIRST_HAVE,
        text=OPEN_ENDED_HAVE,
        tactics=2,
        tactic_goals=(CLAIM, (PARTIAL, AFTER_FIRST_HAVE)),
    )
    builder.duplicate(builder.root, claim, text=BARE_HAVE, tactic_goals=(CLAIM,))
    builder.child(builder.root, *PROVABLE_CLAIM, text=PROVABLE_ATTEMPT, failure_after=1, tactic_goals=(PROVABLE_CLAIM,))
    sibling = builder.child(builder.root, E_FIRST, text=SIBLING_PROOF)
    record = builder.record(builder.child(sibling, text="close"))
    pieces = {
        ERRORING_HAVE: ["have h₂ : x = -4", "nlinarith"],
        OPEN_ENDED_HAVE: ["have h₂ : x = -4", "field_simp"],
        PROVABLE_ATTEMPT: ["have h₉ : e = 11", "nlinarith"],
    }
    return with_pieces(record, pieces)
