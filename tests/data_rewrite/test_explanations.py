import dataclasses
import tomllib
from pathlib import Path

import pytest
from rewritten_records import CHANGES, COUNTS, example, proof

from lean_search.data_rewrite.chunks import ChunkLength
from lean_search.data_rewrite.dataset import BuildConfig, ChunkPosition, NameVariant, plan_chunks
from lean_search.data_rewrite.explanations import (
    AcceptedExplanation,
    ExplainConfig,
    ExplainedBlock,
    ExplanationBounds,
    ExplanationRequest,
    FewShotConfig,
    TeacherReply,
    explanation_messages,
    explanation_record,
    explanation_request,
    few_shot_explanations,
    judge_explanation,
)
from lean_search.data_rewrite.naming import renamed_text
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExplanationOutcome,
    ExplanationRejection,
    NamedStatus,
    RejectedExplanation,
    RewrittenExample,
)
from lean_search.data_rewrite.statistics import explanation_statistics
from lean_search.lean.text import split_tactics
from lean_search.search.records import from_json_object

CONFIGS = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "data_rewrite"
BOUNDS = ExplanationBounds()
BLOCK = "nlinarith [sq_nonneg (x - 1), sq_nonneg (x + 1), hx_pos]\nlinarith [hx_pos]"
REQUEST = ExplanationRequest(ChunkPosition("p/1", 0, 2), ("x : ℝ\nhx_pos : 0 < x\n⊢ 0 < x ^ 2 + 1",), BLOCK, CHANGES)
ACCEPTED = "Since `hx_pos` makes $x$ positive, squares of shifts of $x$ bound the goal from below."
FEW_SHOTS = (
    ExplainedBlock(("a : ℕ\n⊢ a + 0 = a",), "simp", "Adding zero changes nothing, so `simp` closes it."),
    ExplainedBlock(("⊢ ∀ (x : ℝ), x ^ 2 ≥ 0",), "intro x\npositivity", "Introduce `x`; a square is nonnegative."),
)
BUILD_CONFIG = BuildConfig(
    rewrite_run="run",
    variant=NameVariant.NUMBERED,
    chunk_lengths=(ChunkLength(1), ChunkLength(0)),
    visible_chunk_examples_per_reasoning_example=3.0,
    non_visible_share=0.0,
    seed="test",
)


def judged(text: str, finish_reason: str = "stop") -> AcceptedExplanation | ExplanationRejection:
    return judge_explanation(TeacherReply(text, finish_reason), BLOCK, CHANGES, BOUNDS)


@pytest.mark.parametrize(
    ("text", "finish_reason", "rejection"),
    [
        (ACCEPTED, "length", ExplanationRejection.TRUNCATED),
        ("  \n", "stop", ExplanationRejection.EMPTY),
        (f"<think>\nShort.\n</think>\n\n{ACCEPTED}", "stop", ExplanationRejection.MARKUP),
        (f"{ACCEPTED}\n```lean\nnlinarith\n```", "stop", ExplanationRejection.CODE_BLOCK),
        (f"**Plan**: {ACCEPTED}", "stop", ExplanationRejection.LABEL),
        (f"Explanation: {ACCEPTED}", "stop", ExplanationRejection.LABEL),
        ("Use `nlinarith`.", "stop", ExplanationRejection.TOO_SHORT),
        ("Squares are nonnegative. " * 50, "stop", ExplanationRejection.TOO_LONG),
        ("Squares are nonnegative, 所以 `nlinarith` closes the goal.", "stop", ExplanationRejection.NOT_ENGLISH),
        (
            "Close with `nlinarith [sq_nonneg (x - 1), sq_nonneg (x + 1), sq_nonneg (x - 2), mul_pos hx_pos hx_pos]`.",
            "stop",
            ExplanationRejection.LONG_INLINE_CODE,
        ),
        (
            "The claim is a closed numeric fact, so `native_decide` settles it.",
            "stop",
            ExplanationRejection.FORBIDDEN_TOKEN,
        ),
        (
            "The identity is polynomial, so polyrith finds the combination.",
            "stop",
            ExplanationRejection.FORBIDDEN_TOKEN,
        ),
        (f"We bound the goal: {BLOCK}", "stop", ExplanationRejection.COPIES_BLOCK),
        (
            "Run `nlinarith [sq_nonneg (x - 1), sq_nonneg (x + 1), hx_pos]`, then `linarith [hx_pos]` to finish.",
            "stop",
            ExplanationRejection.LINE_BY_LINE,
        ),
        (
            "The provided tactics bound the square using the positivity of $x$.",
            "stop",
            ExplanationRejection.MENTIONS_GIVEN_BLOCK,
        ),
    ],
)
def test_unusable_replies_are_rejected(text: str, finish_reason: str, rejection: ExplanationRejection) -> None:
    assert judged(text, finish_reason) == rejection


