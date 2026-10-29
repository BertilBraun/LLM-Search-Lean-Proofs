"""A fixed-size pool of Lean REPL processes shared by many concurrent proof searches in one asyncio program."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Sequence

from lean_search.lean.repl import LeanRepl, LeanReplConfig, MemoryUsage

logger = logging.getLogger(__name__)


class LeanReplPool:
    """Processes past `restart_fraction` of their limits, or whose user raised, are restarted before reuse."""

    def __init__(
        self,
        size: int,
        config: LeanReplConfig | None = None,
        restart_fraction: float = 0.5,
        restart_attempts: int = 3,
        restart_backoff_seconds: float = 2.0,
    ) -> None:
        self.repls = [LeanRepl(config) for _ in range(size)]
        self.restart_fraction = restart_fraction
        self.restart_attempts = restart_attempts
        self.restart_backoff_seconds = restart_backoff_seconds
        self._headers: list[str] = []
        self._idle: asyncio.Queue[LeanRepl] = asyncio.Queue()
        self._restarts: set[asyncio.Task[None]] = set()
        self._closed = False
        for repl in self.repls:
            self._idle.put_nowait(repl)

    async def __aenter__(self) -> "LeanReplPool":
        await self.start()
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        await self.close()

    async def start(self, headers: Sequence[str] = ()) -> None:
        self._headers = list(dict.fromkeys([*self._headers, *headers]))
        await asyncio.gather(*(self._prepare(repl) for repl in self.repls))

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[LeanRepl]:
        repl = await self._idle.get()
        try:
            yield repl
        except BaseException:
            # The body may have been cancelled mid-request, so never hand this process out unrestarted.
            self._schedule_restart(repl)
            raise
        if repl.needs_restart or repl.exceeds_limits(self.restart_fraction):
            self._schedule_restart(repl)
        else:
            self._idle.put_nowait(repl)

    async def stop_processes(self, above_anonymous_bytes: int) -> list[MemoryUsage]:
        """Stops every process (in use or idle) at or above the private memory; returns what each held."""
        usages = [(repl, repl.memory_usage()) for repl in self.repls if repl.process_id is not None]
        stopping = [(repl, usage) for repl, usage in usages if usage.anonymous_bytes >= above_anonymous_bytes]
        await asyncio.gather(*(repl.stop() for repl, _ in stopping))
        return [usage for _, usage in stopping]

    async def close(self) -> None:
        """Cancels and awaits the restarts and stops every process; REPLs still in use raise on their next call."""
        self._closed = True
        for restart in self._restarts:
            restart.cancel()
        await asyncio.gather(*self._restarts, return_exceptions=True)
        await asyncio.gather(*(repl.close() for repl in self.repls))

    async def _prepare(self, repl: LeanRepl) -> None:
        await repl.start()
        for header in self._headers:
            await repl.load_header(header)

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
            self._idle.put_nowait(repl)
