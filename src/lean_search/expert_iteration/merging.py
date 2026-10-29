"""The loop's publisher: adapters merged into full weights (imports torch, unlike serving.py), on the CPU unless the
training job already merged them on its GPU."""

import functools
import shutil
from pathlib import Path

from lean_search.expert_iteration.loop_config import LoopConfig
from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.policy.adapters import (
    PremergedWeights,
    handed_off_weights,
    merge_adapter,
    premerged_directory,
    read_premerged,
)


def merge(base_model: str, adapter: str, output_directory: Path, handoff_root: Path | None = None) -> None:
    """Takes over the training job's merge of this adapter into this base if there is one: moved from beside the
    adapter (grpo_phase.py --merge-adapters), or copied from the persistent job's handoff in host memory (which stays
    until the version is recorded, so a crash during the copy finds it again); else merges on the CPU."""
    premerged = premerged_directory(Path(adapter))
    if read_premerged(premerged) == PremergedWeights(base_model, adapter):
        shutil.move(premerged, output_directory)
        return
    handed_off = None if handoff_root is None else handed_off_weights(handoff_root, base_model, adapter)
    if handed_off is not None:
        shutil.copytree(handed_off, output_directory)
        return
    merge_adapter(base_model, Path(adapter), output_directory)


def merged_publisher(config: LoopConfig, checkpoints: Path) -> MergedPublisher:
    """Merged weights of every version under $LEAN_SEARCH_CHECKPOINTS/<loop>/weights/v<version>/{policy,value}."""
    return MergedPublisher(config.serving, checkpoints / config.name / "weights", merge)


def handoff_merge(handoff_root: Path) -> functools.partial[None]:
    """`merge` that also takes over merges handed off in host memory under `handoff_root`."""
    return functools.partial(merge, handoff_root=handoff_root)
