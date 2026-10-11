import shutil
from pathlib import Path

import peft
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


def merge_adapter(model: str, adapter_directory: Path, output_directory: Path) -> None:
    merged = peft.PeftModel.from_pretrained(load_base_model(model), adapter_directory).merge_and_unload()
    merged.save_pretrained(output_directory)
    copy_tokenizer_and_processor_files(model, output_directory)


def copy_tokenizer_and_processor_files(model: str, output_directory: Path) -> None:
    for source in Path(snapshot_download(model)).iterdir():
        is_weight_file = source.suffix == ".safetensors" or source.name.endswith(".safetensors.index.json")
        destination = output_directory / source.name
        if not is_weight_file and not destination.exists():
            shutil.copyfile(source, destination)
