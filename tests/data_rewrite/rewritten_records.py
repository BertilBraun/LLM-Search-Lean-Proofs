"""A small rewrite run's records: a three-tactic flat proof with `h₀` renamed to `hx_pos`, and a visible example."""

from lean_search.corpora.records import DataSplit
from lean_search.data_rewrite.dataset import TokenCounts
from lean_search.data_rewrite.naming import NameChange, NameSource, renamed_text
from lean_search.data_rewrite.records import (
    ExampleStatus,
    NamedExample,
    NamedProof,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin

CHANGES = (NameChange("h₀", "hx_pos", NameSource.RULES),)
TACTICS = ("have h₁ : 0 < x + 1", "linarith [h₀]", "nlinarith [h₀, h₁]")
GOALS = (
    ("x : ℝ\nh₀ : 0 < x\n⊢ 0 < x ^ 2 + 1",),
    ("case h₁\nx : ℝ\nh₀ : 0 < x\n⊢ 0 < x + 1", "x : ℝ\nh₀ : 0 < x\nh₁ : 0 < x + 1\n⊢ 0 < x ^ 2 + 1"),
    ("x : ℝ\nh₀ : 0 < x\nh₁ : 0 < x + 1\n⊢ 0 < x ^ 2 + 1",),
    (),
)
COUNTS = TokenCounts(prompt=lambda goals: sum(len(goal) for goal in goals), completion=len)


def renamed_goals(goals: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(renamed_text(goal, CHANGES) for goal in state) for state in goals)


def proof(
    identifier: str,
    split: DataSplit = DataSplit.TRAIN,
    status: ProofStatus = ProofStatus.KEPT,
    named_status: NamedStatus = NamedStatus.RENAMED,
) -> RewrittenProof:
    named = NamedProof(
        named_status,
        CHANGES,
        (),
        "",
        tuple(renamed_text(tactic, CHANGES) for tactic in TACTICS),
        renamed_goals(GOALS),
    )
    return RewrittenProof(
        source="test",
        proof_identifier=identifier,
        split=split,
        header="",
        formal_statement=f"theorem {identifier.replace('/', '_')} (x : ℝ) (h₀ : 0 < x) : 0 < x ^ 2 + 1 := by",
        original_tactics=2,
        flattened=True,
        status=status,
        message="",
        tactics=TACTICS,
        goals=GOALS,
        named=named,
        lean_seconds=1.0,
    )


def example(
    split: DataSplit = DataSplit.TRAIN,
    named_status: NamedStatus = NamedStatus.RENAMED,
    reasoning: str = "Since h₀ gives 0 < x, the square plus one is positive.",
    visible: bool = True,
) -> RewrittenExample:
    original = ReasoningExample(
        "test",
        "test/reasoning",
        0,
        GOALS[0],
        "have h₁ : 0 < x + 1 := by\n  linarith [h₀]\nnlinarith [h₀, h₁]",
        reasoning,
        "",
        ReasoningOrigin.SAMPLED,
        visible=visible,
    )
    named = NamedExample(
        named_status,
        CHANGES,
        (),
        renamed_goals(GOALS)[0],
        renamed_text("have h₁ : 0 < x + 1\nlinarith [h₀]\nnlinarith [h₀, h₁]", CHANGES),
        renamed_text(reasoning, CHANGES),
        (),
    )
    return RewrittenExample(
        original,
        split,
        ExampleStatus.KEPT,
        "",
        True,
        "have h₁ : 0 < x + 1\nlinarith [h₀]\nnlinarith [h₀, h₁]",
        (),
        named,
        1.0,
    )
