"""The verified statement pool of grpo_loop_v1 and how the loop consumed it, for planning a follow-up's pool and probe.

    PYTHONPATH=src python experiments/analysis/statement_pool.py \
        [--dataset node_backup/2026-11-01/hf_dataset] [--metrics node_backup/2026-11-01/hf_run/run_logs/metrics] \
        [--phases results/followup_step0/phases.csv]

Reads the published verified_pool/verified.jsonl, fixed_sets/, run_logs/loop.log, search_trees/index.jsonl and the
probe results.jsonl of v0 (two runs per third) and of the final pass (v31, v33, v35), and prints markdown tables. The
verifier walked the candidates round-robin over proof-length buckets (known_proofs.stratified_candidates); the bucket of
each record, failed ones included, is recovered from its place in that round-robin, the rounds shrinking as buckets run
out.
"""

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

GPUS = 4
MINIMUM_PROOF_TACTICS = 2
# verification.stratified_last_bucket in pool_v3.toml: buckets 2..11 and one open-ended 12+.
LAST_BUCKET = 12
BUCKETS = tuple(range(MINIMUM_PROOF_TACTICS, LAST_BUCKET + 1))
# Rounds looked ahead when testing whether a bucket ran out.
LOOKAHEAD_ROUNDS = 4
REJECTED_PHASES = frozenset(range(5, 11))
FIRST_PHASE_AFTER_ROLLBACK = 11
ARM_GPU_HOURS = 100.0
PROBE_RUNS_VERSION_ZERO = (
    "probe_slot0000_v0000",
    "probe_slot0000_v0000_repeat1",
    "probe_slot0001_v0000",
    "probe_slot0001_v0000_repeat1",
    "probe_slot0002_v0000",
    "probe_slot0002_v0000_repeat1",
)
PROBE_RUNS_FINAL = ("probe_slot0015_v0031", "probe_slot0016_v0033", "probe_slot0017_v0035")
OPEN_END = 10**9
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) (.*)$")
TACTIC_BINS = ((2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 9), (9, 11), (11, 13), (13, OPEN_END))
CHARACTER_BINS = ((0, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 3000), (3000, 4500), (4500, OPEN_END))


@dataclass(frozen=True)
class PoolRecord:
    position: int
    name: str
    source: str
    bucket: int
    verified: bool
    automation_solved: bool
    load_failed: bool
    proof_tactics: int
    proof_characters: int
    seconds: float

    @property
    def usable(self) -> bool:
        return self.verified and not self.automation_solved


@dataclass(frozen=True)
class FedTree:
    name: str
    phase: int
    difficulty: float
    proved: bool
    below_band: bool
    trainable_groups: int
    solved_at_expansion: int | None


@dataclass(frozen=True)
class CurriculumRecord:
    phase: int
    finished_time: float
    band_low: float
    usable_in_curriculum: int


@dataclass(frozen=True)
class BandMove:
    time: float
    empty_band: bool


@dataclass(frozen=True)
class ProbeOutcome:
    record: PoolRecord
    version_zero_solves: int
    final_solves: int


@dataclass(frozen=True)
class Inputs:
    pool: list[PoolRecord]
    trees: list[FedTree]
    curriculum: list[CurriculumRecord]
    gpu_hours: dict[int, float]
    moves: list[BandMove]
    probe: list[ProbeOutcome]
    held_out: frozenset[str]

    def usable_by_name(self) -> dict[str, PoolRecord]:
        return {record.name: record for record in self.pool if record.usable}


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as lines:
        yield from (json.loads(line) for line in lines if line.strip())


def statement_name(statement: dict) -> str:
    return f"{statement['source']}.{statement['identifier']}".replace("/", "_")


def capped_bucket(tactics: int) -> int:
    return min(tactics, LAST_BUCKET)


def mismatch_rate(raw: Sequence[dict], start: int, active: Sequence[int]) -> float:
    """Share of verified records in the next rounds whose compiled proof's length is not their assumed bucket."""
    wrong = 0
    checked = 0
    position = start
    for _ in range(LOOKAHEAD_ROUNDS):
        for bucket in active:
            if position >= len(raw):
                break
            record = raw[position]
            position += 1
            if record["verified"]:
                checked += 1
                wrong += capped_bucket(record["proof_tactics"]) != bucket
    return wrong / checked if checked else 0.0


def assign_buckets(raw: Sequence[dict]) -> list[int]:
    """Each record's proof-length bucket from its place in the round-robin; a bucket that ran out leaves the rounds."""
    active = list(BUCKETS)
    buckets: list[int] = []
    position = 0
    while position < len(raw):
        current = mismatch_rate(raw, position, active)
        # A longer known proof compiling after the shortest failed explains a few mismatches, a shifted round many.
        if current > 0.3:
            options = [[bucket for bucket in active if bucket != removed] for removed in active]
            best = min(options, key=lambda option: mismatch_rate(raw, position, option))
            if mismatch_rate(raw, position, best) < current:
                active = best
        for bucket in active[: len(raw) - position]:
            buckets.append(bucket)
            position += 1
    return buckets


