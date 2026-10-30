import dataclasses

import pytest
from loop_fixtures import attempt, verified

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import Curriculum, CurriculumConfig, CurriculumState
from lean_search.expert_iteration.known_proofs import IndexedStatement
from lean_search.expert_iteration.loop_config import SchedulerConfig
from lean_search.expert_iteration.pool import problem_name
from lean_search.expert_iteration.scheduler import Scheduler
from lean_search.expert_iteration.shards import Decision

CONFIG = CurriculumConfig(
    proof_steps_weight=1.0,
    root_value_weight=0.0,
    band_width=1.0,
    band_step=1.0,
    window=5,
    raise_solve_rate=0.5,
    lower_solve_rate=0.3,
    fast_raise_solve_rate=2.0,
)


def curriculum_with(tactics: list[int], config: CurriculumConfig = CONFIG) -> Curriculum:
    curriculum = Curriculum(config, value_version=0)
    curriculum.add([verified(number, count) for number, count in enumerate(tactics)], started=set())
    return curriculum


def fed_tactics(curriculum: Curriculum, count: int) -> list[int]:
    statements = [curriculum.next_statement() for _ in range(count)]
    return [curriculum.statements[problem_name(statement)].proof_tactics for statement in statements if statement]


def test_only_verified_statements_the_automation_misses_join() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    added = curriculum.add(
        [verified(0, 2), verified(1, 2, automation_solved=True), verified(2, 2, is_verified=False)], set()
    )
    assert [statement.identifier for statement in added] == ["t0"]


def test_the_band_starts_at_the_easiest_statements() -> None:
    curriculum = curriculum_with([5, 1, 2, 9, 1])
    assert sorted(fed_tactics(curriculum, 3)) == [1, 1, 2]


def test_an_empty_band_moves_to_the_nearest_statements() -> None:
    curriculum = curriculum_with([1, 6, 7])
    fed_tactics(curriculum, 1)
    assert fed_tactics(curriculum, 1) == [6]


def outcomes(curriculum: Curriculum, solved: list[bool]) -> None:
    for outcome in solved:
        statement = curriculum.next_statement()
        assert statement is not None
        curriculum.record_outcome(problem_name(statement), outcome)


@pytest.mark.parametrize(
    ("solved", "band_low"),
    [
        ([True, True, True, False, False], 2.0),
        ([True, False, False, False, False], 1.0),
        ([True, True, False, False, False], 1.0),
    ],
    ids=["raised", "floored", "kept"],
)
def test_the_band_follows_the_solve_rate(solved: list[bool], band_low: float) -> None:
    curriculum = curriculum_with([1] * 4 + [2] * 8 + [3] * 8)
    outcomes(curriculum, solved)
    assert curriculum.band_low == band_low


def test_a_low_solve_rate_lowers_the_band() -> None:
    curriculum = curriculum_with([1] * 4 + [3] * 8)
    curriculum.restore(CurriculumState(3.0, 1, ()))
    outcomes(curriculum, [False] * 5)
    assert curriculum.band_low == 2.0


def test_outcomes_from_before_a_band_move_do_not_count() -> None:
    curriculum = curriculum_with([1] * 8 + [2] * 8)
    cohort = fed_names(curriculum, 5)
    late = fed_names(curriculum, 1)
    record(curriculum, cohort, True)
    record(curriculum, late, True)
    assert curriculum.counts().outcomes == 0


def fed_names(curriculum: Curriculum, count: int) -> list[str]:
    statements = [curriculum.next_statement() for _ in range(count)]
    return [problem_name(statement) for statement in statements if statement]


def record(curriculum: Curriculum, names: list[str], solved: bool) -> None:
    for name in names:
        curriculum.record_outcome(name, solved)


def test_the_band_is_judged_by_the_statements_fed_first_not_the_first_to_finish() -> None:
    curriculum = curriculum_with([1] * 4 + [3] * 20)
    curriculum.restore(CurriculumState(3.0, 1, ()))
    cohort = fed_names(curriculum, 5)
    record(curriculum, fed_names(curriculum, 5), True)
    record(curriculum, cohort, False)
    assert curriculum.band_low == 2.0


def test_the_band_waits_for_every_statement_of_its_cohort() -> None:
    curriculum = curriculum_with([1] * 4 + [2] * 8)
    cohort = fed_names(curriculum, 5)
    record(curriculum, [*cohort[:4], *fed_names(curriculum, 1)], True)
    assert curriculum.band_low == 1.0


def test_a_cohort_is_judged_once_its_judged_share_finished() -> None:
    curriculum = curriculum_with([1] * 4 + [2] * 8, dataclasses.replace(CONFIG, judged_share=0.8))
    cohort = fed_names(curriculum, 5)
    record(curriculum, cohort[:4], True)
    assert curriculum.band_low == 2.0


def test_cohort_statements_still_running_at_the_judgement_count_as_unsolved() -> None:
    curriculum = curriculum_with([1] * 4 + [2] * 8, dataclasses.replace(CONFIG, judged_share=0.4))
    cohort = fed_names(curriculum, 5)
    record(curriculum, cohort[:2], True)
    assert curriculum.band_low == 1.0


def test_an_abandoned_cohort_statement_makes_room_for_the_next_one_fed() -> None:
    curriculum = curriculum_with([1] * 6 + [2] * 8)
    cohort = fed_names(curriculum, 5)
    curriculum.abandon(cohort[0])
    record(curriculum, [*cohort[1:], *fed_names(curriculum, 1)], True)
    assert curriculum.band_low == 2.0


