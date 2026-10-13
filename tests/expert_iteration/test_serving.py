from pathlib import Path

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.expert_iteration.serving import (
    LoopPaths,
    MergedPublisher,
    ModelVersion,
    read_current,
    read_versions,
    record_published,
)

POLICY_SERVER = ServerEndpoint("policy-gpu1", 1, "http://127.0.0.1:8101/v1", 0.58)
VALUE_SERVER = ServerEndpoint("value-gpu1", 1, "http://127.0.0.1:8201/v1", 0.25, max_num_seqs=96)
CONFIG = ServingConfig("Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-2B", (POLICY_SERVER,), (VALUE_SERVER,))


class RecordingMerge:
    def __init__(self) -> None:
        self.merged: list[str] = []

    def __call__(self, base_model: str, adapter: str, output_directory: Path) -> None:
        self.merged.append(adapter)
        output_directory.mkdir(parents=True)


def published(tmp_path: Path, merge: RecordingMerge, number: int, value_adapter: str) -> ModelVersion:
    version = ModelVersion(number, f"/policy{number}", value_adapter, "now", "proofs")
    return MergedPublisher(CONFIG, tmp_path, merge).prepare(version)


def test_a_version_serves_its_merged_weights(tmp_path: Path) -> None:
    version = published(tmp_path, RecordingMerge(), 3, "/value3")
    assert (version.policy_weights, version.value_weights) == (
        str(tmp_path / "v0003" / "policy"),
        str(tmp_path / "v0003" / "value"),
    )


def test_merged_weights_are_not_merged_again(tmp_path: Path) -> None:
    merge = RecordingMerge()
    published(tmp_path, merge, 1, "/value1")
    published(tmp_path, merge, 1, "/value1")
    assert merge.merged == ["/policy1", "/value1"]


def test_each_instance_serves_its_kind_of_weights(tmp_path: Path) -> None:
    publisher = MergedPublisher(CONFIG, tmp_path, RecordingMerge())
    version = publisher.prepare(ModelVersion(2, "/policy2", "/value2", "now", "proofs"))
    assert publisher.serve_command(version, VALUE_SERVER) == (
        "GPU_MEMORY_UTILIZATION=0.25 MAX_NUM_SEQS=96 SLEEP_MODE=1 deployment/serve_model.sh value-gpu1 "
        f"{tmp_path / 'v0002' / 'value'} 1 8201 --served-model-name value-merged --no-enable-lora --dtype bfloat16"
    )


def test_the_current_pointer_follows_the_last_publish(tmp_path: Path) -> None:
    paths = LoopPaths(tmp_path, tmp_path, "loop")
    for number in range(3):
        record_published(paths, ModelVersion(number, "/p", "/v", "now", "proofs"))
    assert (read_current(paths).version, [entry.version for entry in read_versions(paths)]) == (2, [0, 1, 2])