def read_pool(dataset: Path) -> list[PoolRecord]:
    raw = list(read_jsonl(dataset / "verified_pool" / "verified.jsonl"))
    return [
        PoolRecord(
            position,
            statement_name(record["statement"]),
            record["statement"]["source"],
            bucket,
            record["verified"],
            record["automation_solved"],
            record["load_failed"],
            record["proof_tactics"],
            record["proof_characters"],
            record["seconds"],
        )
        for position, (record, bucket) in enumerate(zip(raw, assign_buckets(raw), strict=True))
    ]


def read_trees(dataset: Path) -> list[FedTree]:
    return [
        FedTree(
            entry["problem_name"],
            entry["phase"],
            entry["difficulty"],
            entry["proved"],
            bool(entry["summary"].get("below_band")),
            entry["summary"]["trainable_groups"],
            entry["summary"]["solved_at_expansion"],
        )
        for entry in read_jsonl(dataset / "search_trees" / "index.jsonl")
    ]


def read_curriculum(metrics: Path) -> list[CurriculumRecord]:
    last_per_phase: dict[int, CurriculumRecord] = {}
    for record in read_jsonl(metrics / "curriculum.jsonl"):
        fields = record["fields"]
        last_per_phase[record["phase"]] = CurriculumRecord(
            record["phase"], record["time"], fields["band_low"], fields["verified_statements"]
        )
    return [last_per_phase[phase] for phase in sorted(last_per_phase)]


def read_gpu_hours(path: Path) -> dict[int, float]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        int(row["phase"]): GPUS
        * (float(row["sampling_seconds"]) + float(row["pause_seconds"]) + float(row["held_out_seconds"]))
        / 3600
        for row in rows
    }


def read_band_moves(dataset: Path) -> list[BandMove]:
    moves = []
    for line in (dataset / "run_logs" / "loop.log").read_text(encoding="utf-8").splitlines():
        match = LOG_LINE.match(line)
        if match is None or not match.group(2).startswith("Curriculum band"):
            continue
        time = datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC).timestamp()
        moves.append(BandMove(time, "band was empty" in match.group(2)))
    return moves


def probe_solves(dataset: Path, runs: Sequence[str]) -> Counter[str]:
    solves: Counter[str] = Counter()
    for run in runs:
        for result in read_jsonl(dataset / "evaluations" / run / "results.jsonl"):
            solves[result["problem_name"]] += result["proved"]
    return solves


def read_inputs(dataset: Path, metrics: Path, phases: Path) -> Inputs:
    pool = read_pool(dataset)
    by_name = {record.name: record for record in pool}
    fixed_sets = dataset / "fixed_sets" / "fixed_sets"
    probe_names = [statement_name(entry["statement"]) for entry in read_jsonl(fixed_sets / "probe.jsonl")]
    gate_names = [statement_name(entry["statement"]) for entry in read_jsonl(fixed_sets / "gate.jsonl")]
    version_zero = probe_solves(dataset, PROBE_RUNS_VERSION_ZERO)
    final = probe_solves(dataset, PROBE_RUNS_FINAL)
    return Inputs(
        pool,
        read_trees(dataset),
        read_curriculum(metrics),
        read_gpu_hours(phases),
        read_band_moves(dataset),
        [ProbeOutcome(by_name[name], version_zero[name], final[name]) for name in probe_names],
        frozenset(probe_names) | frozenset(gate_names),
    )


def print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    print("| " + " | ".join(headers) + " |")
    print("|" + "---|" * len(headers))
    for row in rows:
        print("| " + " | ".join(str(cell) for cell in row) + " |")
    print()


def bucket_label(bucket: int) -> str:
    return f"{bucket}+" if bucket == LAST_BUCKET else str(bucket)


def bin_label(bounds: tuple[int, int]) -> str:
    low, high = bounds
    if high == OPEN_END:
        return f"{low:,}+"
    return str(low) if high - low == 1 else f"{low:,}-{high - 1:,}"


