"""The trees an expert-iteration round reads from a loop's run directory: a window of its phases (`phase_window`) or
explicit tree directories, each one slice, as `experiments/grpo_phase.py --trees` reads them."""

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import read_versions
from lean_search.rl.expert_iteration_data import ExpertIterationDataConfig, PhaseWindow, phase_window
from lean_search.rl.health_checks import RewardFix
from lean_search.rl.loop import GrpoLoopPaths, read_progress
from lean_search.rl.tree_store import TreeEntry
from lean_search.search.records import from_json_object


@dataclass(frozen=True)
class RoundTree:
    path: Path
    # Fed from below the curriculum's band (`TreeSummary.below_band`); unknown for tree directories, so False.
    below_band: bool


@dataclass(frozen=True)
class RoundTrees:
    # None for tree directories.
    window: PhaseWindow | None
    # Samples of earlier versions, and of unrecorded ones, are left out.
    minimum_version: int
    # The window's index entries, which `count` tabulates; none for tree directories.
    entries: tuple[TreeEntry, ...]
    # What `build` labels: the window's solved trees, or every tree of the directories.
    trees: tuple[RoundTree, ...]


def index_entries(paths: GrpoLoopPaths) -> list[TreeEntry]:
    """The tree index; a last line the running loop is still appending is left out."""
    lines = [line for line in (paths.trees / "index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = []
    for number, line in enumerate(lines, start=1):
        try:
            entries.append(from_json_object(TreeEntry, json.loads(line)))
        except ValueError:
            if number < len(lines):
                raise
    return entries


def directory_trees(directories: Collection[str], runs_directory: Path) -> tuple[RoundTree, ...]:
    """Every tree file of each directory (under `runs_directory` unless absolute), directory by directory."""
    trees = []
    for name in directories:
        directory = runs_directory / name
        found = sorted(directory.glob("*.json.gz"))
        if not found:
            raise ValueError(f"The tree directory {directory} holds no trees (*.json.gz).")
        trees += [RoundTree(path, below_band=False) for path in found]
    return tuple(trees)


def round_trees(config: ExpertIterationDataConfig, paths: GrpoLoopPaths) -> RoundTrees:
    """The run directory's side of `grpo_expert_iteration.loop_inputs`. Tree directories take every policy version
    from 0 (rejected ones aside); that they hold one version only is checked on the trees (`check_one_version`)."""
    if config.tree_directories:
        return RoundTrees(None, 0, (), directory_trees(config.tree_directories, paths.runs_root))
    reward_fix_phase = (
        from_json_object(RewardFix, json.loads(paths.reward_fix.read_text(encoding="utf-8"))).first_phase
        if paths.reward_fix.exists()
        else None
    )
    last_phase = config.last_phase or read_progress(paths.progress).phase - 1
    window = phase_window(config.window_phases, last_phase, read_versions(paths.models), reward_fix_phase)
    entries = tuple(entry for entry in index_entries(paths) if window.holds(entry.phase))
    trees = tuple(RoundTree(paths.trees / entry.file, entry.summary.below_band) for entry in entries if entry.proved)
    return RoundTrees(window, window.minimum_version, entries, trees)


def check_one_version(versions: Collection[int | None], allow_mixed_versions: bool) -> None:
    if len(versions) > 1 and not allow_mixed_versions:
        named = ", ".join("unrecorded" if version is None else str(version) for version in versions)
        raise ValueError(
            f"The tree directories mix policy versions ({named}); set [data] allow_mixed_versions to take them all."
        )
