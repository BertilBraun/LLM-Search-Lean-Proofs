import pytest
from expert_trees import TreeBuilder

from lean_search.expert_iteration.proofs import (
    EXPERT_ITERATION_SOURCE,
    FoundProof,
    found_proof,
    policy_sft_examples,
    proof_length_histogram,
    shortest_proofs,
)
from lean_search.search import StepSource, TreeRecord


def three_step_tree() -> TreeRecord:
    """intro x (policy) -> norm_num (automation) -> linarith (policy), with a failed sibling at the root."""
    builder = TreeBuilder("⊢ ∀ x, p x")
    builder.failure(builder.root, "exact foo")
    a = builder.child(builder.root, "x : ℕ\n⊢ p x", step="intro x")
    b = builder.child(a, "x : ℕ\n⊢ q x", step="norm_num", source=StepSource.AUTOMATION, log_probability=None)
    proved = builder.child(b, step="linarith")
    return builder.record(proved)


def proof_of(run: str, steps: int) -> FoundProof:
    builder = TreeBuilder("⊢ r")
    node = builder.root
    for index in range(steps - 1):
        node = builder.child(node, f"⊢ r{index}", step=f"step {index}")
    proved = builder.child(node, step="done")
    proof = found_proof(run, builder.record(proved))
    assert proof is not None
    return proof


def test_found_proof_follows_the_verified_path() -> None:
    proof = found_proof("round_0", three_step_tree())
    assert proof is not None and [step.step for step in proof.steps] == ["intro x", "norm_num", "linarith"]


def test_each_step_carries_the_goals_before_it() -> None:
    proof = found_proof("round_0", three_step_tree())
    assert proof is not None and [step.goals for step in proof.steps] == [
        ("⊢ ∀ x, p x",),
        ("x : ℕ\n⊢ p x",),
        ("x : ℕ\n⊢ q x",),
    ]


def test_an_unsolved_tree_has_no_proof() -> None:
    builder = TreeBuilder("⊢ r")
    builder.failure(builder.root, "simp")
    assert found_proof("round_0", builder.record()) is None


def test_the_shortest_proof_of_a_statement_is_kept() -> None:
    (kept,) = shortest_proofs([proof_of("round_0", 3), proof_of("round_1", 2), proof_of("round_2", 4)])
    assert kept.run == "round_1"


def test_equally_short_proofs_keep_the_earlier_run() -> None:
    (kept,) = shortest_proofs([proof_of("round_1", 2), proof_of("round_0", 2)])
    assert kept.run == "round_0"


@pytest.mark.parametrize(
    ("policy_steps_only", "steps"), [(True, ["intro x", "linarith"]), (False, ["intro x", "norm_num", "linarith"])]
)
def test_sft_examples_can_leave_out_automation_steps(policy_steps_only: bool, steps: list[str]) -> None:
    proof = found_proof("round_0", three_step_tree())
    assert proof is not None
    examples = policy_sft_examples([proof], policy_steps_only)
    assert [example.tactic_block for example in examples] == steps


def test_sft_examples_name_the_run_and_statement() -> None:
    proof = found_proof("round_0", three_step_tree())
    assert proof is not None
    (first, *_) = policy_sft_examples([proof], policy_steps_only=True)
    assert (first.source, first.proof_identifier, first.step_index) == (
        EXPERT_ITERATION_SOURCE,
        "round_0/lean_workbook.t",
        0,
    )


def test_proof_lengths_are_bucketed() -> None:
    proofs = [proof_of("a", 1), proof_of("b", 2), proof_of("c", 2), proof_of("d", 5)]
    assert proof_length_histogram(proofs, 3) == (1, 2, 1)
