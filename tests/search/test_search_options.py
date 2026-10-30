from pathlib import Path

from scripted_repl import HEADER, STATEMENT, ScriptedRepl, root_state, write_environment_names

from lean_search.data import Problem, Split
from lean_search.lean.identifiers import NameRepair
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    DepthPlusGoals,
    Edge,
    EdgeOutcome,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_theorem,
)
from lean_search.search.search import NameRepairConfig

CONSTANTS = ["Nat.add_zero", "Nat.add_comm", "Nat.succ_le_iff"]
PROBLEM = Problem("t", Split.VALID, HEADER, STATEMENT, "", "")
CLOSING = "rw [Nat.add_zero]"


class Batches:
    """Yields its batches in turn, each after the search ran the one before."""

    def __init__(self, *batches: CandidateBatch) -> None:
        self.batches = batches

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        for batch in self.batches:
            yield batch


def policy_batch(*texts: str, feedback: bool = False) -> CandidateBatch:
    candidates = tuple(Candidate(text, StepSource.POLICY, log_probability=-1.0, feedback=feedback) for text in texts)
    return CandidateBatch(candidates, prompt="feedback prompt" if feedback else "prompt", feedback=feedback)


async def search(
    tmp_path: Path, expander: Batches, outcomes: dict[str, tuple[str, ...]], repair: bool = False
) -> CompletedSearch:
    directory = write_environment_names(tmp_path, CONSTANTS)
    config = SearchConfig(
        max_expansions=1,
        name_inaccessible_hypotheses=False,
        environment_names_directory=str(directory),
        name_repair=NameRepairConfig(enabled=repair),
    )
    repl = ScriptedRepl(tmp_path, outcomes)
    return await search_theorem(PROBLEM, repl, expander, DepthPlusGoals(), config, root_state())


async def test_repaired_block_runs_with_the_existing_name(tmp_path: Path) -> None:
    completed = await search(tmp_path, Batches(policy_batch("rw [Nat.add_zeroo]")), {CLOSING: ()}, repair=True)
    assert completed.result.proved


async def repaired_edges(tmp_path: Path) -> list[Edge]:
    completed = await search(tmp_path, Batches(policy_batch("rw [Nat.add_zeroo]")), {CLOSING: ()}, repair=True)
    assert completed.tree is not None
    return completed.tree.edges


async def test_sampled_edge_keeps_its_own_text_and_failure(tmp_path: Path) -> None:
    edge = (await repaired_edges(tmp_path))[0]
    assert (edge.text, edge.outcome, edge.repaired) == ("rw [Nat.add_zeroo]", EdgeOutcome.FAILED, False)


async def test_repair_runs_as_a_search_step_of_its_own(tmp_path: Path) -> None:
    edge = (await repaired_edges(tmp_path))[1]
    assert (edge.source, edge.text, edge.outcome) == (StepSource.REPAIR, CLOSING, EdgeOutcome.CHILD)


async def test_repair_edge_names_its_repair(tmp_path: Path) -> None:
    edge = (await repaired_edges(tmp_path))[1]
    assert edge.name_repairs == (NameRepair("Nat.add_zeroo", "Nat.add_zero"),)


async def test_repair_a_sample_already_wrote_is_not_run_again(tmp_path: Path) -> None:
    directory = write_environment_names(tmp_path, CONSTANTS)
    config = SearchConfig(
        max_expansions=1,
        name_inaccessible_hypotheses=False,
        environment_names_directory=str(directory),
        name_repair=NameRepairConfig(enabled=True),
    )
    repl = ScriptedRepl(tmp_path, {CLOSING: ("a : ℕ\n⊢ a = a",)})
    expander = Batches(policy_batch(CLOSING, "rw [Nat.add_zeroo]"))
    await search_theorem(PROBLEM, repl, expander, DepthPlusGoals(), config, root_state())
    assert repl.blocks == [CLOSING, "rw [Nat.add_zeroo]"]


async def test_without_repair_the_unknown_name_is_rejected(tmp_path: Path) -> None:
    completed = await search(tmp_path, Batches(policy_batch("rw [Nat.add_zeroo]")), {CLOSING: ()})
    assert completed.tree is not None
    assert (completed.tree.edges[0].outcome, completed.tree.edges[0].repaired) == (EdgeOutcome.FAILED, False)


async def test_lean_error_naming_an_unknown_constant_is_repaired(tmp_path: Path) -> None:
    directory = write_environment_names(tmp_path, CONSTANTS)
    config = SearchConfig(
        max_expansions=1,
        name_inaccessible_hypotheses=False,
        environment_names_directory=str(directory),
        name_repair=NameRepairConfig(enabled=True),
    )
    # `try` keeps the identifier check out: Lean's own message names the constant.
    repl = ScriptedRepl(tmp_path, {"try rw [Nat.add_zero]": ()}, error="unknown constant 'Nat.add_zeroo'")
    expander = Batches(policy_batch("try rw [Nat.add_zeroo]"))
    await search_theorem(PROBLEM, repl, expander, DepthPlusGoals(), config, root_state())
    assert repl.blocks == ["try rw [Nat.add_zeroo]", "try rw [Nat.add_zero]"]


async def test_name_too_far_from_any_constant_is_not_repaired(tmp_path: Path) -> None:
    completed = await search(tmp_path, Batches(policy_batch("rw [Nat.mul_self_le]")), {CLOSING: ()}, repair=True)
    assert completed.tree is not None
    assert completed.tree.edges[0].repaired is False


async def test_feedback_batch_marks_its_edges(tmp_path: Path) -> None:
    expander = Batches(policy_batch("simp"), policy_batch("omega", feedback=True))
    completed = await search(tmp_path, expander, {})
    assert completed.tree is not None
    assert [edge.feedback for edge in completed.tree.edges] == [False, True]


async def test_feedback_batch_records_its_own_prompt(tmp_path: Path) -> None:
    expander = Batches(policy_batch("simp"), policy_batch("omega", feedback=True))
    completed = await search(tmp_path, expander, {})
    assert completed.tree is not None
    assert [(texts.prompt, texts.feedback) for texts in completed.tree.expansion_texts] == [
        ("prompt", False),
        ("feedback prompt", True),
    ]


async def test_feedback_sample_repeating_an_earlier_block_is_not_run_again(tmp_path: Path) -> None:
    expander = Batches(policy_batch("simp"), policy_batch("simp", feedback=True))
    completed = await search(tmp_path, expander, {})
    assert completed.tree is not None
    assert completed.tree.edges[1].outcome == EdgeOutcome.REPEATED
