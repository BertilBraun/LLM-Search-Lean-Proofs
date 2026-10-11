"""A fixed-size pool of Lean REPL processes shared by many concurrent proof searches in one asyncio program."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence

from lean_search.lean.repl import LeanRepl, LeanReplConfig


class LeanReplPool:
    """Processes past `restart_fraction` of their limits are restarted on release, so restarts fall between uses."""

    def __init__(self, size: int, config: LeanReplConfig | None = None, restart_fraction: float = 0.5) -> None:
        self.repls = [LeanRepl(config) for _ in range(size)]
        self.restart_fraction = restart_fraction
        self._headers: list[str] = []
        self._idle: asyncio.Queue[LeanRepl] = asyncio.Queue()
        self._restarts: set[asyncio.Task[None]] = set()
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
        finally:
            if repl.exceeds_limits(self.restart_fraction):
                restart = asyncio.create_task(self._restart(repl))
                self._restarts.add(restart)
                restart.add_done_callback(self._restarts.discard)
            else:
                self._idle.put_nowait(repl)

    async def close(self) -> None:
        await asyncio.gather(*self._restarts)
        await asyncio.gather(*(repl.close() for repl in self.repls))

    async def _prepare(self, repl: LeanRepl) -> None:
        await repl.start()
        for header in self._headers:
            await repl.load_header(header)

    async def _restart(self, repl: LeanRepl) -> None:
        await repl.restart()
        await self._prepare(repl)
        self._idle.put_nowait(repl)
