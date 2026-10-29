"""The loop's publisher: adapters merged into full weights (imports torch, unlike serving.py), on the CPU unless the
training job already merged them on its GPU."""

import shutil
from pathlib import Path

from lean_search.expert_iteration.loop_config import LoopConfig
from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.policy.adapters import PremergedWeights, merge_adapter, premerged_directory, read_premerged


def merge(base_model: str, adapter: str, output_directory: Path) -> None:
    """Takes over the training job's merge of this adapter into this base (grpo_phase.py --merge-adapters) if there
    is one, else merges on the CPU."""
    premerged = premerged_directory(Path(adapter))
    if read_premerged(premerged) == PremergedWeights(base_model, adapter):
        shutil.move(premerged, output_directory)
        return
    merge_adapter(base_model, Path(adapter), output_directory)


def merged_publisher(config: LoopConfig, checkpoints: Path) -> MergedPublisher:
    """Merged weights of every version under $LEAN_SEARCH_CHECKPOINTS/<loop>/weights/v<version>/{policy,value}."""
    return MergedPublisher(config.serving, checkpoints / config.name / "weights", merge)
