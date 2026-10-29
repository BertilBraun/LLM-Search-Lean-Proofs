"""Models that stay in a training process between phases, parked in host memory while the GPUs serve.

The frozen tensors (the base weights and buffers) live once on the node: in one file under a host directory (a tmpfs),
written by the main rank and mapped shared by every rank, so four ranks hold one copy. Parking points a rank's frozen
tensors at that mapping and moves its LoRA weights to the CPU, which frees its GPU but for the CUDA context; unparking
copies them back. The module objects stay, so their compiled layers keep their graphs. The base never changes: an
in-place merge on the GPU only touches the unparked copy.
"""

import json
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import peft
import torch
import transformers

from lean_search.policy.adapters import (
    PremergedWeights,
    load_adapter_weights,
    saved_adapter_weights,
    write_premerged,
)
from lean_search.search.records import from_json_object, to_json
from lean_search.training.data_parallel import Ranks, barrier
from lean_search.training.sft import FineTuningMethod, LoraSettings, OptimizationConfig, load_trainable_model

CPU = torch.device("cpu")
# Byte offset alignment of the tensors in the file, so every slice can be viewed with its own dtype.
ALIGNMENT = 64
LAYOUT_SUFFIX = ".layout.json"
TRAINED_ADAPTER_NAME = "default"


@dataclass(frozen=True)
class HostDirectories:
    """The persistent trainer's host memory (`[training] host_directory` / loop name)."""

    root: Path

    @property
    def parked(self) -> Path:
        return self.root / "parked"

    @property
    def handoff(self) -> Path:
        """Merged weights handed to the servers (`adapters.handoff_directory`), until the loop wrote them to disk."""
        return self.root / "handoff"


@dataclass(frozen=True)
class TensorSlot:
    name: str
    offset: int
    dtype: str
    shape: tuple[int, ...]


@dataclass(frozen=True)
class HostLayout:
    size: int
    slots: tuple[TensorSlot, ...]


def frozen_tensors(module: torch.nn.Module) -> Iterator[tuple[str, torch.Tensor]]:
    """The parameters that do not train, then the buffers; tied parameters once."""
    for name, parameter in module.named_parameters():
        if not parameter.requires_grad:
            yield name, parameter
    yield from module.named_buffers()


def layout_path(path: Path) -> Path:
    return path.with_name(path.name + LAYOUT_SUFFIX)


