"""Model versions, the "current" pointer, and the interfaces that publish weights and free the GPUs for training.

A training phase stops (or puts to sleep) every server (GpuRelease.release), trains, publishes version k + 1
(Publisher.prepare, then the versions log and models/current.json) and brings the servers back with it
(GpuRelease.restore). The adapters keep their served names across versions, so the searches simply continue. Both
interfaces are protocols: a merged policy, in-place weight reload or vLLM sleep mode plug in without touching the
searches; the LoRA-adapter publisher with stop/start works with today's servers.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ModelVersion:
    # A counter for analysis: the searches do not depend on it.
    version: int
    # LoRA adapters relative to the raw base model; the next phase continues from them.
    policy_adapter: str
    value_adapter: str
    published_at: str
    # Why the phase that produced it started ("initial" for version 0).
    trigger: str


@dataclass(frozen=True)
class LoopPaths:
    # $LEAN_SEARCH_RUNS, $LEAN_SEARCH_DATA and the loop's name.
    runs_root: Path
    data_root: Path
    name: str

    @property
    def directory(self) -> Path:
        return self.runs_root / self.name

    @property
    def data_directory(self) -> Path:
        return self.data_root / "expert_iteration" / self.name

    @property
    def config(self) -> Path:
        return self.directory / "loop.toml"

    @property
    def current(self) -> Path:
        return self.directory / "models" / "current.json"

    @property
    def versions(self) -> Path:
        return self.directory / "models" / "versions.jsonl"

    @property
    def shards(self) -> Path:
        return self.directory / "search" / "shards"

    @property
    def heartbeat(self) -> Path:
        return self.directory / "search" / "heartbeat.json"

    @property
    def curriculum(self) -> Path:
        return self.directory / "search" / "curriculum.json"

    @property
    def digests(self) -> Path:
        return self.directory / "training" / "digests"

    @property
    def buffers(self) -> Path:
        return self.directory / "training" / "buffers"

    @property
    def phase_state(self) -> Path:
        return self.directory / "training" / "state.json"

    @property
    def phases(self) -> Path:
        return self.directory / "training" / "phases.jsonl"

    @property
    def evaluations(self) -> Path:
        return self.directory / "evaluations.jsonl"

    @property
    def evaluation_lock(self) -> Path:
        """Present while an evaluation uses the servers; a phase waits for it before stopping them."""
        return self.directory / "evaluation.running"

    @property
    def summary(self) -> Path:
        return self.directory / "summary"

    def phase_data(self, phase: int) -> Path:
        return self.data_directory / f"phase_{phase:04d}"

    def phase_run_name(self, phase: int, stage: str) -> str:
        return f"{self.name}_phase_{phase:04d}_{stage}"


def write_json_atomically(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(to_json(record), encoding="utf-8")
    os.replace(temporary, path)


def read_current(paths: LoopPaths) -> ModelVersion:
    return from_json_object(ModelVersion, json.loads(paths.current.read_text(encoding="utf-8")))


def read_versions(paths: LoopPaths) -> list[ModelVersion]:
    if not paths.versions.exists():
        return []
    with paths.versions.open(encoding="utf-8") as lines:
        return [from_json_object(ModelVersion, json.loads(line)) for line in lines if line.strip()]


def record_published(paths: LoopPaths, version: ModelVersion) -> None:
    """The versions log first, then the pointer: a crash in between leaves the pointer one version behind."""
    paths.versions.parent.mkdir(parents=True, exist_ok=True)
    with paths.versions.open("a", encoding="utf-8") as handle:
        handle.write(to_json(version) + "\n")
    write_json_atomically(paths.current, version)


def server_port(server: ServerEndpoint) -> int:
    port = urlparse(server.url).port
    assert port is not None, server.url
    return port


class Publisher(Protocol):
    """Makes trained weights servable."""

    def prepare(self, version: ModelVersion) -> ModelVersion:
        """CPU work before serving (e.g. merging the policy); returns the version as it will be served."""
        ...

    def serve_command(self, version: ModelVersion, server: ServerEndpoint) -> str:
        """Starts a server that serves the version (after a phase or a reboot)."""
        ...


class GpuRelease(Protocol):
    """Frees a server's GPU for training and brings the server back with a version."""

    async def release(self, server: ServerEndpoint) -> None: ...

    async def restore(self, server: ServerEndpoint, version: ModelVersion) -> None: ...


class LoraAdapterPublisher:
    """Policy and value as LoRA adapters on the raw base model, under the same served names in every version."""

    def __init__(self, config: ServingConfig) -> None:
        self.config = config

    def prepare(self, version: ModelVersion) -> ModelVersion:
        return version

    def serve_command(self, version: ModelVersion, server: ServerEndpoint) -> str:
        return (
            f"deployment/serve_model.sh {server.name} {self.config.base_model} {server.gpu} {server_port(server)} "
            f"--served-model-name {self.config.served_model} --lora-modules "
            f"{self.config.policy_adapter_name}={version.policy_adapter} "
            f"{self.config.value_adapter_name}={version.value_adapter}"
        )


async def run_shell(command: str) -> None:
    process = await asyncio.create_subprocess_exec("bash", "-c", command, cwd=REPOSITORY_DIRECTORY)
    if await process.wait():
        raise RuntimeError(f"Command failed: {command}")


class StopStartRelease:
    """Stops the vLLM server for training and starts it again (1.5-2.5 minutes with warm caches)."""

    def __init__(self, publisher: Publisher) -> None:
        self.publisher = publisher

    async def release(self, server: ServerEndpoint) -> None:
        await run_shell(f"deployment/stop_model.sh {server.name}")

    async def restore(self, server: ServerEndpoint, version: ModelVersion) -> None:
        # Stopping first makes a repeated restore (after a crash) start the server once.
        await run_shell(f"deployment/stop_model.sh {server.name}")
        await run_shell(self.publisher.serve_command(version, server))
