import pytest
from loop_fixtures import attempt, statement

from lean_search.expert_iteration.loop_config import PassBudget, SchedulerConfig
from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.scheduler import AttemptOutcome, Scheduler, decide
from lean_search.expert_iteration.shards import Decision
from lean_search.training.sft_data import SourceWeight

CONFIG = SchedulerConfig(
    budgets=(PassBudget(16, 300.0), PassBudget(64, 1200.0)), retry_share=0.25, promising_value=2.5, promising_depth=0
)


def outcome(
    proved: bool = False,
    start_failed: bool = False,
    best_frontier_value: float | None = 6.0,
    root_dead: bool = False,
    max_depth: int = 1,
) -> AttemptOutcome:
    return AttemptOutcome(proved, start_failed, best_frontier_value, root_dead, max_depth)


@pytest.mark.parametrize(
    ("attempt_outcome", "pass_index", "decision"),
    [
        (outcome(proved=True), 0, Decision.SOLVED),
        (outcome(start_failed=True), 0, Decision.RETIRED_LOAD_FAILURE),
        (outcome(best_frontier_value=1.0), 1, Decision.RETIRED_LAST_PASS),
        (outcome(best_frontier_value=1.0, root_dead=True), 0, Decision.RETIRED_DEAD),
        (outcome(best_frontier_value=2.5), 0, Decision.REQUEUED),
        (outcome(best_frontier_value=2.6, max_depth=9), 0, Decision.RETIRED_UNPROMISING),
        (outcome(best_frontier_value=None, max_depth=9), 0, Decision.RETIRED_UNPROMISING),
    ],
)
def test_decide(attempt_outcome: AttemptOutcome, pass_index: int, decision: Decision) -> None:
    assert decide(attempt_outcome, pass_index, CONFIG) == decision


def test_without_a_value_model_depth_can_requeue() -> None:
    config = SchedulerConfig(budgets=CONFIG.budgets, promising_depth=4)
    assert decide(outcome(best_frontier_value=None, max_depth=5), 0, config) == Decision.REQUEUED


def scheduler_with(config: SchedulerConfig = CONFIG, **counts: int) -> Scheduler:
    scheduler = Scheduler(config)
    scheduler.add_statements([statement(source, number) for source, count in counts.items() for number in range(count)])
    return scheduler


def requeue(scheduler: Scheduler, name: str, best_frontier_value: float) -> None:
    scheduler.record(attempt(name, decision=Decision.REQUEUED, best_frontier_value=best_frontier_value))


def test_fresh_statements_follow_the_source_weights() -> None:
    config = SchedulerConfig(budgets=CONFIG.budgets, source_weights=(SourceWeight("b", 0.5),))
    scheduler = scheduler_with(config, a=100, b=100)
    sources = [job.statement.source for job in (scheduler.next_job() for _ in range(30)) if job is not None]
    assert (sources.count("a"), sources.count("b")) == (20, 10)


def test_a_source_of_weight_zero_is_left_out() -> None:
    config = SchedulerConfig(budgets=CONFIG.budgets, source_weights=(SourceWeight("b", 0.0),))
    scheduler = scheduler_with(config, a=3, b=3)
    jobs = [scheduler.next_job() for _ in range(4)]
    assert [job.statement.source if job else None for job in jobs] == ["a", "a", "a", None]


def test_fresh_statements_keep_the_pool_order() -> None:
    scheduler = scheduler_with(a=3)
    assert [job.name for job in (scheduler.next_job(), scheduler.next_job()) if job] == ["a.a_0", "a.a_1"]


def test_retries_stay_within_their_share_while_fresh_statements_remain() -> None:
    scheduler = scheduler_with(a=40)
    started = [scheduler.next_job() for _ in range(8)]
    for job in started:
        assert job is not None
        requeue(scheduler, job.name, 1.0)
    passes = [job.pass_index for job in (scheduler.next_job() for _ in range(8)) if job is not None]
    # Retries until they reach a quarter of the attempts started (8 fresh before): 4 of the next 8.
    assert passes.count(1) == 4


def test_the_most_promising_retry_comes_first() -> None:
    scheduler = scheduler_with(a=2)
    started = [scheduler.next_job(), scheduler.next_job()]
    for job, frontier_value in zip(started, (2.0, 1.5), strict=True):
        assert job is not None
        requeue(scheduler, job.name, frontier_value)
    retry = scheduler.next_job()
    assert retry is not None and (retry.name, retry.pass_index, retry.budget.max_expansions) == ("a.a_1", 1, 64)


def test_retries_fill_in_when_fresh_statements_run_out() -> None:
    scheduler = scheduler_with(a=1)
    job = scheduler.next_job()
    assert job is not None
    requeue(scheduler, job.name, 3.0)
    retry = scheduler.next_job()
    assert retry is not None and retry.pass_index == 1


def test_a_released_job_comes_back_at_the_same_pass() -> None:
    scheduler = scheduler_with(a=2)
    job = scheduler.next_job()
    assert job is not None
    scheduler.release(job)
    again = scheduler.next_job()
    assert again is not None and (again.name, again.pass_index) == (job.name, 0)


def test_solved_and_retired_statements_never_come_back() -> None:
    scheduler = scheduler_with(a=2)
    first, second = scheduler.next_job(), scheduler.next_job()
    assert first is not None and second is not None
    scheduler.record(attempt(first.name, proved=True, decision=Decision.SOLVED))
    scheduler.record(attempt(second.name, decision=Decision.RETIRED_DEAD))
    assert scheduler.next_job() is None


def test_replaying_the_attempt_log_restores_the_queue() -> None:
    statements = [statement("a", number) for number in range(5)]
    log = [
        attempt(problem_name(statements[0]), proved=True, decision=Decision.SOLVED),
        attempt(problem_name(statements[1]), decision=Decision.REQUEUED, best_frontier_value=2.0),
        attempt(problem_name(statements[2]), decision=Decision.RETIRED_UNPROMISING),
    ]
    scheduler = Scheduler(CONFIG)
    scheduler.add_statements(statements)
    scheduler.replay(log)
    jobs = [scheduler.next_job() for _ in range(4)]
    assert [(job.name, job.pass_index) if job else None for job in jobs] == [
        ("a.a_1", 1),
        ("a.a_3", 0),
        ("a.a_4", 0),
        None,
    ]


def test_counts_track_every_status() -> None:
    scheduler = scheduler_with(a=3)
    job = scheduler.next_job()
    assert job is not None
    scheduler.record(attempt(job.name, proved=True, decision=Decision.SOLVED))
    scheduler.next_job()
    counts = scheduler.counts()
    assert (counts.fresh, counts.in_flight, counts.solved) == (1, 1, 1)