def in_bin(value: float, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= value < bounds[1]


def share(part: float, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


def report_pool(inputs: Inputs) -> None:
    pool = inputs.pool
    usable = [record for record in pool if record.usable]
    print(f"## Verified pool: {len(pool):,} attempted, {len(usable):,} usable\n")
    by_bucket: dict[int, list[PoolRecord]] = defaultdict(list)
    for record in pool:
        by_bucket[record.bucket].append(record)
    rows = []
    for bucket in BUCKETS:
        records = by_bucket[bucket]
        verified = sum(record.verified for record in records)
        ran_out = records[-1].position < len(pool) - 2 * len(BUCKETS)
        rows.append(
            [
                bucket_label(bucket),
                f"{len(records):,}",
                share(verified, len(records)),
                share(sum(record.automation_solved for record in records), verified),
                f"{sum(record.usable for record in records):,}",
                f"{statistics.fmean(record.seconds for record in records):.1f}",
                f"all {len(records):,} candidates" if ran_out else "no",
            ]
        )
    print_table(
        ["shortest proof (tactics)", "attempted", "verified", "trivial of verified", "usable", "mean s", "ran out"],
        rows,
    )
    print("usable by source:", dict(Counter(record.source for record in usable).most_common()))
    print(
        f"mean seconds per attempt {statistics.fmean(record.seconds for record in pool):.1f}, "
        f"per usable statement {sum(record.seconds for record in pool) / len(usable):.1f}; "
        f"a longer known proof compiled (bucket below the proof): "
        f"{sum(record.verified and capped_bucket(record.proof_tactics) != record.bucket for record in pool)}\n"
    )


def phase_of_time(curriculum: Sequence[CurriculumRecord], time: float) -> int:
    for record in curriculum:
        if time <= record.finished_time:
            return record.phase
    return curriculum[-1].phase + 1


def report_phases(inputs: Inputs) -> None:
    usable = [record for record in inputs.pool if record.usable]
    by_name = inputs.usable_by_name()
    trees_by_phase: dict[int, list[FedTree]] = defaultdict(list)
    for tree in inputs.trees:
        trees_by_phase[tree.phase].append(tree)
    empty_jumps = Counter(phase_of_time(inputs.curriculum, move.time) for move in inputs.moves if move.empty_band)
    print(
        "## Per phase (difficulty = shortest compiled proof's tactics for "
        f"{share(sum(tree.difficulty == by_name[tree.name].proof_tactics for tree in inputs.trees), len(inputs.trees))}"
        " of the trees: no root was ever scored)\n"
    )
    rows = []
    fed: set[str] = set()
    kept_gpu_hours = 0.0
    for record in inputs.curriculum:
        trees = trees_by_phase[record.phase]
        fed |= {tree.name for tree in trees}
        if record.phase not in REJECTED_PHASES:
            kept_gpu_hours += inputs.gpu_hours[record.phase]
        band = [tree for tree in trees if not tree.below_band]
        below = [tree for tree in trees if tree.below_band]
        unfed = [
            entry
            for entry in usable[: record.usable_in_curriculum]
            if entry.name not in fed and entry.name not in inputs.held_out
        ]
        low = record.band_low
        rows.append(
            [
                record.phase,
                "rejected" if record.phase in REJECTED_PHASES else f"{kept_gpu_hours:.0f}",
                f"{low:g}",
                f"{len(band)} ({share(sum(tree.proved for tree in band), len(band))})",
                f"{len(below)} ({share(sum(tree.proved for tree in below), len(below))})",
                f"{statistics.median(by_name[tree.name].proof_characters for tree in band):,.0f}",
                f"{len(unfed):,}",
                f"{sum(low <= entry.proof_tactics <= low + 1 for entry in unfed):,}",
                f"{sum(entry.proof_tactics >= low for entry in unfed):,}",
                f"{sum(entry.proof_characters >= 2000 for entry in unfed):,}",
                empty_jumps.get(record.phase, 0),
            ]
        )
    print_table(
        [
            "phase",
            "kept GPU-h",
            "band low",
            "from band (solved)",
            "from below (solved)",
            "band median proof chars",
            "unfed usable",
            "unfed in band",
            "unfed at/above band",
            "unfed with 2,000+ chars",
            "empty-band jumps",
        ],
        rows,
    )


def report_strata(inputs: Inputs) -> None:
    by_name = inputs.usable_by_name()
    fed_or_held_out = {tree.name for tree in inputs.trees} | inputs.held_out
    kept_trees = [tree for tree in inputs.trees if tree.phase >= FIRST_PHASE_AFTER_ROLLBACK]
    print("## By the shortest compiled proof's length: tactics (the curriculum's axis) and characters\n")
    axes: dict[str, tuple[tuple[tuple[int, int], ...], Callable[[PoolRecord], int]]] = {
        "tactics": (TACTIC_BINS, lambda record: record.proof_tactics),
        "characters": (CHARACTER_BINS, lambda record: record.proof_characters),
    }
    for axis, (bins, measure) in axes.items():
        rows = []
        for bounds in bins:
            usable = [record for record in by_name.values() if in_bin(measure(record), bounds)]
            probe = [outcome for outcome in inputs.probe if in_bin(measure(outcome.record), bounds)]
            trees = [tree for tree in kept_trees if in_bin(measure(by_name[tree.name]), bounds)]
            never_fed = [record for record in usable if record.name not in fed_or_held_out]
            rows.append(
                [
                    bin_label(bounds),
                    f"{len(usable):,}",
                    f"{len(never_fed):,}",
                    f"{statistics.fmean(record.seconds for record in usable):.0f}",
                    len(probe),
                    share(sum(outcome.version_zero_solves for outcome in probe) / 2, len(probe)),
                    share(sum(outcome.final_solves for outcome in probe), len(probe)),
                    share(
                        sum(outcome.version_zero_solves + outcome.final_solves == 0 for outcome in probe), len(probe)
                    ),
                    f"{share(sum(tree.proved for tree in trees), len(trees))} of {len(trees):,}",
                ]
            )
        print_table(
            [
                axis,
                "usable",
                "never fed",
                "verify s",
                "probe",
                "v0 solved",
                "final solved",
                "never solved",
                "loop trees solved (phases 11-31)",
            ],
            rows,
        )
    goedel = sorted(
        (outcome for outcome in inputs.probe if outcome.record.source == "goedel_sft_v2"),
        key=lambda outcome: outcome.record.proof_characters,
    )
    quarter = len(goedel) // 4
    quartiles = [goedel[index * quarter : (index + 1) * quarter] for index in range(4)]
    print(
        "goedel_sft_v2 probe statements only, by proof-character quartile, v0 / final:",
        [
            f"{share(sum(outcome.version_zero_solves for outcome in part) / 2, len(part))} / "
            f"{share(sum(outcome.final_solves for outcome in part), len(part))}"
            for part in quartiles
        ],
    )
    for source in ("goedel_sft_v2", "leanabell_sft"):
        part = [outcome for outcome in inputs.probe if outcome.record.source == source]
        print(
            f"{source}: {len(part)} probe statements, v0 "
            f"{share(sum(outcome.version_zero_solves for outcome in part) / 2, len(part))}, final "
            f"{share(sum(outcome.final_solves for outcome in part), len(part))}"
        )
    print()


def report_arm_demand(inputs: Inputs) -> None:
    """What the old run's kept line consumed in its first ~100 GPU-hours (logged), by origin."""
    kept_phases = [record.phase for record in inputs.curriculum if record.phase not in REJECTED_PHASES]
    chosen: list[int] = []
    total = 0.0
    for phase in kept_phases:
        if total >= ARM_GPU_HOURS:
            break
        chosen.append(phase)
        total += inputs.gpu_hours[phase]
    trees = [tree for tree in inputs.trees if tree.phase in chosen]
    band = [tree for tree in trees if not tree.below_band]
    print(
        f"## A ~{ARM_GPU_HOURS:.0f} GPU-h arm, from the old kept line: phases {chosen[0]}-{chosen[-1]} "
        f"({len(chosen)} phases, {total:.0f} GPU-h, {total / len(chosen):.1f} per phase)\n"
    )
    print(
        f"{len(trees):,} trees ({len(trees) / len(chosen):.0f} per phase), {len(band):,} from the band, "
        f"{len(trees) - len(band):,} from below; {len({tree.name for tree in trees}):,} distinct statements\n"
    )


def report_signal(inputs: Inputs) -> None:
    print("## Training signal per tree (phases 11-31)\n")
    kept = [tree for tree in inputs.trees if tree.phase >= FIRST_PHASE_AFTER_ROLLBACK]
    outcomes: dict[str, Callable[[FedTree], bool]] = {
        "unsolved": lambda tree: not tree.proved,
        "solved at expansion 1": lambda tree: tree.proved and tree.solved_at_expansion == 1,
        "solved at 2-4": lambda tree: tree.proved and 2 <= (tree.solved_at_expansion or 0) <= 4,
        "solved at 5+": lambda tree: tree.proved and (tree.solved_at_expansion or 0) >= 5,
    }
    rows = []
    for label, keep in outcomes.items():
        members = [tree for tree in kept if keep(tree)]
        rows.append(
            [
                label,
                f"{len(members):,}",
                share(len(members), len(kept)),
                f"{statistics.fmean(tree.trainable_groups for tree in members):.2f}",
            ]
        )
    print_table(["outcome", "trees", "share", "trainable groups per tree"], rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=Path("node_backup/2026-11-01/hf_dataset"))
    parser.add_argument("--metrics", type=Path, default=Path("node_backup/2026-11-01/hf_run/run_logs/metrics"))
    parser.add_argument("--phases", type=Path, default=Path("results/followup_step0/phases.csv"))
    arguments = parser.parse_args()
    inputs = read_inputs(arguments.dataset, arguments.metrics, arguments.phases)
    report_pool(inputs)
    report_phases(inputs)
    report_strata(inputs)
    report_arm_demand(inputs)
    report_signal(inputs)


if __name__ == "__main__":
    main()
