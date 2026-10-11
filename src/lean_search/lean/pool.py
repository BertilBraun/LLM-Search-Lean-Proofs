"""A fixed-size pool of Lean REPL processes shared by many concurrent proof searches in one asyncio program."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence

from lean_search.lean.repl import LeanRepl, LeanReplConfig


class LeanReplPool:
    def __init__(self, size: int, config: LeanReplConfig | None = None) -> None:
        self.repls = [LeanRepl(config) for _ in range(size)]
        self._idle: asyncio.Queue[LeanRepl] = asyncio.Queue()
        for repl in self.repls:
            self._idle.put_nowait(repl)

    async def __aenter__(self) -> "LeanReplPool":
        await self.start()
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        await self.close()

    async def start(self, headers: Sequence[str] = ()) -> None:
        await asyncio.gather(*(self._prepare(repl, headers) for repl in self.repls))

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[LeanRepl]:
        repl = await self._idle.get()
        try:
            yield repl
        finally:
            self._idle.put_nowait(repl)

    async def close(self) -> None:
        await asyncio.gather(*(repl.close() for repl in self.repls))

    @staticmethod
    async def _prepare(repl: LeanRepl, headers: Sequence[str]) -> None:
        await repl.start()
        for header in headers:
            await repl.load_header(header)
