import pytest
from loop_fakes import solved_tree

from lean_search.data import Problem, Split
from lean_search.monitoring.families import FailureTiers
from lean_search.rl.phase_metrics import FailureTier, failure_tier, failure_tiers, repeats_itself, unknown_names
from lean_search.search import Accounting, SearchResult, StopReason, TreeRecord, tree_record
from lean_search.search.tree import Failure, FailureKind

PROBLEM = Problem("test.t0", Split.VALID, "", "theorem t0 : True := by", "", "")


@pytest.mark.parametrize(
    ("failure", "tier"),
    [
        (Failure(FailureKind.UNPARSED, "no block"), FailureTier.MALFORMED),
        (Failure(FailureKind.ERROR, "<input>:1:5: unexpected token 'at'; expected command"), FailureTier.MALFORMED),
        (Failure(FailureKind.ERROR, "unknown constant 'Real.foo_bar'"), FailureTier.MALFORMED),
        (Failure(FailureKind.UNKNOWN_IDENTIFIER, "h₇"), FailureTier.INVALID_IN_STATE),
        (Failure(FailureKind.ERROR, "type mismatch\n  h₀\nhas type"), FailureTier.INVALID_IN_STATE),
        (Failure(FailureKind.ERROR, "linarith failed to find a contradiction"), FailureTier.VALID_BUT_FAILING),
        (Failure(FailureKind.HEARTBEAT_TIMEOUT, "maxHeartbeats"), FailureTier.TIMEOUT),
        (Failure(FailureKind.REPL_FAILURE, "crashed"), None),
    ],
)
def test_failure_tiers(failure: Failure, tier: FailureTier | None) -> None:
    assert failure_tier(failure) == tier


def test_a_repeated_explanation_is_a_loop() -> None:
    assert repeats_itself("We need to show x = 2.\n" * 3)


def test_a_varied_explanation_is_not_a_loop() -> None:
    assert not repeats_itself("First isolate x using h₁.\nThen substitute y = 1.\nFinally conclude x = 2.")


def record() -> TreeRecord:
    tree = solved_tree(PROBLEM)
    result = SearchResult(PROBLEM.name, True, StopReason.PROVED, None, (), (), Accounting(), None, 0, 1)
    return tree_record(tree, PROBLEM.formal_statement, result)


def test_failure_tiers_count_policy_samples() -> None:
    assert failure_tiers([record()]) == FailureTiers(malformed=1)


def test_unknown_names_count_per_policy_sample() -> None:
    names = unknown_names([record()])
    assert (names.unknown, names.samples) == (1, 2)
