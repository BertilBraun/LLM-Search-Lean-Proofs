from pathlib import Path

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.expert_iteration.serving import (
    LoopPaths,
    LoraAdapterPublisher,
    ModelVersion,
    read_current,
    read_versions,
    record_published,
)

SERVER = ServerEndpoint("search-gpu1", 1, "http://127.0.0.1:8101/v1")
CONFIG = ServingConfig("Qwen/Qwen3.5-2B", "search-qwen3.5-2b", "Qwen/Qwen3.5-2B", (SERVER,))


def version(number: int) -> ModelVersion:
    return LoraAdapterPublisher(CONFIG).prepare(
        ModelVersion(number, f"/policy{number}", f"/value{number}", "now", "proofs")
    )


def test_every_version_is_served_under_the_same_adapter_names() -> None:
    command = LoraAdapterPublisher(CONFIG).serve_command(version(3), SERVER)
    assert command == (
        "deployment/serve_model.sh search-gpu1 Qwen/Qwen3.5-2B 1 8101 --served-model-name search-qwen3.5-2b "
        "--lora-modules policy=/policy3 value=/value3"
    )


def test_the_current_pointer_follows_the_last_publish(tmp_path: Path) -> None:
    paths = LoopPaths(tmp_path, tmp_path, "loop")
    for number in range(3):
        record_published(paths, version(number))
    assert (read_current(paths).version, [entry.version for entry in read_versions(paths)]) == (2, [0, 1, 2])