def write_host_weights(module: torch.nn.Module, path: Path) -> None:
    """The module's frozen tensors into one file at aligned offsets, and their layout beside it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # An earlier job's copy: its processes are gone before a job starts (loop_services.run_logged).
    path.unlink(missing_ok=True)
    needed = sum(tensor.nbytes + ALIGNMENT for _, tensor in frozen_tensors(module))
    free = shutil.disk_usage(path.parent).free
    if free < needed:
        raise RuntimeError(
            f"{path.parent} has {free / 2**30:.1f} GiB free, the parked weights need {needed / 2**30:.1f} GiB: rent "
            "with a larger --shm-size (deployment/README.md, GRPO loop) or set [training] host_directory elsewhere"
        )
    temporary = path.with_name(path.name + ".tmp")
    slots = []
    offset = 0
    with temporary.open("wb") as file:
        for name, tensor in frozen_tensors(module):
            padding = -offset % ALIGNMENT
            file.write(bytes(padding))
            offset += padding
            data = tensor.detach().cpu().contiguous().reshape(-1).view(torch.uint8)
            file.write(data.numpy().data)
            slots.append(TensorSlot(name, offset, str(tensor.dtype).removeprefix("torch."), tuple(tensor.shape)))
            offset += data.numel()
    os.replace(temporary, path)
    layout_path(path).write_text(to_json(HostLayout(offset, tuple(slots))), encoding="utf-8")


class HostWeights:
    """The file mapped shared: every process mapping it reads the same pages."""

    def __init__(self, path: Path) -> None:
        layout = from_json_object(HostLayout, json.loads(layout_path(path).read_text(encoding="utf-8")))
        self.path = path
        self.storage = torch.from_file(str(path), shared=True, size=layout.size, dtype=torch.uint8)
        self.tensors: dict[str, torch.Tensor] = {}
        for slot in layout.slots:
            dtype = getattr(torch, slot.dtype)
            size = dtype.itemsize * torch.Size(slot.shape).numel()
            view = self.storage[slot.offset : slot.offset + size].view(dtype)
            self.tensors[slot.name] = view.view(slot.shape)

    @property
    def size(self) -> int:
        return self.storage.numel()


def named_tensors(module: torch.nn.Module) -> Iterator[tuple[str, torch.Tensor]]:
    yield from module.named_parameters()
    yield from module.named_buffers()


def park(module: torch.nn.Module, host: HostWeights) -> None:
    """Frozen tensors onto the shared mapping, the rest (the LoRA weights) to the CPU: nothing left on the GPU."""
    for name, tensor in named_tensors(module):
        tensor.grad = None
        tensor.data = host.tensors[name] if name in host.tensors else tensor.data.to(CPU)


def unpark(module: torch.nn.Module, host: HostWeights, device: torch.device) -> None:
    """Every tensor onto the device; frozen ones as copies, so that the mapping never changes."""
    for name, tensor in named_tensors(module):
        tensor.data = tensor.data.to(device, copy=name in host.tensors, non_blocking=True)
    if device.type == "cuda":
        torch.cuda.synchronize(device)


@dataclass(frozen=True)
class ResidentStructure:
    """What a resident model was built with; a trainer asking for another model or structure is a bug."""

    model: str
    method: FineTuningMethod
    packing: bool
    gradient_checkpointing: bool
    compile_layers: bool


def resident_structure(model: str, optimization: OptimizationConfig) -> ResidentStructure:
    return ResidentStructure(
        model,
        optimization.method,
        optimization.packing,
        optimization.gradient_checkpointing,
        optimization.compile_layers,
    )


def merged_state_dict(causal_model: transformers.PreTrainedModel) -> dict[str, torch.Tensor]:
    """The state dict of the merged model as merge_and_unload would leave it: base layers under their own names."""
    return {
        name.replace(".base_layer", ""): tensor
        for name, tensor in causal_model.state_dict().items()
        if ".lora_" not in name
    }


class ResidentModel:
    """A LoRA model built once (on the CPU, its base on the shared mapping) and lent to the trainers each phase."""

    def __init__(
        self,
        saved_module: peft.PeftModel,
        causal_model: transformers.PreTrainedModel,
        host: HostWeights,
        structure: ResidentStructure,
        device: torch.device,
    ) -> None:
        self.saved_module = saved_module
        self.causal_model = causal_model
        self.host = host
        self.structure = structure
        self.device = device
        self.parked = True
        # Seconds since the last `reset_seconds`, for the phase's timings.
        self.unpark_seconds = 0.0
        self.park_seconds = 0.0

    def reset_seconds(self) -> None:
        self.unpark_seconds = self.park_seconds = 0.0

    def unpark(self) -> None:
        if not self.parked:
            return
        started = time.perf_counter()
        unpark(self.saved_module, self.host, self.device)
        self.parked = False
        self.unpark_seconds += time.perf_counter() - started

    def park(self) -> None:
        if self.parked:
            return
        started = time.perf_counter()
        park(self.saved_module, self.host)
        self.parked = True
        self.park_seconds += time.perf_counter() - started

    def trainable(
        self,
        model_name: str,
        optimization: OptimizationConfig,
        lora: LoraSettings,
        device: torch.device,
        initial_adapter: str = "",
    ) -> tuple[torch.nn.Module, transformers.PreTrainedModel]:
        """A `TrainableLoader`: the model unparked with the adapter to continue loaded (fresh LoRA weights without)."""
        assert resident_structure(model_name, optimization) == self.structure, (model_name, optimization)
        assert device == self.device
        self.unpark()
        torch.manual_seed(optimization.seed)
        if initial_adapter:
            load_adapter_weights(self.saved_module, saved_adapter_weights(Path(initial_adapter), device))
        else:
            for module in self.saved_module.modules():
                if isinstance(module, peft.tuners.lora.LoraLayer):
                    module.reset_lora_parameters(TRAINED_ADAPTER_NAME, True)
        self.saved_module.train()
        return self.saved_module, self.causal_model

    def write_merged(self, marker: PremergedWeights, directory: Path) -> tuple[float, float]:
        """The trained adapter merged into the base on the device and written to `directory` (`write_premerged`);
        the merging and the writing seconds. The merge stays in the unparked copy, which parking drops."""
        started = time.perf_counter()
        self.unpark()
        self.saved_module.base_model.merge_adapter()
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        merged = time.perf_counter()
        write_premerged(self.causal_model, merged_state_dict(self.causal_model), marker, directory)
        written = time.perf_counter()
        self.saved_module.base_model.unmerge_adapter()
        self.park()
        return merged - started, written - merged


def build_resident_model(
    model_name: str,
    optimization: OptimizationConfig,
    lora: LoraSettings,
    initial_adapter: str,
    path: Path,
    device: torch.device,
    ranks: Ranks,
) -> ResidentModel:
    """The ranks in turn load the model on the CPU and park it, so that one transient copy exists at a time; the main
    rank first writes the shared file of its frozen tensors."""
    assert optimization.method == FineTuningMethod.LORA, optimization.method
    resident = None
    for turn in range(ranks.world_size):
        if turn == ranks.rank:
            saved_module, causal_model = load_trainable_model(model_name, optimization, lora, CPU, initial_adapter)
            assert isinstance(saved_module, peft.PeftModel)
            if ranks.is_main:
                write_host_weights(saved_module, path)
            host = HostWeights(path)
            assert set(host.tensors) == {name for name, _ in frozen_tensors(saved_module)}
            park(saved_module, host)
            structure = resident_structure(model_name, optimization)
            resident = ResidentModel(saved_module, causal_model, host, structure, device)
        barrier(ranks)
    assert resident is not None
    return resident
