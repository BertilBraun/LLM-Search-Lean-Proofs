"""The shared sampling run's trees cut into slices of equal generated tokens by finish order (DESIGN.md, "Follow-up
study: controlled arms", "Step 2"): each slice stands for one phase's budget B of a closed-loop arm.

The token count is what each tree's summary in the run's index records (`TreeSummary.generated_tokens`, the search's
own accounting); a cut falls at the tree boundary nearest to k / N of the total. A slice is a directory of links to
its tree files, as `grpo_phase.py --trees` and the expert-iteration builder read a phase's directory, with its own
index.jsonl (the entries, their files relative to the slice).

With the policy fixed, slices differ in what was searched: the curriculum's band rises across them, and the stop drops
the slow searches still in flight from the last. Each slice's record therefore says what it holds (difficulty range,
statements per character band, solved and below-band shares, statements already searched in an earlier slice), so a
one-slice against four-slice comparison can be described for what it is.
"""

import bisect
import dataclasses
import itertools
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.rl.fixed_sets import character_strata, character_stratum
from lean_search.rl.tree_store import INDEX_FILE, TreeEntry
from lean_search.search.records import to_json

MANIFEST_FILE = "manifest.json"
# Probe v2's bands of proof characters; the follow-up curriculum's difficulty is characters / 100.
CHARACTER_EDGES = (500, 1000, 1500, 2000, 3000, 4500)
CHARACTERS_PER_DIFFICULTY = 100


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
class BandCount:
    # Proof characters (difficulty x 100), probe v2's bands; "unknown" without a recorded difficulty.
    band: str
    trees: int
    solved: int


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
    # The curriculum difficulty range searched; None without recorded difficulties.
    difficulty_low: float | None
    difficulty_high: float | None
    by_character_band: tuple[BandCount, ...]
    below_band_share: float
    statements: int
    # Statements also searched in an earlier slice.
    statements_seen_before: int
    trainable_groups: int
    mean_expansions: float


@dataclass(frozen=True)
class SliceManifest:
    trees_directory: str
    # The index as read: its lines (one per tree), checked unchanged while the slices were cut.
    index_lines: int
    trees: int
    generated_tokens: int
    slices: tuple[SliceRecord, ...]


def slice_directory_name(number: int) -> str:
    return f"slice_{number}"


def character_band(entry: TreeEntry) -> str:
    if entry.difficulty is None:
        return "unknown"
    return character_stratum(round(entry.difficulty * CHARACTERS_PER_DIFFICULTY), CHARACTER_EDGES)


def slice_record(number: int, directory: Path, members: Sequence[TreeEntry], seen_before: set[str]) -> SliceRecord:
    solved = sum(entry.proved for entry in members)
    difficulties = [entry.difficulty for entry in members if entry.difficulty is not None]
    bands = [*character_strata(CHARACTER_EDGES), "unknown"]
    by_band = tuple(
        BandCount(
            band,
            sum(character_band(entry) == band for entry in members),
            sum(character_band(entry) == band and entry.proved for entry in members),
        )
        for band in bands
    )
    names = {entry.problem_name for entry in members}
    return SliceRecord(
        slice=number,
        directory=str(directory),
        trees=len(members),
        generated_tokens=sum(entry.summary.generated_tokens for entry in members),
        solved=solved,
        solved_share=solved / len(members) if members else 0.0,
        first_finished_time=members[0].finished_time if members else 0.0,
        last_finished_time=members[-1].finished_time if members else 0.0,
        difficulty_low=min(difficulties) if difficulties else None,
        difficulty_high=max(difficulties) if difficulties else None,
        by_character_band=tuple(count for count in by_band if count.trees),
        below_band_share=sum(entry.summary.below_band for entry in members) / len(members) if members else 0.0,
        statements=len(names),
        statements_seen_before=len(names & seen_before),
        trainable_groups=sum(entry.summary.trainable_groups for entry in members),
        mean_expansions=sum(entry.expansions for entry in members) / len(members) if members else 0.0,
    )


def write_slices(
    trees_directory: Path, slices: Sequence[Sequence[TreeEntry]], output: Path, index_lines: int
) -> SliceManifest:
    """Slice k's links under output/slice_k/ (absolute, to the trees' files), its index and the manifest; refuses an
    existing output, so the slices stay as first cut."""
    if output.exists():
        raise ValueError(f"{output} exists: the slices are cut once.")
    # A slice links its trees by file name: trees of one name in two phase directories would collide.
    names = [Path(entry.file).name for members in slices for entry in members]
    assert len(set(names)) == len(names), "Trees of different phase directories share a file name."
    records = []
    seen: set[str] = set()
    for number, members in enumerate(slices, start=1):
        directory = output / slice_directory_name(number)
        directory.mkdir(parents=True)
        lines = []
        for entry in members:
            link = directory / Path(entry.file).name
            os.symlink((trees_directory / entry.file).resolve(), link)
            lines.append(to_json(dataclasses.replace(entry, file=link.name)) + "\n")
        (directory / INDEX_FILE).write_text("".join(lines), encoding="utf-8")
        records.append(slice_record(number, directory, members, seen))
        seen |= {entry.problem_name for entry in members}
    manifest = SliceManifest(
        trees_directory=str(trees_directory),
        index_lines=index_lines,
        trees=sum(record.trees for record in records),
        generated_tokens=sum(record.generated_tokens for record in records),
        slices=tuple(records),
    )
    (output / MANIFEST_FILE).write_text(to_json(manifest) + "\n", encoding="utf-8")
    return manifest
