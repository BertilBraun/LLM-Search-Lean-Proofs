import json
import shutil
from pathlib import Path

import peft
import safetensors.torch
import torch
import transformers
from huggingface_hub import snapshot_download

LANGUAGE_MODEL_LINEAR_LAYERS = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "in_proj_qkv",
    "in_proj_z",
    "in_proj_a",
    "in_proj_b",
    "out_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)
# Qwen3.5 checkpoints contain a vision tower whose linear layers vLLM does not adapt by default.
LORA_TARGET_PATTERN = rf"(?!.*\bvisual\b).*\.({'|'.join(LANGUAGE_MODEL_LINEAR_LAYERS)})"
ADAPTER_CONFIG_FILE = "adapter_config.json"
ADAPTER_WEIGHTS_FILE = "adapter_model.safetensors"
LORA_A_SUFFIX = ".lora_A.weight"
LORA_B_SUFFIX = ".lora_B.weight"


def load_base_model(model: str, device: str = "cpu") -> transformers.PreTrainedModel:
    config = transformers.AutoConfig.from_pretrained(model)
    model_class = (
        transformers.AutoModelForImageTextToText
        if hasattr(config, "vision_config")
        else transformers.AutoModelForCausalLM
    )
    return model_class.from_pretrained(model, dtype=torch.bfloat16, device_map=device)


def create_zero_adapter(model: str, output_directory: Path, rank: int) -> None:
    lora_config = peft.LoraConfig(r=rank, lora_alpha=rank, target_modules=LORA_TARGET_PATTERN, lora_dropout=0.0)
    peft.get_peft_model(load_base_model(model), lora_config).save_pretrained(output_directory)


def merge_adapter(model: str, adapter_directory: Path, output_directory: Path, device: str = "cpu") -> None:
    merged = peft.PeftModel.from_pretrained(load_base_model(model, device), adapter_directory).merge_and_unload()
    merged.save_pretrained(output_directory)
    copy_tokenizer_and_processor_files(model, output_directory)


def difference_adapter(target_directory: Path, merged_directory: Path, output_directory: Path) -> None:
    """Writes the adapter that turns base weights with `merged_directory`'s adapter merged in into base + target."""
    target_weights = safetensors.torch.load_file(target_directory / ADAPTER_WEIGHTS_FILE)
    merged_weights = safetensors.torch.load_file(merged_directory / ADAPTER_WEIGHTS_FILE)
    assert target_weights.keys() == merged_weights.keys()
    target_scale, merged_scale = lora_scale(target_directory), lora_scale(merged_directory)
    # B_t A_t - B_m A_m = [B_t, -B_m] [A_t; A_m]: the ranks concatenate, each adapter's scale folded into its B.
    weights = {
        key: torch.cat([target_weights[key], merged_weights[key]])
        if key.endswith(LORA_A_SUFFIX)
        else torch.cat([target_scale * target_weights[key], -merged_scale * merged_weights[key]], dim=1)
        for key in target_weights
    }
    rank = lora_rank(target_directory) + lora_rank(merged_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    safetensors.torch.save_file(weights, output_directory / ADAPTER_WEIGHTS_FILE)
    config = json.loads((target_directory / ADAPTER_CONFIG_FILE).read_text(encoding="utf-8"))
    config |= {"r": rank, "lora_alpha": rank}
    (output_directory / ADAPTER_CONFIG_FILE).write_text(json.dumps(config, indent=2), encoding="utf-8")


def lora_rank(adapter_directory: Path) -> int:
    return json.loads((adapter_directory / ADAPTER_CONFIG_FILE).read_text(encoding="utf-8"))["r"]


def lora_scale(adapter_directory: Path) -> float:
    config = json.loads((adapter_directory / ADAPTER_CONFIG_FILE).read_text(encoding="utf-8"))
    assert not config["use_rslora"] and not config["rank_pattern"] and not config["alpha_pattern"]
    return config["lora_alpha"] / config["r"]


def lora_delta(adapter_directory: Path, module_key: str) -> torch.Tensor:
    """The update the adapter adds to one module's weight; keys as in the file, e.g. `base_model.model.<module>`."""
    weights = safetensors.torch.load_file(adapter_directory / ADAPTER_WEIGHTS_FILE)
    return lora_scale(adapter_directory) * weights[module_key + LORA_B_SUFFIX] @ weights[module_key + LORA_A_SUFFIX]


def copy_tokenizer_and_processor_files(model: str, output_directory: Path) -> None:
    for source in Path(snapshot_download(model)).iterdir():
        is_weight_file = source.suffix == ".safetensors" or source.name.endswith(".safetensors.index.json")
        destination = output_directory / source.name
        if not is_weight_file and not destination.exists():
            shutil.copyfile(source, destination)
