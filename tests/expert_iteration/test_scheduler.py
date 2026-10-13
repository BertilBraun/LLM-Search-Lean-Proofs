import pytest
from loop_fixtures import attempt, statement

from lean_search.expert_iteration.loop_config import SchedulerConfig, SearchStage
from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.scheduler import Scheduler, StageOutcome, decide
from lean_search.expert_iteration.shards import Decision
from lean_search.training.sft_data import SourceWeight

CONFIG = SchedulerConfig(
    stages=(SearchStage(32, 600.0), SearchStage(128, 2400.0, 3.0), SearchStage(512, 9600.0, 2.0)),
    promising_depth=0,
)


def outcome(
    proved: bool = False,
    start_failed: bool = False,
    frontier_exhausted: bool = False,
    best_frontier_value: float | None = 6.0,
    max_depth: int = 1,
) -> StageOutcome:
    return StageOutcome(proved, start_failed, frontier_exhausted, best_frontier_value, max_depth)


@pytest.mark.parametrize(
    ("stage_outcome", "stage", "decision"),
    [
        (outcome(proved=True), 0, Decision.SOLVED),
        (outcome(start_failed=True), 0, Decision.RETIRED_LOAD_FAILURE),
        (outcome(frontier_exhausted=True, best_frontier_value=None), 0, Decision.RETIRED_DEAD),
        (outcome(best_frontier_value=3.0), 0, Decision.ESCALATED),
        (outcome(best_frontier_value=3.1), 0, Decision.RETIRED_UNPROMISING),
        (outcome(best_frontier_value=2.0), 1, Decision.ESCALATED),
        (outcome(best_frontier_value=2.5), 1, Decision.RETIRED_UNPROMISING),
        (outcome(best_frontier_value=0.5), 2, Decision.RETIRED_LAST_STAGE),
        (outcome(best_frontier_value=None, max_depth=9), 0, Decision.RETIRED_UNPROMISING),
    ],
)
def test_decide(stage_outcome: StageOutcome, stage: int, decision: Decision) -> None:
    assert decide(stage_outcome, stage, CONFIG) == decision


def test_without_a_value_model_depth_can_escalate() -> None:
    config = SchedulerConfig(stages=CONFIG.stages, promising_depth=4)
    assert decide(outcome(best_frontier_value=None, max_depth=5), 0, config) == Decision.ESCALATED


def scheduler_with(config: SchedulerConfig = CONFIG, **counts: int) -> Scheduler:
    scheduler = Scheduler(config)
    scheduler.add_statements([statement(source, number) for source, count in counts.items() for number in range(count)])
    return scheduler


def test_fresh_statements_follow_the_source_weights() -> None:
    config = SchedulerConfig(stages=CONFIG.stages, source_weights=(SourceWeight("b", 0.5),))
    scheduler = scheduler_with(config, a=100, b=100)
    sources = [job.statement.source for job in (scheduler.next_job() for _ in range(30)) if job is not None]
    assert (sources.count("a"), sources.count("b")) == (20, 10)


def test_a_source_of_weight_zero_is_left_out() -> None:
    config = SchedulerConfig(stages=CONFIG.stages, source_weights=(SourceWeight("b", 0.0),))
    scheduler = scheduler_with(config, a=3, b=3)
    jobs = [scheduler.next_job() for _ in range(4)]
    assert [job.statement.source if job else None for job in jobs] == ["a", "a", "a", None]


def test_fresh_statements_keep_the_pool_order() -> None:
    scheduler = scheduler_with(a=3)
    assert [job.name for job in (scheduler.next_job(), scheduler.next_job()) if job] == ["a.a_0", "a.a_1"]


def test_an_escalated_search_stays_in_flight() -> None:
    scheduler = scheduler_with(a=2)
    job = scheduler.next_job()
    assert job is not None
    scheduler.record(attempt(job.name, decision=Decision.ESCALATED))
    counts = scheduler.counts()
    assert (counts.in_flight, counts.queued, counts.fresh) == (1, 0, 1)


def test_a_released_fresh_job_comes_back_first() -> None:
    scheduler = scheduler_with(a=2)
    job = scheduler.next_job()
    assert job is not None
    scheduler.release(job)
    again = scheduler.next_job()
    assert again is not None and (again.name, again.stage) == (job.name, 0)


def test_a_released_escalated_job_starts_over() -> None:
    scheduler = scheduler_with(a=2)
    job = scheduler.next_job()
    assert job is not None
    scheduler.record(attempt(job.name, decision=Decision.ESCALATED))
    scheduler.release(job)
    again = scheduler.next_job()
    assert again is not None and (again.name, again.stage) == (job.name, 0)


def test_solved_and_retired_statements_never_come_back() -> None:
    scheduler = scheduler_with(a=2)
    first, second = scheduler.next_job(), scheduler.next_job()
    assert first is not None and second is not None
    scheduler.record(attempt(first.name, proved=True, decision=Decision.SOLVED))
    scheduler.record(attempt(second.name, decision=Decision.RETIRED_DEAD))
    assert scheduler.next_job() is None


def test_replay_restarts_cut_off_searches_first_most_promising_first() -> None:
    statements = [statement("a", number) for number in range(6)]
    names = [problem_name(record) for record in statements]
    log = [
        attempt(names[0], proved=True, decision=Decision.SOLVED),
        attempt(names[1], decision=Decision.ESCALATED, best_frontier_value=2.5),
        attempt(names[2], decision=Decision.RETIRED_UNPROMISING),
        attempt(names[3], decision=Decision.ESCALATED, best_frontier_value=1.0),
        attempt(names[3], stage=1, decision=Decision.ESCALATED, best_frontier_value=1.5),
        attempt(names[4], decision=Decision.ESCALATED, best_frontier_value=0.5),
        attempt(names[4], stage=1, proved=True, decision=Decision.SOLVED),
    ]
    scheduler = Scheduler(CONFIG)
    scheduler.add_statements(statements)
    scheduler.replay(log)
    jobs = [scheduler.next_job() for _ in range(4)]
    assert [(job.name, job.stage) if job else None for job in jobs] == [
        ("a.a_3", 0),
        ("a.a_1", 0),
        ("a.a_5", 0),
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
