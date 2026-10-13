import dataclasses
import datetime
import tomllib

import pytest
from loop_fixtures import attempt

from lean_search.expert_iteration.digests import VersionedValueExample
from lean_search.expert_iteration.loop_config import EvaluationLoopConfig, ServerEndpoint, ServingConfig, ThinkingConfig
from lean_search.expert_iteration.loop_evaluation import (
    EvaluationRecord,
    due_version,
    evaluation_config_text,
    evaluation_due,
)
from lean_search.expert_iteration.loop_metrics import (
    Interval,
    run_totals,
    search_seconds,
    stage_metrics,
    version_metrics,
)
from lean_search.expert_iteration.serving import ModelVersion
from lean_search.expert_iteration.shards import AttemptRecord, Decision
from lean_search.value.labels import LabelKind, ValueExample

EVALUATION = EvaluationLoopConfig("evaluation.toml", every_versions=3, max_expansions=32, concurrency=16)
SERVING = ServingConfig(
    "base", "base", (ServerEndpoint("p0", 0, "http://p/v1"),), (ServerEndpoint("v0", 0, "http://v/v1"),)
)


def exact(steps: int, estimate: float) -> VersionedValueExample:
    example = ValueExample((f"⊢ {steps} {estimate}",), LabelKind.EXACT, steps, 1.0, "a", "a.x", 0)
    return VersionedValueExample(1, example, estimate)


def version(number: int) -> ModelVersion:
    return ModelVersion(number, "/p", "/v", "now", "proofs")


def test_first_stage_solves_are_counted_per_version() -> None:
    attempts = [
        attempt("a.1", version=1, proved=True, decision=Decision.SOLVED),
        attempt("a.2", version=1),
        attempt("a.3", version=1, stage=1, proved=True, decision=Decision.SOLVED),
        attempt("a.4", version=2),
    ]
    (first, _) = version_metrics(attempts, [])
    assert (first.first_stage_solved, first.first_stage_attempts, first.later_stage_solved) == (1, 2, 1)


def test_calibration_ranks_the_estimates_against_the_exact_steps() -> None:
    values = [exact(1, 1.2), exact(2, 2.5), exact(4, 3.9)]
    (metrics,) = version_metrics([attempt("a.1", version=1)], values)
    assert metrics.spearman == pytest.approx(1.0)


def test_run_totals_count_statements_once() -> None:
    attempts = [
        attempt("a.1", decision=Decision.ESCALATED),
        attempt("a.1", stage=1, proved=True, decision=Decision.SOLVED),
        attempt("a.2"),
    ]
    totals = run_totals(attempts, datetime.datetime.fromisoformat("2026-10-12T10:30:00+00:00"))
    assert (totals.statements, totals.solved_statements, totals.attempts_last_hour) == (2, 1, 3)


@pytest.mark.parametrize(
    ("published", "evaluated", "due"),
    [
        ([0], set(), 0),
        ([0, 1, 2], set(), None),
        ([0, 1, 2, 3], set(), 3),
        ([0, 1, 2, 3], {3}, None),
        ([0, 3, 4], set(), None),
    ],
)
def test_the_current_version_is_evaluated_when_due(published: list[int], evaluated: set[int], due: int | None) -> None:
    chosen = due_version([version(number) for number in published], evaluated, EVALUATION)
    assert (None if chosen is None else chosen.version) == due


def test_the_evaluation_config_requests_the_merged_servers_at_the_reduced_budget() -> None:
    template = (
        '[lean]\npool_size = 40\nconcurrency = 40\n\n[search]\nmax_expansions = 64\n\n[policy]\nmodel = "served"\n'
        'adapter = "old"\n\n[value]\nmodel = "served"\nadapter = "old"\n'
    )
    table = tomllib.loads(evaluation_config_text(template, SERVING, EVALUATION, ThinkingConfig()))
    assert (
        table["lean"]["concurrency"],
        table["search"]["max_expansions"],
        "adapter" in table["policy"],
        table["value"]["server_urls"],
    ) == (16, 32, False, ["http://v/v1"])


def stage_records() -> list[AttemptRecord]:
    first = attempt("a.1", decision=Decision.ESCALATED)
    second = dataclasses.replace(
        attempt("a.1", stage=1, proved=True, decision=Decision.SOLVED), generated_tokens=300, harvested_proofs=1
    )
    return [first, second]


def test_gpu_time_goes_to_the_stages_by_generated_tokens() -> None:
    metrics = stage_metrics(stage_records(), gpus=2, searched_seconds=3600.0)
    assert [entry.gpu_seconds for entry in metrics] == [1800.0, 5400.0]


def test_a_stage_yields_its_proofs_per_gpu_hour() -> None:
    (_, second) = stage_metrics(stage_records(), gpus=2, searched_seconds=3600.0)
    assert second.proofs_per_gpu_hour == pytest.approx(2 / 1.5)


def test_search_time_leaves_out_the_training_phases() -> None:
    records = [
        dataclasses.replace(attempt("a.1"), started_at="2026-10-12T09:00:00+00:00"),
        dataclasses.replace(attempt("a.2"), finished_at="2026-10-12T12:00:00+00:00"),
    ]
    phase = Interval("2026-10-12T10:00:00+00:00", "2026-10-12T10:30:00+00:00")
    assert search_seconds(records, [phase]) == 2.5 * 3600


def test_a_thinking_loop_evaluates_in_thinking_mode() -> None:
    template = '[policy]\nmodel = "m"\nthinking = false\n\n[value]\nmodel = "v"\n'
    thinking = ThinkingConfig(enabled=True, max_tokens=512, instruction="")
    policy = tomllib.loads(evaluation_config_text(template, SERVING, EVALUATION, thinking))["policy"]
    assert (policy["thinking"], policy["max_tokens"]) == (True, 512)


@pytest.mark.parametrize(
    ("finished_at", "due"),
    [(None, True), ("2026-10-13T07:30:00+00:00", False), ("2026-10-13T04:59:00+00:00", True)],
)
def test_an_evaluation_is_due_every_few_hours(finished_at: str | None, due: bool) -> None:
    evaluations = [] if finished_at is None else [EvaluationRecord(3, "run", 244, 150, finished_at, finished_at)]
    current = datetime.datetime.fromisoformat("2026-10-13T08:00:00+00:00")
    assert evaluation_due(evaluations, current, EvaluationLoopConfig("evaluation.toml", every_hours=3.0)) == due
