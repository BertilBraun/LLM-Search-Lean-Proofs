"""Goals to premises: encode the goals, search the index; concurrent searches share forward passes."""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.index import PremiseIndex
from lean_search.retrieval.premises import RetrievedPremise, serialize_goals
from lean_search.retrieval.statistics import BatchStatistics


class GoalRetriever:
    def __init__(self, encoder: TextEncoder, index: PremiseIndex) -> None:
        self.encoder = encoder
        self.index = index

    def retrieve(self, goal_lists: Sequence[Sequence[str]], count: int) -> list[tuple[RetrievedPremise, ...]]:
        queries = self.encoder.encode([serialize_goals(goals) for goals in goal_lists])
        return self.index.search(queries.to(self.index.embeddings.device), count)


@dataclass
class _Request:
    goals: tuple[str, ...]
    future: asyncio.Future[tuple[RetrievedPremise, ...]]


class BatchingRetriever:
    """Requests that arrive while a batch is encoded form the next batch; encoding runs in a worker thread."""

    def __init__(self, retriever: GoalRetriever, count: int, max_batch_goals: int) -> None:
        self.retriever = retriever
        self.count = count
        self.max_batch_goals = max_batch_goals
        self.statistics = BatchStatistics()
        self._pending: list[_Request] = []
        self._worker: asyncio.Task[None] | None = None

    async def retrieve(self, goals: Sequence[str]) -> tuple[RetrievedPremise, ...]:
        future: asyncio.Future[tuple[RetrievedPremise, ...]] = asyncio.get_running_loop().create_future()
        self._pending.append(_Request(tuple(goals), future))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())
        return await future

    async def _drain(self) -> None:
        while self._pending:
            batch = self._pending[: self.max_batch_goals]
            self._pending = self._pending[self.max_batch_goals :]
            started = time.monotonic()
            try:
                results = await asyncio.to_thread(
                    self.retriever.retrieve, [request.goals for request in batch], self.count
                )
            except Exception as error:
                for request in batch:
                    if not request.future.done():
                        request.future.set_exception(error)
                continue
            self.statistics.batches += 1
            self.statistics.goals += len(batch)
            self.statistics.seconds += time.monotonic() - started
            # A request whose search was cancelled meanwhile has a cancelled future.
            for request, result in zip(batch, results, strict=True):
                if not request.future.done():
                    request.future.set_result(result)
