import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")
safetensors_torch = pytest.importorskip("safetensors.torch")

from lean_search.policy.adapters import (  # noqa: E402
    LORA_A_SUFFIX,
    LORA_B_SUFFIX,
    LORA_TARGET_PATTERN,
    load_base_model,
    merge_adapter,
    merge_adapter_fp16,
)

PUBLISH_SCRIPT = Path(__file__).resolve().parents[2] / "experiments" / "publish_weights.py"
MODULE = "model.language_model.layers.0.mlp.up_proj"
VOCABULARY_SIZE = 512


def tiny_qwen3_5_config() -> transformers.PretrainedConfig:
    """Qwen3.5's layout (vision tower, Gated DeltaNet and attention layers, tied embeddings) at a tiny size."""
    return transformers.Qwen3_5Config(
        text_config={
            "vocab_size": VOCABULARY_SIZE,
            "hidden_size": 64,
            "intermediate_size": 128,
            "num_hidden_layers": 4,
            "layer_types": ["linear_attention"] * 3 + ["full_attention"],
            "num_attention_heads": 2,
            "num_key_value_heads": 1,
            "head_dim": 32,
            "linear_num_key_heads": 2,
            "linear_num_value_heads": 2,
            "linear_key_head_dim": 16,
            "linear_value_head_dim": 16,
            "tie_word_embeddings": True,
        },
        vision_config={"depth": 1, "hidden_size": 32, "intermediate_size": 64, "num_heads": 1, "out_hidden_size": 64},
        tie_word_embeddings=True,
    )


@pytest.fixture(scope="module")
def tiny_base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("tiny_qwen3_5") / "base"
    torch.manual_seed(0)
    transformers.AutoModelForImageTextToText.from_config(tiny_qwen3_5_config()).to(torch.bfloat16).save_pretrained(
        directory
    )
    return directory


@pytest.fixture(scope="module")
def tiny_adapter(tiny_base: Path) -> Path:
    directory = tiny_base.parent / "adapter"
    lora_config = peft.LoraConfig(r=4, lora_alpha=8, target_modules=LORA_TARGET_PATTERN, lora_dropout=0.0)
    model = peft.get_peft_model(load_base_model(str(tiny_base)), lora_config)
    generator = torch.Generator().manual_seed(1)
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            if "lora_" in name:
                parameter.copy_(torch.randn(parameter.shape, generator=generator) * 0.05)
    model.save_pretrained(directory)
    return directory


def merged_weight(directory: Path) -> torch.Tensor:
    return safetensors_torch.load_file(directory / "model.safetensors")[MODULE + ".weight"]


def adapter_update(adapter: Path) -> torch.Tensor:
    weights = safetensors_torch.load_file(adapter / "adapter_model.safetensors")
    key = f"base_model.model.{MODULE}"
    # lora_alpha / r = 8 / 4.
    return 2.0 * weights[key + LORA_B_SUFFIX].float() @ weights[key + LORA_A_SUFFIX].float()


def base_weight(base: Path) -> torch.Tensor:
    return merged_weight(base).float()


def test_bf16_merge_adds_the_adapter_update(tiny_base: Path, tiny_adapter: Path, tmp_path: Path) -> None:
    merge_adapter(str(tiny_base), tiny_adapter, tmp_path / "merged")
    expected = (base_weight(tiny_base) + adapter_update(tiny_adapter)).to(torch.bfloat16)
    torch.testing.assert_close(merged_weight(tmp_path / "merged"), expected, atol=0, rtol=2**-7)


def test_fp16_merge_is_the_fp32_merge_rounded_once(tiny_base: Path, tiny_adapter: Path, tmp_path: Path) -> None:
    merge_adapter_fp16(str(tiny_base), tiny_adapter, tmp_path / "merged")
    expected = (base_weight(tiny_base) + adapter_update(tiny_adapter)).to(torch.float16)
    torch.testing.assert_close(merged_weight(tmp_path / "merged"), expected, atol=0, rtol=0)


@pytest.mark.parametrize("dtype", ["bfloat16", "float16"])
def test_merged_checkpoint_loads_with_the_output_layer_tied(
    tiny_base: Path, tiny_adapter: Path, tmp_path: Path, dtype: str
) -> None:
    output = tmp_path / "merged"
    command = [sys.executable, str(PUBLISH_SCRIPT), "merge", "--base-model", str(tiny_base)]
    subprocess.run([*command, "--adapter", str(tiny_adapter), "--output", str(output), "--dtype", dtype], check=True)
    merged = load_base_model(str(output))
    assert merged.lm_head.weight.data_ptr() == merged.get_input_embeddings().weight.data_ptr()


def test_concurrent_merges_in_their_own_processes_all_succeed(
    tiny_base: Path, tiny_adapter: Path, tmp_path: Path
) -> None:
    def merge(index: int) -> int:
        command = [sys.executable, str(PUBLISH_SCRIPT), "merge", "--base-model", str(tiny_base)]
        output = ["--adapter", str(tiny_adapter), "--output", str(tmp_path / f"merged_{index}")]
        dtype = ["--dtype", "float16" if index % 2 else "bfloat16"]
        return subprocess.run([*command, *output, *dtype], check=False).returncode

    with ThreadPoolExecutor(3) as pool:
        assert list(pool.map(merge, range(3))) == [0, 0, 0]
