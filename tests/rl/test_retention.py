from pathlib import Path

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.policy.adapters import premerged_directory
from lean_search.rl.retention import kept_adapters, prune_phase_adapters


def version(number: int, value_adapter: str = "value-v0") -> ModelVersion:
    return ModelVersion(number, f"phase_{number}/policy/adapter", value_adapter, "now", f"phase {number}")


def test_the_adapters_of_the_last_versions_are_kept() -> None:
    versions = [version(number) for number in range(4)]
    assert kept_adapters(versions, 2, []) == {
        Path("phase_2/policy/adapter"),
        Path("phase_3/policy/adapter"),
        Path("value-v0"),
    }


def test_adapters_in_use_are_kept_beyond_the_last_versions() -> None:
    assert Path("phase_1/value/adapter") in kept_adapters([version(3)], 1, ["phase_1/value/adapter"])


def test_a_deleted_adapter_takes_its_gpu_merge_along(tmp_path: Path) -> None:
    adapter = tmp_path / "phase_1" / "policy" / "adapter"
    premerged_directory(adapter).mkdir(parents=True)
    adapter.mkdir(parents=True)
    prune_phase_adapters([tmp_path / "phase_1"], kept=set())
    assert list((tmp_path / "phase_1" / "policy").iterdir()) == []


def test_a_kept_adapter_stays(tmp_path: Path) -> None:
    adapter = tmp_path / "phase_1" / "value" / "adapter"
    adapter.mkdir(parents=True)
    prune_phase_adapters([tmp_path / "phase_1"], kept={adapter})
    assert adapter.exists()