@pytest.mark.parametrize(
    "text",
    [
        "Since `h₀` makes $x$ positive, the shifted squares bound the goal.",
        "Since $h_0$ makes $x$ positive, the shifted squares bound the goal.",
        "Since $h_{0}$ makes $x$ positive, the shifted squares bound the goal.",
    ],
)
def test_named_explanation_mentioning_a_replaced_numbered_name_is_rejected(text: str) -> None:
    assert judged(text) == ExplanationRejection.STALE_NAME


def test_named_explanation_with_an_escaped_descriptive_name_is_rejected() -> None:
    assert judged(r"Since $hx\_pos$ makes $x$ positive, the shifted squares bound the goal.") == (
        ExplanationRejection.UNRENAMED_NAME
    )


def test_accepted_explanation_is_renamed_back_for_the_numbered_arm() -> None:
    assert judged(f"  {ACCEPTED}\n") == AcceptedExplanation(
        ACCEPTED, "Since `h₀` makes $x$ positive, squares of shifts of $x$ bound the goal from below."
    )


def test_latex_quoted_name_is_renamed_back() -> None:
    accepted = judged("Since $hx_pos$ makes $x$ positive, the shifted squares bound the goal.")
    assert accepted == AcceptedExplanation(
        "Since $hx_pos$ makes $x$ positive, the shifted squares bound the goal.",
        "Since $h₀$ makes $x$ positive, the shifted squares bound the goal.",
    )


def test_both_arms_explanations_differ_in_the_names_only() -> None:
    accepted = judged("Use `hx_pos` twice: `hx_pos.le` and $hx_pos$ give the nonnegative terms the goal needs.")
    assert isinstance(accepted, AcceptedExplanation) and renamed_text(accepted.numbered, CHANGES) == accepted.named


def test_without_renaming_both_arms_share_the_explanation() -> None:
    accepted = judge_explanation(TeacherReply(ACCEPTED, "stop"), BLOCK, (), BOUNDS)
    assert accepted == AcceptedExplanation(ACCEPTED, ACCEPTED)


def test_short_tactic_names_may_be_mentioned() -> None:
    block = "norm_num\nlinarith"
    reply = TeacherReply("Normalize the numerals with `norm_num`, then the rest is linear: `linarith`.", "stop")
    assert isinstance(judge_explanation(reply, block, (), BOUNDS), AcceptedExplanation)


def test_rejected_reply_is_kept_beside_the_accepted_retry() -> None:
    record = explanation_record(REQUEST, [TeacherReply("Use it.", "stop"), TeacherReply(ACCEPTED, "stop")], BOUNDS)
    assert (record.outcome, record.rejected) == (
        ExplanationOutcome.EXPLAINED,
        (RejectedExplanation(ExplanationRejection.TOO_SHORT, "Use it."),),
    )


def test_two_rejected_replies_leave_the_chunk_unexplained() -> None:
    record = explanation_record(REQUEST, [TeacherReply("Use it.", "stop"), TeacherReply(ACCEPTED, "length")], BOUNDS)
    assert (record.outcome, record.named, record.numbered) == (ExplanationOutcome.REJECTED, "", "")


