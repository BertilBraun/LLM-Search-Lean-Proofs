"""Pausing, sleeping and in-place weight swaps of vLLM servers in dev mode (serve_model.sh, deployment/README.md).
Every sleep and in-place reload first marks the server (port_<port>.swapped in $LEAN_SEARCH_RUNS/servers/, removed by
serve_model.sh at a start): it may no longer hold the weights it started from."""

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from lean_search.policy.server_processes import mark_swapped

RELOAD_TIMEOUT_SECONDS = 900.0


@dataclass(frozen=True)
class PhaseSeconds:
    pause: float
    weights: float
    resume: float

    @property
    def total(self) -> float:
        return self.pause + self.weights + self.resume


def swap_marks_directory() -> Path:
    """serve_model.sh's directory, at the time of the call."""
    return Path(os.environ["LEAN_SEARCH_RUNS"]) / "servers"


def mark_server_swapped(server_url: str) -> None:
    port = urlparse(server_url).port
    assert port is not None, server_url
    mark_swapped(swap_marks_directory(), port)


def server_root(server_url: str) -> str:
    """The server's root URL from an OpenAI base URL such as http://127.0.0.1:8100/v1."""
    return server_url.rstrip("/").removesuffix("/v1")


async def post(http: httpx.AsyncClient, path: str, **request: object) -> httpx.Response:
    response = await http.post(path, **request)
    response.raise_for_status()
    return response


async def reset_prefix_cache(http: httpx.AsyncClient) -> None:
    # Fails while blocks are still held, e.g. right after the last request finished.
    while not (await post(http, "/reset_prefix_cache")).json()["success"]:
        await asyncio.sleep(0.5)


async def reload_weights(http: httpx.AsyncClient, weights_directory: Path) -> None:
    """Copies a checkpoint of the same architecture into the live parameters; CUDA graphs stay valid."""
    body = {
        "method": "reload_weights",
        "kwargs": {"weights_path": str(weights_directory)},
        "timeout": RELOAD_TIMEOUT_SECONDS,
    }
    await post(http, "/collective_rpc", json=body)


async def publish_weights(server_url: str, weights_directory: Path) -> PhaseSeconds:
    """Drains the server, swaps in the new weights, clears cached prefixes computed with the old ones, resumes."""
    mark_server_swapped(server_url)
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        started = time.monotonic()
        await post(http, "/pause", params={"mode": "wait"})
        paused = time.monotonic()
        await reload_weights(http, weights_directory)
        await reset_prefix_cache(http)
        reloaded = time.monotonic()
        await post(http, "/resume")
        return PhaseSeconds(paused - started, reloaded - paused, time.monotonic() - reloaded)


async def is_sleeping(server_url: str) -> bool:
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=30.0) as http:
        response = await http.get("/is_sleeping")
        response.raise_for_status()
        return bool(response.json()["is_sleeping"])


async def is_healthy(server_url: str) -> bool:
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=10.0) as http:
        try:
            return (await http.get("/health")).status_code == 200
        except httpx.TransportError:
            return False


async def release_gpu(server_url: str) -> PhaseSeconds:
    """Drains the server and discards its weights and KV cache (sleep level 2); new requests wait for restore_gpu."""
    mark_server_swapped(server_url)
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        started = time.monotonic()
        await post(http, "/pause", params={"mode": "wait"})
        paused = time.monotonic()
        await post(http, "/sleep", params={"level": 2})
        return PhaseSeconds(paused - started, time.monotonic() - paused, 0.0)


async def restore_gpu(server_url: str, weights_directory: Path) -> PhaseSeconds:
    """Reallocates a released server's memory, loads the given weights (the old or new ones) and resumes."""
    mark_server_swapped(server_url)
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        started = time.monotonic()
        await post(http, "/wake_up", params={"tags": "weights"})
        await reload_weights(http, weights_directory)
        await post(http, "/wake_up", params={"tags": "kv_cache"})
        await reset_prefix_cache(http)
        reloaded = time.monotonic()
        await post(http, "/resume")
        return PhaseSeconds(0.0, reloaded - started, time.monotonic() - reloaded)


async def replace_adapter(server_url: str, name: str, adapter_directory: Path) -> None:
    """Registers an adapter under `name`, replacing any earlier one (a weight reload drops the workers' adapters)."""
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        await http.post("/v1/unload_lora_adapter", json={"lora_name": name})
        await post(http, "/v1/load_lora_adapter", json={"lora_name": name, "lora_path": str(adapter_directory)})
