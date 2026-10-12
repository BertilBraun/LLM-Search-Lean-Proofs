import datetime
import tomllib

import pytest
from loop_fixtures import attempt

from lean_search.expert_iteration.digests import VersionedValueExample
from lean_search.expert_iteration.loop_config import EvaluationLoopConfig, ServerEndpoint, ServingConfig
from lean_search.expert_iteration.loop_evaluation import due_version, evaluation_config_text
from lean_search.expert_iteration.loop_metrics import run_totals, version_metrics
from lean_search.expert_iteration.serving import ModelVersion
from lean_search.expert_iteration.shards import Decision
from lean_search.value.labels import LabelKind, ValueExample

EVALUATION = EvaluationLoopConfig("evaluation.toml", every_versions=3, max_expansions=32, concurrency=16)
SERVING = ServingConfig("base", "served", "base", (ServerEndpoint("gpu0", 0, "http://a/v1"),))


def exact(steps: int, estimate: float) -> VersionedValueExample:
    example = ValueExample((f"⊢ {steps} {estimate}",), LabelKind.EXACT, steps, 1.0, "a", "a.x", 0)
    return VersionedValueExample(1, example, estimate)


def version(number: int) -> ModelVersion:
    return ModelVersion(number, "/p", "/v", "now", "proofs")


def test_first_pass_solves_are_counted_per_version() -> None:
    attempts = [
        attempt("a.1", version=1, proved=True, decision=Decision.SOLVED),
        attempt("a.2", version=1),
        attempt("a.3", version=1, pass_index=1, proved=True, decision=Decision.SOLVED),
        attempt("a.4", version=2),
    ]
    (first, _) = version_metrics(attempts, [])
    assert (first.first_pass_solved, first.first_pass_attempts, first.later_pass_solved) == (1, 2, 1)


def test_calibration_ranks_the_estimates_against_the_exact_steps() -> None:
    values = [exact(1, 1.2), exact(2, 2.5), exact(4, 3.9)]
    (metrics,) = version_metrics([attempt("a.1", version=1)], values)
    assert metrics.spearman == pytest.approx(1.0)


def test_run_totals_count_statements_once() -> None:
    attempts = [
        attempt("a.1", decision=Decision.REQUEUED),
        attempt("a.1", pass_index=1, proved=True, decision=Decision.SOLVED),
        attempt("a.2"),
    ]
    totals = run_totals(attempts, datetime.datetime.fromisoformat("2026-10-12T10:30:00+00:00"))
    assert (totals.statements, totals.solved_statements, totals.attempts_last_hour) == (2, 1, 3)


@pytest.mark.parametrize(
    ("published", "evaluated", "due"),
    [([0, 1, 2], set(), None), ([0, 1, 2, 3], set(), 3), ([0, 1, 2, 3], {3}, None), ([0, 3, 4], set(), None)],
)
def test_the_current_version_is_evaluated_when_due(published: list[int], evaluated: set[int], due: int | None) -> None:
    chosen = due_version([version(number) for number in published], evaluated, EVALUATION)
    assert (None if chosen is None else chosen.version) == due


def test_the_evaluation_config_requests_the_served_adapters_at_the_reduced_budget() -> None:
    template = (
        '[lean]\npool_size = 40\nconcurrency = 40\n\n[search]\nmax_expansions = 64\n\n[policy]\nmodel = "served"\n'
        'adapter = "old"\n\n[value]\nmodel = "served"\nadapter = "old"\n'
    )
    table = tomllib.loads(evaluation_config_text(template, SERVING, EVALUATION))
    assert (
        table["lean"]["concurrency"],
        table["search"]["max_expansions"],
        table["policy"]["adapter"],
        table["value"]["server_urls"],
    ) == (16, 32, "policy", ["http://a/v1"])