def test_explanation_record_keeps_the_chunk_position() -> None:
    record = explanation_record(REQUEST, [TeacherReply(ACCEPTED, "stop")], BOUNDS)
    assert ChunkPosition(record.proof_identifier, record.start, record.tactics) == REQUEST.position


def test_explanation_prompt_shows_the_state_and_the_block() -> None:
    user = explanation_messages(REQUEST.goals, BLOCK, FEW_SHOTS)[-1].content
    assert user.startswith(f"Proof state:\n```lean\n{REQUEST.goals[0]}\n```\n\nNext tactics:\n```lean\n{BLOCK}\n```")


def test_few_shot_examples_are_user_and_assistant_turns() -> None:
    roles = [message.role for message in explanation_messages(REQUEST.goals, BLOCK, FEW_SHOTS)]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]


def test_few_shot_answer_is_the_explanation_alone() -> None:
    assert explanation_messages(REQUEST.goals, BLOCK, FEW_SHOTS)[2].content == FEW_SHOTS[0].explanation


def test_every_request_shares_the_same_prompt_prefix() -> None:
    first = explanation_messages(REQUEST.goals, BLOCK, FEW_SHOTS)
    second = explanation_messages(("⊢ True",), "trivial", FEW_SHOTS)
    assert first[:-1] == second[:-1]


def test_explanation_request_shows_the_named_chunk() -> None:
    planned = plan_chunks([proof("p/1")], [example()], BUILD_CONFIG, COUNTS).visible
    requests = [explanation_request(chunk) for chunk in planned]
    assert all("h₀" not in "".join(request.goals) + request.tactic_block for request in requests)


def test_explanation_request_carries_the_proofs_renaming() -> None:
    planned = plan_chunks([proof("p/1")], [example()], BUILD_CONFIG, COUNTS).visible[0]
    assert explanation_request(planned).changes == CHANGES


def test_explanation_request_without_renaming_has_no_name_changes() -> None:
    record = proof("p/1", named_status=NamedStatus.NOTHING_TO_RENAME)
    planned = plan_chunks([record], [example()], BUILD_CONFIG, COUNTS).visible[0]
    assert explanation_request(planned).changes == ()


def one_tactic_example(index: int) -> RewrittenExample:
    record = example(reasoning=f"Since h₀ gives 0 < x, `nlinarith` finishes ({index}).")
    one_tactic = "nlinarith [h₀]"
    named = dataclasses.replace(record.named, tactic_block=renamed_text(one_tactic, CHANGES))
    original = dataclasses.replace(record.original, step_index=index)
    return dataclasses.replace(record, original=original, tactic_block=one_tactic, named=named)


def test_few_shots_take_one_example_per_block_length() -> None:
    config = ExplainConfig(few_shot=FewShotConfig(examples=2))
    few_shots = few_shot_explanations([example(), one_tactic_example(1), one_tactic_example(2)], config)
    assert [len(split_tactics(few_shot.tactic_block)) for few_shot in few_shots] == [1, 3]


def test_few_shots_use_the_named_explanation() -> None:
    few_shots = few_shot_explanations([example()], ExplainConfig())
    assert [few_shot.explanation for few_shot in few_shots] == [
        "Since hx_pos gives 0 < x, the square plus one is positive."
    ]


def test_few_shots_skip_thinking_traces() -> None:
    assert few_shot_explanations([example(visible=False)], ExplainConfig()) == ()


def test_explanation_statistics_count_the_chunks_explained_on_the_retry() -> None:
    retried = explanation_record(REQUEST, [TeacherReply("Use it.", "stop"), TeacherReply(ACCEPTED, "stop")], BOUNDS)
    first = explanation_record(REQUEST, [TeacherReply(ACCEPTED, "stop")], BOUNDS)
    rejected = ChunkExplanation("p/2", 0, 1, ExplanationOutcome.REJECTED, "", "", ())
    assert explanation_statistics([retried, first, rejected]).explained_on_retry == 1


def test_explain_config_loads() -> None:
    text = (CONFIGS / "explain_chunks.toml").read_text(encoding="utf-8")
    assert from_json_object(ExplainConfig, tomllib.loads(text)).teacher.servers[0].model == "namer"
