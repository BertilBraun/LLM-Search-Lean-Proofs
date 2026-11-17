"""Bounded variants of Mathlib's `nlinarith` (`[search] nlinarith_variant`, off by default; README.md, "Bounded
nlinarith"). `nlinarith` multiplies every pair of comparisons (hypotheses, hint terms, the negated goal, the squares it
finds) before linarith, so its linear program grows quadratically with them. `lean_search_nlinarith <variant> [hints]`
is linarith with nlinarith's squares and fewer products:

- `full`: every pair, as `nlinarith` (the check that the reimplementation matches it);
- `linear`: no products;
- `goal_hints`: pairs with the negated goal or a hint term as a factor;
- `degree`: pairs whose product has polynomial degree at most max(2, the negated goal's degree);
- `cap8`: the pairs among the first 8 comparisons ranked negated goal, hint terms, hypotheses, squares.

A REPL whose config names a variant adds VARIANT_DEFINITIONS to its base environment and runs every `nlinarith` and
`nlinarith [hints]` written in a tactic as that variant (`variant_tactic`); the search records the text as written.
Measured on step 1's run 4 (experiments/analysis/nlinarith_variants.py): `degree` took 71% of the time and kept 93% of
the plain calls' successes.
"""

import re
from enum import StrEnum

# A whole word `nlinarith`, not part of a name (`Linarith.nlinarithExtras`, `nlinarith_foo`), not `nlinarith!`.
_NLINARITH = re.compile(r"(?<![\w.'])nlinarith(?![\w'!?])")
# Forms with their own options keep plain `nlinarith`: `only`, a config.
_OWN_OPTIONS = re.compile(r"\s*(?:only\b|\()")


class NlinarithVariant(StrEnum):
    FULL = "full"
    LINEAR = "linear"
    GOAL_HINTS = "goal_hints"
    DEGREE = "degree"
    CAP8 = "cap8"


def variant_tactic(text: str, variant: NlinarithVariant) -> str:
    """The tactic text with every plain `nlinarith` (with or without hints) run as the variant."""

    def replaced(match: re.Match[str]) -> str:
        if _OWN_OPTIONS.match(text, match.end()):
            return match.group(0)
        return f"lean_search_nlinarith {variant.value}"

    return _NLINARITH.sub(replaced, text)


