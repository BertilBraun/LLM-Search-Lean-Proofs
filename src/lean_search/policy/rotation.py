"""The servers of one model taken in turn, each request by the next; a server that fails a request with a server error
(no answer, or a 5xx) is left out of the turn until its /health answers again, so that one dead server does not fail
every search in flight (each search sends requests to every server in turn). The failed request itself still raises.

Given a `RequestFailures`, the rotation also counts each server's server errors in a row (by URL; a success ends the
streak), so that a standalone evaluation's recovery can tell a server that answers /health but fails its requests from
one that only stumbled."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterator, Sequence

import httpx

from lean_search.policy.client import PolicyClient
from lean_search.policy.server_control import is_healthy

HEALTH_RECHECK_SECONDS = 5.0


def is_server_error(error: httpx.HTTPError) -> bool:
    """A failure of the server rather than of the request."""
    match error:
        case httpx.HTTPStatusError():
            return error.response.status_code >= 500
        case httpx.TransportError():
            return True
        case _:
            return False


class RequestFailures:
    """Server errors in a row per server URL, shared by the rotations of an evaluation's clients."""

    def __init__(self) -> None:
        self.streaks: dict[str, int] = {}

    def failed(self, server_url: str) -> None:
        self.streaks[server_url] = self.streaks.get(server_url, 0) + 1

    def succeeded(self, server_url: str) -> None:
        self.streaks.pop(server_url, None)

    def streak(self, server_url: str) -> int:
        return self.streaks.get(server_url, 0)


class ServerRotation:
    def __init__(
        self,
        clients: Sequence[PolicyClient],
        healthy: Callable[[str], Awaitable[bool]] = is_healthy,
        recheck_seconds: float = HEALTH_RECHECK_SECONDS,
        request_failures: RequestFailures | None = None,
    ) -> None:
        self.clients = tuple(clients)
        self.request_failures = request_failures
        self.healthy = healthy
        self.recheck_seconds = recheck_seconds
        # A left-out client's index and the task that takes it back once its server answers.
        self.left_out: dict[int, asyncio.Task[None]] = {}
        self.next_index = 0
        self.closed = False

    def next_client(self) -> PolicyClient:
        """The next client in turn that is not left out; with every one left out, the next in turn (its request fails
        as it would have without the rotation)."""
        candidates = [(self.next_index + offset) % len(self.clients) for offset in range(len(self.clients))]
        index = next((index for index in candidates if index not in self.left_out), candidates[0])
        self.next_index = (index + 1) % len(self.clients)
        return self.clients[index]

    @contextlib.contextmanager
    def client(self) -> Iterator[PolicyClient]:
        """The next client; a server error inside leaves it out and is raised."""
        client = self.next_client()
        try:
            yield client
        except httpx.HTTPError as error:
            if is_server_error(error):
                if self.request_failures is not None:
                    self.request_failures.failed(client.server_url)
                self.leave_out(client)
            raise
        if self.request_failures is not None:
            self.request_failures.succeeded(client.server_url)

    def leave_out(self, client: PolicyClient) -> None:
        index = self.clients.index(client)
        if index not in self.left_out and not self.closed:
            self.left_out[index] = asyncio.create_task(self.take_back(index))

    async def take_back(self, index: int) -> None:
        while True:
            await asyncio.sleep(self.recheck_seconds)
            # A failing check (the client's own pool exhausted, say) keeps it out until the next one.
            with contextlib.suppress(Exception):
                if await self.healthy(self.clients[index].server_url):
                    break
        del self.left_out[index]

    async def close(self) -> None:
        self.closed = True
        watchers = list(self.left_out.values())
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
        self.left_out.clear()
