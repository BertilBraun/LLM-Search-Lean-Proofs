import pytest

from lean_search.rl.host_memory import BudgetStage, HostMemoryTerms, budget_conditions, budget_text

TERMS = HostMemoryTerms(total=128.0, repl_p90=0.5, vllm=25.0, parked=14.0, handoff=14.0, rank=6.0, merge=10.0)


def used(terms: HostMemoryTerms, stage: BudgetStage, ranks: int = 4) -> float:
    conditions = budget_conditions(terms, loop_concurrency=112, evaluation_concurrency=64, training_ranks=ranks)
    return next(condition.used for condition in conditions if condition.stage == stage)


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (BudgetStage.SAMPLING, 112 * 0.5 + 25.0 + 14.0 + 14.0),
        (BudgetStage.TRAINING, 25.0 + 4 * 6.0 + 14.0 + 14.0),
        (BudgetStage.PUBLISHING, 112 * 0.5 + 25.0 + 10.0 + 14.0 + 14.0),
        (BudgetStage.EVALUATING, 64 * 0.5 + 25.0 + 14.0),
    ],
)
def test_each_stage_adds_up_its_terms(stage: BudgetStage, expected: float) -> None:
    assert used(TERMS, stage) == pytest.approx(expected)


def test_the_parked_weights_count_once_whatever_the_ranks() -> None:
    assert used(TERMS, BudgetStage.TRAINING, ranks=4) - used(TERMS, BudgetStage.TRAINING, ranks=1) == 3 * TERMS.rank


def test_the_limit_is_85_percent_of_the_memory() -> None:
    conditions = budget_conditions(TERMS, 112, 64, 4)
    assert {condition.limit for condition in conditions} == {0.85 * 128.0}


def test_a_condition_over_the_limit_is_flagged() -> None:
    crowded = HostMemoryTerms(total=128.0, repl_p90=1.0, vllm=25.0, parked=14.0, handoff=14.0)
    assert "sampling 165/109 OVER" in budget_text(budget_conditions(crowded, 112, 64, 4))
