from graph_trees import GraphBuilder

from lean_search.rl.step1_settings import StepValue, progressing_step_values
from lean_search.search import FailureKind, StepSource, TreeRecord

ROOT = "x : ℕ\n⊢ x + 0 = x"


def calibration_tree() -> TreeRecord:
    """One expansion of the root: a block that changed the goals (3 samples), one that closed them, one that left
    them as they were, a failing one, and an automation step."""
    builder = GraphBuilder(ROOT)
    root = builder.root
    builder.child(root, "x : ℕ\n⊢ x = x", text="simp only [Nat.add_zero]", sample_count=3)
    proved = builder.child(root, text="simp")
    builder.duplicate(root, root, text="skip")
    builder.failure(root, FailureKind.ERROR, text="linarith")
    builder.child(root, text="omega", source=StepSource.AUTOMATION)
    return builder.record(proved)


def test_only_policy_blocks_that_ran_and_changed_the_goals_count() -> None:
    assert progressing_step_values(calibration_tree()) == [StepValue(-1.0, 3), StepValue(-1.0, 1)]
