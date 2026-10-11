import heapq
import math
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

    def node_ids(self) -> list[int]:
        return [entry.node_id for entry in sorted(self._heap)]