def test_a_band_that_stays_judges_a_new_cohort() -> None:
    curriculum = curriculum_with([1] * 12 + [2] * 8)
    outcomes(curriculum, [True, True, False, False, False])
    record(curriculum, fed_names(curriculum, 5), True)
    assert curriculum.band_low == 2.0


def test_a_restart_with_cohort_statements_running_starts_a_new_cohort() -> None:
    curriculum = curriculum_with([1] * 8)
    cohort = fed_names(curriculum, 5)
    record(curriculum, cohort[:3], True)
    assert curriculum.state().outcomes == ()


def test_root_values_shift_the_difficulty() -> None:
    config = CurriculumConfig(proof_steps_weight=0.5, root_value_weight=0.5)
    curriculum = curriculum_with([4], config)
    before = curriculum.difficulty("s.t0")
    curriculum.set_root_values({"s.t0": 1.0}, version=0)
    assert (before, curriculum.difficulty("s.t0")) == (4.0, 2.5)


def test_roots_nearest_the_band_are_scored_first() -> None:
    curriculum = curriculum_with([1, 9, 2])
    curriculum.next_statement()
    assert [root.name for root in curriculum.roots_to_score(window=4, limit=2)] == ["s.t2", "s.t1"]


def test_a_new_value_model_makes_every_root_stale_again() -> None:
    curriculum = curriculum_with([1, 2])
    curriculum.set_root_values({"s.t0": 1.0, "s.t1": 2.0}, version=0)
    curriculum.value_version = 1
    assert len(curriculum.roots_to_score(window=10, limit=10)) == 2


def test_the_scheduler_feeds_the_curriculum_and_reports_outcomes() -> None:
    curriculum = curriculum_with([1] * 4 + [2] * 4)
    scheduler = Scheduler(SchedulerConfig(), curriculum)
    for _ in range(5):
        job = scheduler.next_job()
        assert job is not None
        scheduler.record(attempt(job.name, proved=True, decision=Decision.SOLVED))
    assert curriculum.band_low == 2.0


def test_a_load_failure_leaves_room_in_the_curriculum_cohort() -> None:
    curriculum = curriculum_with([1] * 6 + [2] * 4)
    scheduler = Scheduler(SchedulerConfig(), curriculum)
    for number in range(6):
        job = scheduler.next_job()
        assert job is not None
        decision = Decision.RETIRED_LOAD_FAILURE if number == 0 else Decision.SOLVED
        scheduler.record(attempt(job.name, proved=number > 0, decision=decision))
    assert curriculum.band_low == 2.0


def test_the_open_pool_gets_its_share_of_fresh_starts() -> None:
    curriculum = curriculum_with([1] * 10)
    scheduler = Scheduler(SchedulerConfig(), curriculum, open_share=0.25)
    scheduler.add_statements([StatementRecord("open", f"o{number}", "", "", "", "") for number in range(10)])
    sources = [job.statement.source for job in (scheduler.next_job() for _ in range(8)) if job]
    assert sources.count("open") == 2


def test_replayed_attempts_leave_the_curriculum() -> None:
    curriculum = curriculum_with([1, 1])
    scheduler = Scheduler(SchedulerConfig(), curriculum)
    scheduler.replay([attempt("s.t0", decision=Decision.RETIRED_UNPROMISING)])
    assert [job.name for job in (scheduler.next_job(), scheduler.next_job()) if job] == ["s.t1"]


def test_a_band_far_above_the_target_moves_in_bigger_steps() -> None:
    config = dataclasses.replace(CONFIG, fast_raise_solve_rate=0.8, fast_band_step=1.5)
    curriculum = curriculum_with([1] * 5 + [2] * 8 + [3] * 8, config)
    outcomes(curriculum, [True] * 5)
    assert curriculum.band_low == 2.5


def indexed(number: int, tactics: int) -> IndexedStatement:
    statement = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return IndexedStatement(statement, tactics, 10 * tactics)


def test_unverified_statements_are_fed_as_such() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    curriculum.add_unverified([indexed(0, 2)], started=set())
    curriculum.next_statement()
    assert curriculum.counts().unverified_outcomes.fed == 1


def test_a_failed_verification_takes_an_unverified_statement_out() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    curriculum.add_unverified([indexed(0, 2), indexed(1, 2)], started=set())
    curriculum.add([verified(0, 2, is_verified=False)], started=set())
    assert curriculum.available == {"s.t1"}


def test_a_later_verification_certifies_an_unverified_statement() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    curriculum.add_unverified([indexed(0, 2)], started=set())
    curriculum.add([verified(0, 3)], started=set())
    assert (curriculum.is_verified("s.t0"), curriculum.statements["s.t0"].proof_tactics) == (True, 3)


def test_outcomes_are_counted_by_verification() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    curriculum.add([verified(0, 1)], started=set())
    curriculum.add_unverified([indexed(1, 1), indexed(2, 1)], started=set())
    for _ in range(3):
        statement = curriculum.next_statement()
        assert statement is not None
        curriculum.record_outcome(problem_name(statement), curriculum.is_verified(problem_name(statement)))
    counts = curriculum.counts()
    assert (counts.verified_outcomes.solve_rate, counts.unverified_outcomes.solve_rate) == (1.0, 0.0)


def test_only_verified_roots_are_scored() -> None:
    curriculum = Curriculum(CONFIG, value_version=0)
    curriculum.add([verified(0, 1)], started=set())
    curriculum.add_unverified([indexed(1, 1)], started=set())
    assert [root.name for root in curriculum.roots_to_score(window=10, limit=10)] == ["s.t0"]
