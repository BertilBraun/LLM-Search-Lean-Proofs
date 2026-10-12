import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from lean_search.policy import PolicyClient
from lean_search.policy.client import TRANSPORT_ATTEMPTS

COMPLETION = {
    "choices": [{"index": 0, "text": "rfl", "logprobs": {"token_logprobs": [-0.25]}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
}


@dataclass
class FlakyServer:
    """Closes the first connections without answering, like a server dropping a kept-alive connection."""

    dropped_connections: int
    connections: int = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        headers = await reader.readuntil(b"\r\n\r\n")
        length = next(
            int(line.split(b":")[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length")
        )
        await reader.readexactly(length)
        if self.connections > self.dropped_connections:
            body = json.dumps(COMPLETION).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        writer.close()
        await writer.wait_closed()


@contextlib.asynccontextmanager
async def flaky_server(dropped_connections: int) -> AsyncIterator[tuple[FlakyServer, str]]:
    state = FlakyServer(dropped_connections)
    server = await asyncio.start_server(state.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield state, f"http://127.0.0.1:{port}/v1"


async def generate_once(url: str) -> str:
    async with PolicyClient(url, "model") as client:
        generation = await client.generate("theorem t : True := by\n", sample_count=1, max_tokens=4)
    return generation.samples[0].text


async def test_a_request_succeeds_after_dropped_connections() -> None:
    async with flaky_server(dropped_connections=TRANSPORT_ATTEMPTS - 1) as (_, url):
        assert await generate_once(url) == "rfl"


async def test_a_server_that_keeps_dropping_connections_gets_a_bounded_number_of_attempts() -> None:
    async with flaky_server(dropped_connections=10) as (state, url):
        with pytest.raises(httpx.RemoteProtocolError):
            await generate_once(url)
    assert state.connections == TRANSPORT_ATTEMPTS
