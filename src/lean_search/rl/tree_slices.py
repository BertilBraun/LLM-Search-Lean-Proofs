"""The shared sampling run's trees cut into slices of equal generated tokens by finish order (DESIGN.md, "Follow-up
study: controlled arms", "Step 2"): each slice stands for one phase's budget B of a closed-loop arm.

The token count is what each tree's summary in the run's index records (`TreeSummary.generated_tokens`, the search's
own accounting); a cut falls at the tree boundary nearest to k / N of the total. A slice is a directory of links to
its tree files, as `grpo_phase.py --trees` and the expert-iteration builder read a phase's directory, with its own
index.jsonl (the entries, their files relative to the slice).
"""

import bisect
import dataclasses
import itertools
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.rl.tree_store import INDEX_FILE, TreeEntry
from lean_search.search.records import to_json

MANIFEST_FILE = "manifest.json"


def finish_order(entries: Sequence[TreeEntry]) -> list[TreeEntry]:
    return sorted(entries, key=lambda entry: (entry.finished_time, entry.sequence))


def slice_by_tokens(entries: Sequence[TreeEntry], count: int) -> tuple[tuple[TreeEntry, ...], ...]:
    """`count` consecutive runs of the trees in finish order, each holding as nearly 1 / count of the generated tokens
    as tree boundaries allow."""
    if count < 1:
        raise ValueError("At least one slice.")
    ordered = finish_order(entries)
    cumulative = list(itertools.accumulate((entry.summary.generated_tokens for entry in ordered), initial=0))
    total = cumulative[-1]
    if total == 0:
        raise ValueError("The trees record no generated tokens (TreeSummary.generated_tokens).")
    cuts = [0]
    for slice_number in range(1, count):
        target = slice_number * total / count
        position = bisect.bisect_left(cumulative, target)
        if target - cumulative[position - 1] <= cumulative[position] - target:
            position -= 1
        cuts.append(max(position, cuts[-1]))
    cuts.append(len(ordered))
    return tuple(tuple(ordered[start:end]) for start, end in itertools.pairwise(cuts))


@dataclass(frozen=True)
class SliceRecord:
    slice: int
    directory: str
    trees: int
    generated_tokens: int
    solved: int
    solved_share: float
    first_finished_time: float
    last_finished_time: float


@dataclass(frozen=True)
class SliceManifest:
    trees_directory: str
    trees: int
    generated_tokens: int
    slices: tuple[SliceRecord, ...]


def slice_directory_name(number: int) -> str:
    return f"slice_{number}"


def write_slices(trees_directory: Path, slices: Sequence[Sequence[TreeEntry]], output: Path) -> SliceManifest:
    """Slice k's links under output/slice_k/ (absolute, to the trees' files), its index and the manifest; refuses an
    existing output, so the slices stay as first cut."""
    if output.exists():
        raise ValueError(f"{output} exists: the slices are cut once.")
    records = []
    for number, members in enumerate(slices, start=1):
        directory = output / slice_directory_name(number)
        directory.mkdir(parents=True)
        lines = []
        for entry in members:
            link = directory / Path(entry.file).name
            os.symlink((trees_directory / entry.file).resolve(), link)
            lines.append(to_json(dataclasses.replace(entry, file=link.name)) + "\n")
        (directory / INDEX_FILE).write_text("".join(lines), encoding="utf-8")
        solved = sum(entry.proved for entry in members)
        records.append(
            SliceRecord(
                slice=number,
                directory=str(directory),
                trees=len(members),
                generated_tokens=sum(entry.summary.generated_tokens for entry in members),
                solved=solved,
                solved_share=solved / len(members) if members else 0.0,
                first_finished_time=members[0].finished_time if members else 0.0,
                last_finished_time=members[-1].finished_time if members else 0.0,
            )
        )
    manifest = SliceManifest(
        trees_directory=str(trees_directory),
        trees=sum(record.trees for record in records),
        generated_tokens=sum(record.generated_tokens for record in records),
        slices=tuple(records),
    )
    (output / MANIFEST_FILE).write_text(to_json(manifest) + "\n", encoding="utf-8")
    return manifest
