"""The loop's publisher: adapters merged into full weights on the CPU (imports torch, unlike serving.py)."""

from pathlib import Path

from lean_search.expert_iteration.loop_config import LoopConfig
from lean_search.expert_iteration.serving import MergedPublisher
from lean_search.policy.adapters import merge_adapter


def merge(base_model: str, adapter: str, output_directory: Path) -> None:
    merge_adapter(base_model, Path(adapter), output_directory)


def merged_publisher(config: LoopConfig, checkpoints: Path) -> MergedPublisher:
    """Merged weights of every version under $LEAN_SEARCH_CHECKPOINTS/<loop>/weights/v<version>/{policy,value}."""
    return MergedPublisher(config.serving, checkpoints / config.name / "weights", merge)