VARIANT_DEFINITIONS = """
open Lean Elab Tactic Meta Linarith in
partial def leanSearchDegree (e : Expr) : Nat :=
  match e.numeral? with
  | some _ => 0
  | none =>
    match e.getAppFnArgs with
    | (``HAdd.hAdd, #[_, _, _, _, a, b]) => max (leanSearchDegree a) (leanSearchDegree b)
    | (``HSub.hSub, #[_, _, _, _, a, b]) => max (leanSearchDegree a) (leanSearchDegree b)
    | (``HMul.hMul, #[_, _, _, _, a, b]) => leanSearchDegree a + leanSearchDegree b
    | (``HDiv.hDiv, #[_, _, _, _, a, b]) => leanSearchDegree a + leanSearchDegree b
    | (``HPow.hPow, #[_, _, _, _, a, n]) => n.numeral?.getD 1 * leanSearchDegree a
    | (``Neg.neg, #[_, _, a]) => leanSearchDegree a
    | _ => 1

open Lean Elab Tactic Meta Linarith in
def leanSearchProduct (first : Ineq × Expr) (second : Ineq × Expr) : MetaM Expr :=
  match first, second with
  | (Ineq.eq, a), (_, b) => mkAppM ``Linarith.zero_mul_eq #[a, b]
  | (_, a), (Ineq.eq, b) => mkAppM ``Linarith.mul_zero_eq #[a, b]
  | (Ineq.lt, a), (Ineq.lt, b) => mkAppM ``mul_pos_of_neg_of_neg #[a, b]
  | (Ineq.lt, a), (Ineq.le, b) => do
      let a ← mkAppM ``le_of_lt #[a]
      mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]
  | (Ineq.le, a), (Ineq.lt, b) => do
      let b ← mkAppM ``le_of_lt #[b]
      mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]
  | (Ineq.le, a), (Ineq.le, b) => mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]

open Lean Elab Tactic Meta Linarith in
def leanSearchTryProduct (first : Ineq × Expr) (second : Ineq × Expr) : MetaM (Option Expr) := do
  try
    return some (← leanSearchProduct first second)
  catch _ =>
    return none

open Lean Elab Tactic Meta Linarith in
def leanSearchParse (proof : Expr) : MetaM (Ineq × Nat) := do
  try
    let (strength, term) ← parseCompAndExpr (← inferType proof)
    return (strength, leanSearchDegree term)
  catch _ =>
    return (Ineq.lt, 1)

structure LeanSearchComparison where
  strength : Linarith.Ineq
  proof : Lean.Expr
  degree : Nat
  rank : Nat
  deriving Inhabited

open Lean Elab Tactic Meta Linarith in
def leanSearchProducts (variant : Name) (hints : List Expr) : GlobalPreprocessor where
  name := "lean_search bounded products"
  transform ls := do
    let squares ← ls.foldrM (fun h s => do findSquares s (← instantiateMVars (← inferType h))) Lean.HashSet.empty
    let squareProofs ← squares.foldM (fun proofs (⟨e, isSquare⟩ : Expr × Bool) =>
      ((do
        let p ← mkAppM (if isSquare then ``sq_nonneg else ``mul_self_nonneg) #[e]
        pure (p :: proofs)) <|> pure proofs)) ([] : List Expr)
    let squareProofs ← compWithZero.globalize.transform squareProofs
    let goal? := (← getLCtx).lastDecl.map (·.fvarId)
    let mut comparisons : Array LeanSearchComparison := #[]
    for (proof, index) in (squareProofs ++ ls).zip (List.range (squareProofs.length + ls.length)) do
      let (strength, degree) ← leanSearchParse proof
      let isGoal := goal?.any proof.containsFVar
      let isHint := hints.any (·.occurs proof)
      let group := if isGoal then 0 else if isHint then 1 else if index < squareProofs.length then 3 else 2
      comparisons := comparisons.push ⟨strength, proof, degree, group * 100000 + index⟩
    let goalDegree := comparisons.foldl (fun d c => if c.rank < 100000 then max d c.degree else d) 2
    let ranks := (comparisons.map (·.rank)).qsort (· < ·)
    let capRank := if ranks.size ≥ 8 then ranks[7]! else 1000000000
    let keep (a b : LeanSearchComparison) : Bool :=
      match variant with
      | `full => true
      | `linear => false
      | `goal_hints => a.rank < 200000 || b.rank < 200000
      | `degree => a.degree + b.degree ≤ goalDegree
      | `cap8 => a.rank ≤ capRank && b.rank ≤ capRank
      | _ => false
    let mut products : Array Expr := #[]
    for i in [:comparisons.size] do
      for j in [i:comparisons.size] do
        let a := comparisons[i]!
        let b := comparisons[j]!
        if keep a b then
          if let some product ← leanSearchTryProduct (a.strength, a.proof) (b.strength, b.proof) then
            products := products.push product
    let productProofs ← compWithZero.globalize.transform products.toList
    return squareProofs ++ ls ++ productProofs

syntax (name := leanSearchNlinarith) "lean_search_nlinarith " ident (" [" term,* "]")? : tactic

open Lean Elab Tactic Meta Linarith in
elab_rules : tactic
  | `(tactic| lean_search_nlinarith $variant:ident $[[$args,*]]?) => withMainContext do
    let args ← ((args.map (Syntax.TSepArray.getElems)).getD {}).mapM (elabLinarithArg `nlinarith)
    let extras : GlobalBranchingPreprocessor := leanSearchProducts variant.getId args.toList
    let config : LinarithConfig := { preprocessors := some (defaultPreprocessors ++ [extras]) }
    commitIfNoEx do liftMetaFinishingTactic <| Linarith.linarith false args.toList config
"""
