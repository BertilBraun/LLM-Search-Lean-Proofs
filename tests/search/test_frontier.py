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
