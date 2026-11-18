"""A fixed-size pool of Lean REPL processes shared by many concurrent proof searches in one asyncio program."""

import asyncio
import collections
import contextlib
import itertools
import logging
from collections.abc import AsyncIterator, Callable, Sequence

from lean_search.lean.repl import LeanRepl, LeanReplConfig, MemoryUsage

logger = logging.getLogger(__name__)


class SpareProcesses:
    """Up to `count` started REPL processes with the pool's headers loaded, each handed to a REPL that must replace its
    process (a wall-clock kill, a crash, a limit, or its first use after the pool stopped it) and replaced in the
    background. They run on the CPUs of the process that starts them, like the pool's own. A start that fails is tried
    again after `retry_seconds`, doubling with every failure in a row up to `max_retry_seconds`."""

    def __init__(
        self,
        count: int,
        config: LeanReplConfig | None,
        headers: Callable[[], Sequence[str]],
        retry_seconds: float = 5.0,
        max_retry_seconds: float = 600.0,
    ) -> None:
        self.count = count
        self.config = config
        self.retry_seconds = retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self._headers = headers
        self._ready: collections.deque[LeanRepl] = collections.deque()
        self._starting: set[asyncio.Task[None]] = set()
        # Dead spares being closed: not counted as starting, never cancelled.
        self._closing: set[asyncio.Task[None]] = set()
        self._closed = False
        self._failed_starts = 0

    @property
    def ready(self) -> int:
        return len(self._ready)

    def ready_process_ids(self) -> list[int]:
        return [process_id for spare in self._ready if (process_id := spare.process_id) is not None]

    def fill(self) -> None:
        while not self._closed and len(self._ready) + len(self._starting) < self.count:
            start = asyncio.create_task(self._start_one())
            self._starting.add(start)
            start.add_done_callback(self._starting.discard)

    def take(self) -> LeanRepl | None:
        """A ready spare, or None while none is ready (the caller then starts its own process)."""
        spare = None
        while self._ready and spare is None:
            candidate = self._ready.popleft()
            if candidate.needs_restart:
                self._close_later(candidate)
            else:
                spare = candidate
        self.fill()
        return spare

    async def close(self) -> None:
        self._closed = True
        for start in self._starting:
            start.cancel()
        await asyncio.gather(*self._starting, return_exceptions=True)
        ready, self._ready = list(self._ready), collections.deque()
        await asyncio.gather(*(spare.close() for spare in ready))
        # A REPL still in use while the pool closes can hand back a dead spare to close meanwhile.
        while self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    async def _start_one(self) -> None:
        spare = LeanRepl(self.config)
        try:
            await spare.start()
            for header in self._headers():
                await spare.load_header(header)
        except asyncio.CancelledError:
            await spare.close()
            raise
        except Exception:
            self._failed_starts += 1
            delay = min(self.retry_seconds * 2 ** (self._failed_starts - 1), self.max_retry_seconds)
            if self._failed_starts == 1:
                logger.exception("Starting a spare Lean REPL failed; trying again in %g s", delay)
            else:
                logger.warning(
                    "Starting a spare Lean REPL failed again (%d failures in a row); trying again in %g s",
                    self._failed_starts,
                    delay,
                )
            await spare.close()
            await asyncio.sleep(delay)
            current = asyncio.current_task()
            assert current is not None
            self._starting.discard(current)
            self.fill()
            return
        self._failed_starts = 0
        if self._closed:
            await spare.close()
            return
        self._ready.append(spare)

    def _close_later(self, spare: LeanRepl) -> None:
        closing = asyncio.create_task(spare.close())
        self._closing.add(closing)
        closing.add_done_callback(self._closing.discard)


