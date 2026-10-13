"""Model versions, the "current" pointer, and the interfaces that publish weights and free the GPUs for training.

A training phase puts every server to sleep (GpuRelease.release: weights and KV cache freed in 0.4 s), trains,
publishes version k + 1 (Publisher.prepare merges the new adapters into full weights, ~17 s each on the CPU; then the
versions log and models/current.json) and wakes the servers with the new weights (GpuRelease.restore, ~2 s). The
served model names stay, so the searches simply continue. Restarting the servers (stop/start, 1-2.5 minutes) is the
fallback, e.g. after a reboot (deployment/README.md).
"""

import asyncio
import dataclasses
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.policy.server_control import release_gpu, restore_gpu
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
MERGED_MARKER = "merged_from.txt"


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
    # The adapters merged into full weights, as the servers load them; empty before Publisher.prepare.
    policy_weights: str = ""
    value_weights: str = ""


@dataclass(frozen=True)
class ServiceControl:
    """Written by phase6_loop.py hold / release; the service follows it within CONTROL_SECONDS."""

    hold: bool
    requested_at: str


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
    def control(self) -> Path:
        return self.directory / "search" / "control.json"

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


def merged_directory(weights_root: Path, version: int, kind: str) -> Path:
    return weights_root / f"v{version:04d}" / kind


class MergedPublisher:
    """Merges each version's policy and value adapters into full weights for the merged instances."""

    def __init__(self, config: ServingConfig, weights_root: Path, merge: Callable[[str, Path], None]) -> None:
        self.config = config
        self.weights_root = weights_root
        # Merges an adapter into the base model's weights at a directory (lean_search.policy.adapters.merge_adapter).
        self.merge = merge
        self.merged: dict[str, Path] = {}

    def prepare(self, version: ModelVersion) -> ModelVersion:
        policy = self.merged_weights(
            version.policy_adapter, merged_directory(self.weights_root, version.version, "policy")
        )
        value = self.merged_weights(
            version.value_adapter, merged_directory(self.weights_root, version.version, "value")
        )
        return dataclasses.replace(version, policy_weights=str(policy), value_weights=str(value))

    def merged_weights(self, adapter: str, directory: Path) -> Path:
        """An adapter merged once: an unchanged adapter (e.g. the value model when it did not train) reuses it."""
        if adapter in self.merged:
            return self.merged[adapter]
        if not (directory / MERGED_MARKER).exists():
            temporary = directory.with_name(directory.name + ".tmp")
            shutil.rmtree(temporary, ignore_errors=True)
            self.merge(adapter, temporary)
            (temporary / MERGED_MARKER).write_text(adapter, encoding="utf-8")
            shutil.rmtree(directory, ignore_errors=True)
            os.replace(temporary, directory)
        self.merged[adapter] = directory
        return directory

    def weights(self, version: ModelVersion, server: ServerEndpoint) -> str:
        return version.policy_weights if server in self.config.policy_servers else version.value_weights

    def serve_command(self, version: ModelVersion, server: ServerEndpoint) -> str:
        served = self.config.policy_model if server in self.config.policy_servers else self.config.value_model
        settings = (
            ("GPU_MEMORY_UTILIZATION", server.memory_share),
            ("MAX_NUM_SEQS", server.max_num_seqs),
            ("MAX_NUM_BATCHED_TOKENS", server.max_num_batched_tokens),
        )
        environment = "".join(f"{name}={value} " for name, value in settings if value)
        return (
            f"{environment}SLEEP_MODE=1 deployment/serve_model.sh {server.name} {self.weights(version, server)} "
            f"{server.gpu} {server_port(server)} --served-model-name {served} --no-enable-lora "
            f"--dtype {self.config.dtype}"
        )


async def run_shell(command: str) -> None:
    process = await asyncio.create_subprocess_exec("bash", "-c", command, cwd=REPOSITORY_DIRECTORY)
    if await process.wait():
        raise RuntimeError(f"Command failed: {command}")


class SleepRelease:
    """vLLM sleep mode: the server frees its GPU and later reloads the version's weights in place."""

    def __init__(self, publisher: MergedPublisher) -> None:
        self.publisher = publisher

    async def release(self, server: ServerEndpoint) -> None:
        await release_gpu(server.url)

    async def restore(self, server: ServerEndpoint, version: ModelVersion) -> None:
        await restore_gpu(server.url, Path(self.publisher.weights(version, server)))


class StopStartRelease:
    """Stops the vLLM server for training and starts it again (1-2.5 minutes with warm caches)."""

    def __init__(self, publisher: Publisher) -> None:
        self.publisher = publisher

    async def release(self, server: ServerEndpoint) -> None:
        await run_shell(f"deployment/stop_model.sh {server.name}")

    async def restore(self, server: ServerEndpoint, version: ModelVersion) -> None:
        # Stopping first makes a repeated restore (after a crash) start the server once.
        await run_shell(f"deployment/stop_model.sh {server.name}")
        await run_shell(self.publisher.serve_command(version, server))
