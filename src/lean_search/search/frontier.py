import heapq
import math
from collections.abc import Callable
from typing import NamedTuple


class FrontierEntry(NamedTuple):
    priority: float
    insertion: int
    node_id: int


class Frontier:
    """Min-priority queue of node ids; equal priorities pop in insertion order."""

    def __init__(self) -> None:
        self._heap: list[FrontierEntry] = []
        self._insertions = 0

    def __len__(self) -> int:
        return len(self._heap)

    def push(self, node_id: int, priority: float) -> None:
        assert not math.isnan(priority), node_id
        heapq.heappush(self._heap, FrontierEntry(priority, self._insertions, node_id))
        self._insertions += 1

    def pop(self) -> int:
        return heapq.heappop(self._heap).node_id

    def pop_at_rank(self, rank: int) -> int:
        """The node id at this rank in priority order (0: the best), removed; the others keep their order."""
        better = [heapq.heappop(self._heap) for _ in range(rank)]
        chosen = heapq.heappop(self._heap)
        for entry in better:
            heapq.heappush(self._heap, entry)
        return chosen.node_id

    def pop_best_where(self, accepts: Callable[[int], bool]) -> int | None:
        """The best node id that `accepts`, removed; None when there is none."""
        for entry in sorted(self._heap):
            if accepts(entry.node_id):
                self._heap.remove(entry)
                heapq.heapify(self._heap)
                return entry.node_id
        return None

    def node_ids(self) -> list[int]:
        return [entry.node_id for entry in sorted(self._heap)]
