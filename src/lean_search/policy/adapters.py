import dataclasses
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
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
PREMERGED_DIRECTORY = "merged"
PREMERGED_MARKER = "premerged.json"


@dataclass(frozen=True)
class PremergedWeights:
    base_model: str
    adapter: str


@dataclass(frozen=True)
class MergeSeconds:
    # Loading the base and merging the adapter, then writing the merged weights.
    merge: float = 0.0
    write: float = 0.0


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
    """From a local model directory or the model's Hugging Face snapshot."""
    model_directory = Path(model) if Path(model).is_dir() else Path(snapshot_download(model))
    for source in model_directory.iterdir():
        is_weight_file = source.suffix == ".safetensors" or source.name.endswith(".safetensors.index.json")
        destination = output_directory / source.name
        if not is_weight_file and not destination.exists():
            shutil.copyfile(source, destination)


def premerged_directory(adapter_directory: Path) -> Path:
    """Where a training job leaves the adapter merged on its GPU, for the loop's publisher to take over."""
    return adapter_directory.parent / PREMERGED_DIRECTORY


def read_premerged(directory: Path) -> PremergedWeights | None:
    marker = directory / PREMERGED_MARKER
    if not marker.exists():
        return None
    return PremergedWeights(**json.loads(marker.read_text(encoding="utf-8")))


def premerge_adapter(model: str, adapter_directory: Path, device: torch.device) -> MergeSeconds:
    """`merge_adapter` on the device into `premerged_directory`; the marker, written last, names base and adapter."""
    started = time.perf_counter()
    merged = peft.PeftModel.from_pretrained(load_base_model(model, str(device)), adapter_directory).merge_and_unload()
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    merged_at = time.perf_counter()
    write_premerged(
        merged, None, PremergedWeights(model, str(adapter_directory)), premerged_directory(adapter_directory)
    )
    return MergeSeconds(merged_at - started, time.perf_counter() - merged_at)


def write_premerged(
    model: transformers.PreTrainedModel,
    state_dict: dict[str, torch.Tensor] | None,
    marker: PremergedWeights,
    directory: Path,
) -> None:
    """The merged weights (`state_dict`, else the model's own) as a servable checkpoint, written beside the directory
    and renamed into place with the marker inside, so a directory with a marker is always complete. Only on
    distributed rank 0, where transformers writes the weights."""
    temporary = directory.with_name(directory.name + ".tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    model.save_pretrained(temporary, state_dict=state_dict)
    assert any(temporary.glob("*.safetensors")), f"{temporary} holds no weights (written on a rank other than 0?)"
    copy_tokenizer_and_processor_files(marker.base_model, temporary)
    (temporary / PREMERGED_MARKER).write_text(json.dumps(dataclasses.asdict(marker)), encoding="utf-8")
    shutil.rmtree(directory, ignore_errors=True)
    temporary.rename(directory)


def load_adapter_weights(saved_module: peft.PeftModel, weights: dict[str, torch.Tensor]) -> None:
    """Adapter weights (as saved, or as `peft.get_peft_model_state_dict` gives them) into the trained adapter's
    existing parameters: the modules stay, so compiled layers keep their graphs."""
    with torch.no_grad():
        loaded = peft.set_peft_model_state_dict(saved_module, weights)
    assert not loaded.unexpected_keys, loaded.unexpected_keys


def saved_adapter_weights(adapter_directory: Path, device: torch.device) -> dict[str, torch.Tensor]:
    return safetensors.torch.load_file(adapter_directory / ADAPTER_WEIGHTS_FILE, device=str(device))


def handoff_directory(root: Path, adapter: str) -> Path:
    """Where the persistent training job leaves an adapter merged into its base in host memory, for the servers."""
    return root / hashlib.sha256(adapter.encode()).hexdigest()[:16]


def handed_off_weights(root: Path, base_model: str, adapter: str) -> Path | None:
    """The merged weights of this adapter on this base the training job left under `root`, if complete."""
    directory = handoff_directory(root, adapter)
    return directory if read_premerged(directory) == PremergedWeights(base_model, adapter) else None
