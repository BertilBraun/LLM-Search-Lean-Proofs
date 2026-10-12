import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
adapters = pytest.importorskip("lean_search.policy.adapters")
safetensors_torch = pytest.importorskip("safetensors.torch")

MODULE = "base_model.model.model.language_model.layers.0.mlp.down_proj"


def write_adapter(directory: Path, rank: int, alpha: int, seed: int) -> Path:
    generator = torch.Generator().manual_seed(seed)
    directory.mkdir()
    weights = {
        MODULE + adapters.LORA_A_SUFFIX: torch.randn(rank, 6, generator=generator),
        MODULE + adapters.LORA_B_SUFFIX: torch.randn(5, rank, generator=generator),
    }
    safetensors_torch.save_file(weights, directory / adapters.ADAPTER_WEIGHTS_FILE)
    config = {"r": rank, "lora_alpha": alpha, "use_rslora": False, "rank_pattern": {}, "alpha_pattern": {}}
    (directory / adapters.ADAPTER_CONFIG_FILE).write_text(json.dumps(config), encoding="utf-8")
    return directory


def test_difference_adapter_on_merged_weights_gives_the_target_update(tmp_path: Path) -> None:
    target = write_adapter(tmp_path / "value", rank=4, alpha=8, seed=0)
    merged = write_adapter(tmp_path / "policy", rank=2, alpha=2, seed=1)
    adapters.difference_adapter(target, merged, tmp_path / "difference")
    difference = adapters.lora_delta(tmp_path / "difference", MODULE)
    expected = adapters.lora_delta(target, MODULE) - adapters.lora_delta(merged, MODULE)
    torch.testing.assert_close(difference, expected)
