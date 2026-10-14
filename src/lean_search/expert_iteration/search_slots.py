"""The service's search slots: how many searches run, how many of them past stage 0, and who waits for a later stage.

A search that qualifies for its next stage while the escalated slots are taken gives up its active slot and waits,
keeping its tree and its REPL's proof states, in a queue ordered by its best frontier h (lowest first). When an
escalated search ends, the most promising waiter resumes in its place, ahead of fresh statements. Past
`max_waiting`, the least promising waiter is retired.
"""

import asyncio
import itertools
from dataclasses import dataclass, field


@dataclass
class SlotLease:
    """A search's hold on the slots: active while it runs, escalated once it was let past stage 0."""

    active: bool = True
    escalated: bool = False


@dataclass(order=True)
class _Waiter:
    priority: float
    sequence: int
    lease: SlotLease = field(compare=False)
    granted: asyncio.Future[bool] = field(compare=False)


class SearchSlots:
    def __init__(self, capacity: int, escalated_capacity: int, max_waiting: int) -> None:
        self.capacity = capacity
        self.escalated_capacity = escalated_capacity
        self.max_waiting = max_waiting
        self.active = 0
        self.escalated = 0
        self.waiters: list[_Waiter] = []
        self.sequence = itertools.count()
        self.freed = asyncio.Event()

    @property
    def waiting(self) -> int:
        return len(self.waiters)

    async def start(self) -> SlotLease:
        """An active slot for a fresh statement; waiters that can resume took theirs already."""
        while self.active >= self.capacity:
            await self.freed.wait()
        self.active += 1
        return SlotLease()

    async def escalate(self, lease: SlotLease, priority: float) -> bool:
        """Whether the search goes on into its next stage, at once or after waiting; False retires it."""
        assert lease.active, "only a running search escalates"
        if lease.escalated:
            return True
        if self.escalated < self.escalated_capacity:
            self.escalated += 1
            lease.escalated = True
            return True
        if self.max_waiting == 0:
            return False
        waiter = _Waiter(priority, next(self.sequence), lease, asyncio.get_running_loop().create_future())
        self.waiters.append(waiter)
        lease.active = False
        self.active -= 1
        if len(self.waiters) > self.max_waiting:
            least_promising = max(self.waiters)
            self.waiters.remove(least_promising)
            least_promising.granted.set_result(False)
        self._changed()
        return await waiter.granted

    def finish(self, lease: SlotLease) -> None:
        if lease.active:
            self.active -= 1
        if lease.escalated:
            self.escalated -= 1
        lease.active = lease.escalated = False
        self._changed()

    def _changed(self) -> None:
        while self.waiters and self.escalated < self.escalated_capacity and self.active < self.capacity:
            best = min(self.waiters)
            self.waiters.remove(best)
            self.active += 1
            self.escalated += 1
            best.lease.active = best.lease.escalated = True
            best.granted.set_result(True)
        # Wakes every fresh start waiting for a slot; a new event serves the next round.
        self.freed.set()
        self.freed = asyncio.Event()
