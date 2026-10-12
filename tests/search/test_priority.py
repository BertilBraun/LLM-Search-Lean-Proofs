import pytest
from search_trees import add_child, new_tree

from lean_search.search import (
    AStar,
    CumulativeLogProbability,
    DepthPlusGoals,
    GoalCountEstimator,
    PriorityConfig,
    PriorityKind,
    StepSource,
    build_priority_function,
)


async def test_depth_plus_goals_adds_depth_and_open_goals() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q", "⊢ r", "⊢ s"))
    grandchild = add_child(tree, child, ("⊢ r", "⊢ s", "⊢ t"))
    scores = await DepthPlusGoals().score([grandchild], tree)
    assert scores.priorities == (5.0,)


async def test_cumulative_log_probability_of_the_root_is_zero() -> None:
    tree = new_tree("⊢ p")
    scores = await CumulativeLogProbability(1.0, -1.0).score([tree.root], tree)
    assert scores.priorities == (0.0,)


@pytest.mark.parametrize(("length_exponent", "expected"), [(0.0, 1.5), (1.0, 0.75), (2.0, 0.375)])
async def test_cumulative_log_probability_is_length_normalized(length_exponent: float, expected: float) -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",))
    grandchild = add_child(tree, child, ("⊢ r",), step="exact h", source=StepSource.POLICY, log_probability=-0.5)
    scores = await CumulativeLogProbability(length_exponent, -1.0).score([grandchild], tree)
    assert scores.priorities == (pytest.approx(expected),)


async def test_cumulative_log_probability_prefers_likely_paths() -> None:
    tree = new_tree("⊢ p")
    likely = add_child(tree, tree.root, ("⊢ q",), step="a", source=StepSource.POLICY, log_probability=-0.1)
    unlikely = add_child(tree, tree.root, ("⊢ r",), step="b", source=StepSource.POLICY, log_probability=-2.0)
    scores = await CumulativeLogProbability(1.0, -1.0).score([likely, unlikely], tree)
    assert scores.priorities[0] < scores.priorities[1]


async def test_a_star_adds_weighted_value_estimate_to_depth() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q", "⊢ r"))
    scores = await AStar(GoalCountEstimator(), value_weight=0.5).score([child], tree)
    assert scores.priorities == (2.0,)


async def test_a_star_reports_the_value_estimates() -> None:
    tree = new_tree("⊢ p")
    first = add_child(tree, tree.root, ("⊢ q", "⊢ r"))
    second = add_child(tree, tree.root, ("⊢ s",), step="norm_num")
    scores = await AStar(GoalCountEstimator(), value_weight=1.0).score([first, second], tree)
    assert scores.value_estimates == (2.0, 1.0)


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [
        (PriorityKind.DEPTH_PLUS_GOALS, DepthPlusGoals),
        (PriorityKind.CUMULATIVE_LOG_PROBABILITY, CumulativeLogProbability),
        (PriorityKind.A_STAR, AStar),
    ],
)
def test_priority_function_is_built_from_its_kind(kind: PriorityKind, expected_type: type) -> None:
    assert type(build_priority_function(PriorityConfig(kind=kind))) is expected_type


async def test_a_star_weighs_depth_and_value_estimate() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q", "⊢ r"))
    scores = await AStar(GoalCountEstimator(), value_weight=1.0, depth_weight=0.25).score([child], tree)
    assert scores.priorities == (2.25,)


async def test_a_star_policy_prior_penalizes_unlikely_paths() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="a", source=StepSource.POLICY, log_probability=-2.0)
    scores = await AStar(GoalCountEstimator(), value_weight=1.0, policy_prior_weight=0.5).score([child], tree)
    assert scores.priorities == (pytest.approx(1.0 + 1.0 + 0.5 * 2.0),)


async def test_the_configured_a_star_keeps_the_old_priority_by_default() -> None:
    tree = new_tree("⊢ p")
    child = add_child(tree, tree.root, ("⊢ q",), step="a", source=StepSource.POLICY, log_probability=-2.0)
    function = build_priority_function(PriorityConfig(kind=PriorityKind.A_STAR, value_weight=0.5))
    assert (await function.score([child], tree)).priorities == (1.5,)
