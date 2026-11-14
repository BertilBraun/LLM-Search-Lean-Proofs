from pathlib import Path

import pytest

from lean_search.expert_iteration.serving import ModelVersion
from lean_search.rl.expert_iteration_data import ExpertIterationDataConfig, PhaseWindow, parse_expert_iteration_config
from lean_search.rl.expert_iteration_trees import RoundTrees, check_one_version, round_trees
from lean_search.rl.loop import GrpoLoopPaths, LoopProgress
from lean_search.rl.tree_store import TreeEntry
from lean_search.search.records import to_json

CONFIG = Path(__file__).resolve().parents[2] / "experiments" / "configs" / "grpo" / "expert_iteration_1.toml"
# Published by phases 1 to 5; the loop collects phase 6.
VERSIONS = [
    ModelVersion(number, "policy", "value", "2026-11-14", "initial" if number == 0 else f"phase {number}")
    for number in range(6)
]
# Per phase 3 to 5 a solved and an unsolved tree.
ENTRIES = [
    TreeEntry(
        index,
        f"p{index}",
        phase,
        f"phase_{phase:04d}/{index}.json.gz",
        proved,
        int(proved),
        1,
        phase - 1,
        None,
        1.0,
        0.0,
    )
    for index, (phase, proved) in enumerate((phase, proved) for phase in (3, 4, 5) for proved in (True, False))
]


def window_run(root: Path) -> GrpoLoopPaths:
    """A loop's run directory with a tree index, versions and progress, and no reward_fix.json."""
    paths = GrpoLoopPaths(root, root, root, "run")
    paths.trees.mkdir(parents=True)
    (paths.trees / "index.jsonl").write_text("".join(f"{to_json(entry)}\n" for entry in ENTRIES), encoding="utf-8")
    paths.models.versions.parent.mkdir(parents=True)
    paths.models.versions.write_text("".join(f"{to_json(version)}\n" for version in VERSIONS), encoding="utf-8")
    paths.progress.write_text(to_json(LoopProgress(phase=6)), encoding="utf-8")
    return paths


def slices_run(root: Path) -> GrpoLoopPaths:
    """Two slice directories of tree files beside a loop's run directory."""
    for name in ("slice_1", "slice_2"):
        (root / "slices" / name).mkdir(parents=True)
        for index in range(2):
            (root / "slices" / name / f"{index}.json.gz").write_bytes(b"")
    return GrpoLoopPaths(root, root, root, "shared")


def selected(trees: RoundTrees, root: Path) -> list[str]:
    return [tree.path.relative_to(root).as_posix() for tree in trees.trees]


def test_a_window_on_a_run_without_a_reward_fix_takes_the_solved_trees_of_its_phases(tmp_path: Path) -> None:
    trees = round_trees(ExpertIterationDataConfig(window_phases=2), window_run(tmp_path))
    found = (trees.window, trees.minimum_version, selected(trees, tmp_path))
    assert found == (PhaseWindow(4, 5, 3), 3, ["run/trees/phase_0004/2.json.gz", "run/trees/phase_0005/4.json.gz"])


def test_a_window_keeps_every_index_entry_of_its_phases_for_count(tmp_path: Path) -> None:
    trees = round_trees(ExpertIterationDataConfig(window_phases=2), window_run(tmp_path))
    assert [entry.sequence for entry in trees.entries] == [2, 3, 4, 5]


def test_tree_directories_take_every_tree_of_each_slice_from_version_zero(tmp_path: Path) -> None:
    config = ExpertIterationDataConfig(tree_directories=("slices/slice_1", "slices/slice_2"))
    trees = round_trees(config, slices_run(tmp_path))
    expected = (None, 0, [f"slices/slice_{part}/{index}.json.gz" for part in (1, 2) for index in range(2)])
    assert (trees.window, trees.minimum_version, selected(trees, tmp_path)) == expected


def test_an_empty_tree_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "slices" / "empty").mkdir(parents=True)
    with pytest.raises(ValueError, match="holds no trees"):
        round_trees(ExpertIterationDataConfig(tree_directories=("slices/empty",)), slices_run(tmp_path))


@pytest.mark.parametrize("versions", [{0, 1}, {0, None}], ids=["two versions", "an unrecorded version"])
def test_tree_directories_mixing_policy_versions_are_refused(versions: set[int | None]) -> None:
    with pytest.raises(ValueError, match="allow_mixed_versions"):
        check_one_version(versions, allow_mixed_versions=False)


@pytest.mark.parametrize(
    ("versions", "allowed"), [({0}, False), ({0, 1}, True)], ids=["one version", "mixed versions allowed"]
)
def test_tree_directories_of_one_version_or_allowed_mixes_pass(versions: set[int | None], allowed: bool) -> None:
    assert check_one_version(versions, allowed) is None


def test_tree_directories_and_a_phase_window_are_exclusive() -> None:
    text = CONFIG.read_text(encoding="utf-8").replace(
        "last_phase = 25\n", 'last_phase = 25\ntree_directories = ["slices/slice_4"]\n'
    )
    with pytest.raises(ValueError, match="not both"):
        parse_expert_iteration_config(text)
