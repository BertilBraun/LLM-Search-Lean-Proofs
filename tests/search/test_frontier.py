import pytest

from lean_search.search import Frontier


def test_lower_priority_pops_first() -> None:
    frontier = Frontier()
    for node_id, priority in [(0, 3.0), (1, 1.0), (2, 2.0)]:
        frontier.push(node_id, priority)
    assert [frontier.pop() for _ in range(3)] == [1, 2, 0]


def test_equal_priorities_pop_in_insertion_order() -> None:
    frontier = Frontier()
    for node_id in [5, 3, 9, 1]:
        frontier.push(node_id, 1.0)
    assert [frontier.pop() for _ in range(4)] == [5, 3, 9, 1]


def test_tie_breaking_ignores_node_ids() -> None:
    frontier = Frontier()
    frontier.push(7, 2.0)
    frontier.push(2, 1.0)
    frontier.push(1, 2.0)
    assert frontier.node_ids() == [2, 7, 1]


def test_length_counts_pending_nodes() -> None:
    frontier = Frontier()
    frontier.push(0, 0.0)
    frontier.push(1, 0.0)
    frontier.pop()
    assert len(frontier) == 1


def ranked_frontier() -> Frontier:
    frontier = Frontier()
    for node_id, priority in [(0, 3.0), (1, 1.0), (2, 2.0), (3, 4.0)]:
        frontier.push(node_id, priority)
    return frontier


@pytest.mark.parametrize(("rank", "node_id"), [(0, 1), (1, 2), (3, 3)])
def test_pop_at_rank_takes_the_node_at_that_rank(rank: int, node_id: int) -> None:
    assert ranked_frontier().pop_at_rank(rank) == node_id


def test_pop_at_rank_keeps_the_order_of_the_others() -> None:
    frontier = ranked_frontier()
    frontier.pop_at_rank(1)
    assert frontier.node_ids() == [1, 0, 3]


def test_pop_best_where_takes_the_best_accepted_node() -> None:
    assert ranked_frontier().pop_best_where(lambda node_id: node_id % 2 == 0) == 2


def test_pop_best_where_keeps_the_rejected_nodes() -> None:
    frontier = ranked_frontier()
    frontier.pop_best_where(lambda node_id: node_id % 2 == 0)
    assert frontier.node_ids() == [1, 0, 3]


def test_pop_best_where_without_an_accepted_node_is_none() -> None:
    assert ranked_frontier().pop_best_where(lambda node_id: node_id > 10) is None
