"""Disk retention of the loop's phase checkpoints: adapters of old versions are deleted, those still used are kept."""

import shutil
from collections.abc import Collection, Iterable, Sequence
from pathlib import Path

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.policy.adapters import premerged_directory

ADAPTER_KINDS = ("policy", "value")


def kept_adapters(versions: Sequence[ModelVersion], adapter_versions: int, in_use: Collection[str]) -> set[Path]:
    recent = versions[-adapter_versions:]
    return {Path(adapter) for adapter in in_use} | {
        Path(adapter) for version in recent for adapter in (version.policy_adapter, version.value_adapter)
    }


def prune_phase_adapters(phase_directories: Iterable[Path], kept: Collection[Path]) -> list[Path]:
    """Deletes the phases' adapters that are not kept, with what the training job merged beside them."""
    removed = []
    for phase_directory in phase_directories:
        for kind in ADAPTER_KINDS:
            adapter = phase_directory / kind / "adapter"
            if adapter in kept:
                continue
            for directory in (adapter, premerged_directory(adapter)):
                if directory.exists():
                    shutil.rmtree(directory)
                    removed.append(directory)
    return removed
