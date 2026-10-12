"""Pausing, sleeping and in-place weight swaps of vLLM servers in dev mode (serve_model.sh, deployment/README.md)."""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

RELOAD_TIMEOUT_SECONDS = 900.0


@dataclass(frozen=True)
class PhaseSeconds:
    pause: float
    weights: float
    resume: float

    @property
    def total(self) -> float:
        return self.pause + self.weights + self.resume


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
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        started = time.monotonic()
        await post(http, "/pause", params={"mode": "wait"})
        paused = time.monotonic()
        await reload_weights(http, weights_directory)
        await reset_prefix_cache(http)
        reloaded = time.monotonic()
        await post(http, "/resume")
        return PhaseSeconds(paused - started, reloaded - paused, time.monotonic() - reloaded)


async def release_gpu(server_url: str) -> PhaseSeconds:
    """Drains the server and discards its weights and KV cache (sleep level 2); new requests wait for restore_gpu."""
    async with httpx.AsyncClient(base_url=server_root(server_url), timeout=RELOAD_TIMEOUT_SECONDS) as http:
        started = time.monotonic()
        await post(http, "/pause", params={"mode": "wait"})
        paused = time.monotonic()
        await post(http, "/sleep", params={"level": 2})
        return PhaseSeconds(paused - started, time.monotonic() - paused, 0.0)


async def restore_gpu(server_url: str, weights_directory: Path) -> PhaseSeconds:
    """Reallocates a released server's memory, loads the given weights (the old or new ones) and resumes."""
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
