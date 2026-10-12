import pytest

from lean_search.lean import LeanError, LeanTimeout, ProofState, ReplFailure, ReplFailureKind
from lean_search.policy.prompts import user_message
from lean_search.retrieval.annotation import (
    AnnotatedLemma,
    Applicability,
    LemmaCheck,
    TryOutcome,
    annotation_comment,
    best_check,
    lemma_lines,
    order_lemmas,
    tactic_check,
    try_outcome,
)
from lean_search.retrieval.premises import RetrievedPremise

CLOSES = LemmaCheck(Applicability.CLOSES, "exact", 0)
CLOSES_WITH_AUTOMATION = LemmaCheck(Applicability.CLOSES_WITH_AUTOMATION, "apply", 0)
APPLY_TWO = LemmaCheck(Applicability.LEAVES_GOALS, "apply", 2)
REWRITE_ONE = LemmaCheck(Applicability.LEAVES_GOALS, "rw", 1)
NO_MATCH = LemmaCheck(Applicability.NO_MATCH)
MUL_POS = "mul_pos {α : Type u_1} [Mul α] [Zero α] {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b"


def state(goal_count: int) -> ProofState:
    return ProofState("", "", (), tuple(f"⊢ goal {index}" for index in range(goal_count)), 0, 0)


def lemma(name: str, score: float, check: LemmaCheck, signature: str = "") -> AnnotatedLemma:
    return AnnotatedLemma(RetrievedPremise(name, signature or f"{name} : True", score), check)


@pytest.mark.parametrize(
    ("goals_after", "check"),
    [
        (1, LemmaCheck(Applicability.CLOSES, "apply", 0)),
        (2, LemmaCheck(Applicability.LEAVES_GOALS, "apply", 1)),
        (4, LemmaCheck(Applicability.LEAVES_GOALS, "apply", 3)),
        (0, LemmaCheck(Applicability.CLOSES, "apply", 0)),
    ],
)
def test_new_goals_replace_the_first_of_two_goals(goals_after: int, check: LemmaCheck) -> None:
    assert tactic_check("apply {name}", 2, state(goals_after)) == check


@pytest.mark.parametrize(
    "outcome",
    [LeanError("type mismatch"), LeanTimeout("heartbeats", wall_clock=False), ReplFailure(ReplFailureKind.CRASHED, "")],
)
def test_failed_tactics_do_not_match(outcome: LeanError | LeanTimeout | ReplFailure) -> None:
    assert tactic_check("rw [{name}]", 1, outcome) == NO_MATCH


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (state(1), TryOutcome.APPLIED),
        (LeanError("type mismatch"), TryOutcome.ERROR),
        (LeanTimeout("heartbeats", wall_clock=False), TryOutcome.HEARTBEAT_TIMEOUT),
        (LeanTimeout("killed", wall_clock=True), TryOutcome.WALL_CLOCK_TIMEOUT),
        (ReplFailure(ReplFailureKind.CRASHED, ""), TryOutcome.REPL_FAILURE),
    ],
)
def test_try_outcomes_are_classified(outcome: ProofState | LeanError | LeanTimeout, expected: TryOutcome) -> None:
    assert try_outcome(outcome) == expected


@pytest.mark.parametrize(
    ("checks", "best"),
    [
        ([NO_MATCH, APPLY_TWO, CLOSES], CLOSES),
        ([APPLY_TWO, REWRITE_ONE], REWRITE_ONE),
        ([REWRITE_ONE, LemmaCheck(Applicability.LEAVES_GOALS, "apply", 1)], REWRITE_ONE),
        ([APPLY_TWO, CLOSES_WITH_AUTOMATION], CLOSES_WITH_AUTOMATION),
        ([CLOSES_WITH_AUTOMATION, CLOSES], CLOSES),
        ([NO_MATCH, NO_MATCH], NO_MATCH),
        ([], NO_MATCH),
    ],
)
def test_best_check_prefers_closing_then_fewer_goals_then_the_earlier_tactic(
    checks: list[LemmaCheck], best: LemmaCheck
) -> None:
    assert best_check(checks) == best


def test_lemmas_are_ordered_by_applicability_then_retrieval_score() -> None:
    lemmas = [
        lemma("unmatched_best_score", 0.9, NO_MATCH),
        lemma("apply_low", 0.2, APPLY_TWO),
        lemma("closes_low", 0.1, CLOSES),
        lemma("rewrite_high", 0.5, REWRITE_ONE),
        lemma("unmatched_low", 0.3, NO_MATCH),
        lemma("automation_low", 0.05, CLOSES_WITH_AUTOMATION),
    ]
    assert [lemma.premise.full_name for lemma in order_lemmas(lemmas)] == [
        "closes_low",
        "automation_low",
        "rewrite_high",
        "apply_low",
        "unmatched_best_score",
        "unmatched_low",
    ]


@pytest.mark.parametrize(
    ("check", "comment"),
    [
        (CLOSES, "  -- exact: closes the goal"),
        (CLOSES_WITH_AUTOMATION, "  -- apply, then automation: closes the goal"),
        (APPLY_TWO, "  -- apply: leaves 2 goals"),
        (REWRITE_ONE, "  -- rw: leaves 1 goal"),
        (NO_MATCH, ""),
    ],
)
def test_annotation_comments(check: LemmaCheck, comment: str) -> None:
    assert annotation_comment(check) == comment


def test_lemma_lines_keep_the_best_count_with_compact_signatures() -> None:
    lemmas = [
        lemma("unmatched", 0.9, NO_MATCH),
        lemma("mul_pos", 0.5, APPLY_TWO, MUL_POS),
        lemma("dropped", 0.1, NO_MATCH),
    ]
    assert lemma_lines(lemmas, 2, 256) == (
        "mul_pos {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b  -- apply: leaves 2 goals",
        "unmatched : True",
    )


def test_prompt_lists_annotated_lemmas_after_the_proof_state() -> None:
    lines = lemma_lines([lemma("mul_pos", 0.5, APPLY_TWO, MUL_POS), lemma("pow_two", 0.4, REWRITE_ONE)], 2, 256)
    assert user_message(["a b : ℝ\nha : 0 < a\nhb : 0 < b\n⊢ 0 < a * b"], lines) == (
        "Proof state:\n```lean\na b : ℝ\nha : 0 < a\nhb : 0 < b\n⊢ 0 < a * b\n```\n\n"
        "Lemmas that may help:\n```lean\n"
        "mul_pos {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b  -- apply: leaves 2 goals\n"
        "pow_two : True  -- rw: leaves 1 goal\n"
        "```"
    )