class LeanReplPool:
    """Processes past `restart_fraction` of their limits, or whose user raised, are restarted before reuse. The most
    recently released REPL is handed out first, so stopped idle processes start again only when demand needs them.
    `spare_processes` warm processes (started with `start`) replace a process that must be replaced mid-use."""

    def __init__(
        self,
        size: int,
        config: LeanReplConfig | None = None,
        restart_fraction: float = 0.5,
        restart_attempts: int = 3,
        restart_backoff_seconds: float = 2.0,
        spare_processes: int = 0,
    ) -> None:
        self.spares = SpareProcesses(spare_processes, config, lambda: self._headers) if spare_processes else None
        self.repls = [LeanRepl(config, self.spares) for _ in range(size)]
        self.restart_fraction = restart_fraction
        self.restart_attempts = restart_attempts
        self.restart_backoff_seconds = restart_backoff_seconds
        self._headers: list[str] = []
        self._idle: asyncio.LifoQueue[LeanRepl] = asyncio.LifoQueue()
        # In use or restarting (the others wait in `_idle`); the release order, so the longest idle stop first.
        self._busy: set[LeanRepl] = set()
        self._releases = itertools.count()
        self._released_at: dict[LeanRepl, int] = {}
        self._restarts: set[asyncio.Task[None]] = set()
        self._closed = False
        for repl in self.repls:
            self._release(repl)

    async def __aenter__(self) -> "LeanReplPool":
        await self.start()
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        await self.close()

    def spare_text(self) -> str:
        """How the spare processes served the pool's REPLs so far; empty without spares."""
        if self.spares is None:
            return ""
        swaps = sum(repl.spare_swaps for repl in self.repls)
        misses = sum(repl.spare_misses for repl in self.repls)
        return (
            f"spare REPL processes {self.spares.ready} of {self.spares.count} ready; {swaps} replacements took one, "
            f"{misses} found none ready"
        )

    async def start(self, headers: Sequence[str] = ()) -> None:
        self._headers = list(dict.fromkeys([*self._headers, *headers]))
        await asyncio.gather(*(self._prepare(repl) for repl in self.repls))
        if self.spares is not None:
            self.spares.fill()

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[LeanRepl]:
        repl = await self._idle.get()
        self._busy.add(repl)
        try:
            yield repl
        except BaseException:
            # The body may have been cancelled mid-request, so never hand this process out unrestarted.
            self._schedule_restart(repl)
            raise
        if repl.needs_restart or repl.exceeds_limits(self.restart_fraction):
            self._schedule_restart(repl)
        else:
            self._release(repl)

    async def stop_processes(self, above_anonymous_bytes: int) -> list[MemoryUsage]:
        """Stops every process (in use or idle) at or above the private memory; returns what each held."""
        usages = [(repl, repl.memory_usage()) for repl in self.repls if repl.process_id is not None]
        stopping = [(repl, usage) for repl, usage in usages if usage.anonymous_bytes >= above_anonymous_bytes]
        await asyncio.gather(*(repl.stop() for repl, _ in stopping))
        return [usage for _, usage in stopping]

    async def stop_idle_processes(self, keep_running: int) -> list[MemoryUsage]:
        """Stops idle processes, the longest idle first, until at most `keep_running` processes run (those in use are
        never stopped); they start again on their next use. Returns what each held."""
        running = [repl for repl in self.repls if repl.process_id is not None]
        idle = sorted((repl for repl in running if repl not in self._busy), key=self._released_at.__getitem__)
        stopping = [(repl, repl.memory_usage()) for repl in idle[: max(0, len(running) - keep_running)]]
        await asyncio.gather(*(repl.stop() for repl, _ in stopping))
        return [usage for _, usage in stopping]

    async def close(self) -> None:
        """Cancels and awaits the restarts and stops every process; REPLs still in use raise on their next call."""
        self._closed = True
        for restart in self._restarts:
            restart.cancel()
        await asyncio.gather(*self._restarts, return_exceptions=True)
        if self.spares is not None:
            await self.spares.close()
        await asyncio.gather(*(repl.close() for repl in self.repls))

    async def _prepare(self, repl: LeanRepl) -> None:
        await repl.start()
        for header in self._headers:
            await repl.load_header(header)

    def _release(self, repl: LeanRepl) -> None:
        self._busy.discard(repl)
        self._released_at[repl] = next(self._releases)
        self._idle.put_nowait(repl)

    def _schedule_restart(self, repl: LeanRepl) -> None:
        # A task started after close would outlive the pool, and asyncio's shutdown can hang cancelling a process start.
        if self._closed:
            return
        restart = asyncio.create_task(self._restart(repl))
        self._restarts.add(restart)
        restart.add_done_callback(self._restarts.discard)

    async def _restart(self, repl: LeanRepl) -> None:
        try:
            for attempt in range(self.restart_attempts):
                if attempt:
                    await asyncio.sleep(self.restart_backoff_seconds * 2 ** (attempt - 1))
                try:
                    await repl.restart()
                    await self._prepare(repl)
                    return
                except Exception:
                    logger.exception("Restarting a pooled Lean REPL failed (attempt %d)", attempt + 1)
        finally:
            # Even after failed attempts the slot returns: the REPL retries its start on use and reports ReplFailure.
            self._release(repl)
