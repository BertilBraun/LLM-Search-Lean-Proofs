from pathlib import Path

from scripted_repl import ROOT_GOALS, STATEMENT, ScriptedRepl, root_state

from lean_search.lean.identifiers import NameRepairer, UnknownNames, namespace_members, parse_environment_names
from lean_search.rl.name_repair_replay import (
    FailureReplay,
    ReplayOutcome,
    ReplayRun,
    UnknownNameFailure,
    repaired_texts,
    replay_block,
    threshold_summaries,
    unknown_name_failures,
)
from lean_search.search import (
    Accounting,
    EdgeOutcome,
    Failure,
    FailureKind,
    SearchResult,
    SearchTree,
    StepSource,
    StopReason,
    TreeRecord,
    tree_record,
)

NAMES = parse_environment_names(
    "import Mathlib", ["constant\ttheorem\tNat.add_zero", "constant\ttheorem\tNat.add_comm"]
)
FAILURE = UnknownNameFailure("t", 0, 0, "rw [Nat.add_zeroo]", ("Nat.add_zeroo",), ("Nat.add_zeroo",))


def failed_tree(*names: str) -> TreeRecord:
    tree = SearchTree("t", root_state(), 0.0)
    tree.root.expansion_index = 0
    for name in names:
        tree.add_edge(
            tree.root,
            text=f"rw [{name}]",
            source=StepSource.POLICY,
            log_probability=-1.0,
            prompt_tokens=0,
            generated_tokens=0,
            outcome=EdgeOutcome.FAILED,
            failure=Failure(FailureKind.UNKNOWN_IDENTIFIER, UnknownNames(0, (name,)).rejection.message),
        )
    result = SearchResult("t", False, StopReason.EXPANSION_BUDGET, None, (), (), Accounting(), None, 0, 0)
    return tree_record(tree, STATEMENT, result)


def test_only_failures_with_a_dotted_name_are_replayed() -> None:
    failures = unknown_name_failures(failed_tree("Nat.add_zeroo", "h₃"))
    assert [failure.dotted for failure in failures] == [("Nat.add_zeroo",)]


def test_each_threshold_gets_its_repair_or_none() -> None:
    repairers = [NameRepairer(namespace_members(NAMES), threshold) for threshold in (0.85, 0.99)]
    assert repaired_texts(FAILURE, repairers, ("",)) == ("rw [Nat.add_zero]", None)


async def test_repaired_block_that_completes_is_valid(tmp_path: Path) -> None:
    repl = ScriptedRepl(tmp_path, {"rw [Nat.add_zero]": ROOT_GOALS})
    run = await replay_block(repl, root_state(), "rw [Nat.add_zero]", 50_000, 60.0)
    assert run.outcome == ReplayOutcome.VALID


def test_threshold_summary_counts_valid_repairs_among_all_failures() -> None:
    runs = {"rw [Nat.add_zero]": ReplayRun(ReplayOutcome.VALID, 0.5)}
    replays = [
        FailureReplay(FAILURE, True, ("rw [Nat.add_zero]", None), runs),
        FailureReplay(FAILURE, True, (None, None)),
        FailureReplay(FAILURE, False, (None, None)),
    ]
    summaries = threshold_summaries(replays, (0.85, 0.99))
    assert [(summary.failures, summary.valid, summary.valid_share) for summary in summaries] == [
        (2, 1, 0.5),
        (2, 0, 0.0),
    ]
