"""Stage 0 of the search options' measurement, from the loop's recorded trees, no GPU (src/lean_search/rl/
search_option_analysis.py): per phase the policy samples' outcomes and Lean error categories, how often the feedback
round would fire at min_children 1, 2 and 3 (and its extra generated tokens), and the held-out evaluation's error mix
against the loop's.

    python experiments/search_options_stage0.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1 \
        --output $LEAN_SEARCH_RUNS/grpo_search_variants_stage0

`--max-trees-per-phase` reads a seeded sample of each phase's trees; the held-out trees are those of the latest
held-out evaluation of the loop (evaluations/held_out_states_v<version>/trees), or of `--held-out-version`. Writes
report.md and summary.json to --output.
"""

import argparse
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.rl.search_option_analysis import (
    ErrorMix,
    FeedbackTriggers,
    error_mix,
    feedback_triggers,
    mix_table,
    trigger_table,
)
from lean_search.rl.tree_store import TreeStore
from lean_search.search.records import read_tree

HELD_OUT_DIRECTORY = re.compile(r"held_out_states_v(\d{4})")


@dataclass(frozen=True)
class PhaseAnalysis:
    phase: int
    mix: ErrorMix
    triggers: FeedbackTriggers


@dataclass(frozen=True)
class Stage0Summary:
    phases: tuple[PhaseAnalysis, ...]
    held_out_directory: str
    held_out: ErrorMix
    held_out_triggers: FeedbackTriggers


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-trees-per-phase", type=int, default=0, help="0: every tree")
    parser.add_argument("--held-out-version", type=int, help="default: the latest held-out evaluation")
    parser.add_argument("--feedback-samples", type=int, default=4, help="the round's samples, for its token cost")
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def analysed(paths: Sequence[Path]) -> tuple[ErrorMix, FeedbackTriggers]:
    mix = ErrorMix()
    triggers = FeedbackTriggers()
    for path in paths:
        record = read_tree(path, texts=False)
        mix += error_mix(record)
        triggers += feedback_triggers(record)
    return mix, triggers


def held_out_directory(evaluations: Path, version: int | None) -> Path | None:
    found = sorted(
        path
        for path in evaluations.glob("held_out_states_v*")
        if (match := HELD_OUT_DIRECTORY.fullmatch(path.name)) and (version is None or int(match[1]) == version)
    )
    return found[-1] if found else None


def main() -> None:
    arguments = parse_arguments()
    store = TreeStore(arguments.loop_directory / "trees")
    generator = random.Random(arguments.seed)
    phases = []
    for phase in sorted({entry.phase for entry in store.entries}):
        entries = store.phase_entries(phase)
        if arguments.max_trees_per_phase and len(entries) > arguments.max_trees_per_phase:
            entries = generator.sample(entries, arguments.max_trees_per_phase)
        mix, triggers = analysed([store.directory / entry.file for entry in entries])
        phases.append(PhaseAnalysis(phase, mix, triggers))
        print(f"phase {phase}: {mix.trees} trees, {mix.outcomes.total} samples", flush=True)
    directory = held_out_directory(arguments.loop_directory / "evaluations", arguments.held_out_version)
    held_out, held_out_triggers = analysed(sorted((directory / "trees").glob("*.json.gz")) if directory else [])
    loop_total = sum((analysis.mix for analysis in phases), ErrorMix())
    triggers_total = sum((analysis.triggers for analysis in phases), FeedbackTriggers())
    held_out_label = directory.name if directory else "none"
    sections = [
        "# Search options, stage 0\n",
        "## Policy samples by outcome and Lean error, per phase (shares of the samples)\n\n"
        + mix_table([*((f"phase {analysis.phase}", analysis.mix) for analysis in phases), ("all phases", loop_total)]),
        f"## Feedback round: share of policy expansions it would fire at (extra generated tokens of "
        f"{arguments.feedback_samples} more samples each, as a share of all)\n\n"
        + trigger_table(
            [
                *((f"phase {analysis.phase}", analysis.triggers) for analysis in phases),
                ("all phases", triggers_total),
                (f"held-out ({held_out_label})", held_out_triggers),
            ],
            arguments.feedback_samples,
        ),
        "## Held-out error mix against the loop's\n\n"
        + mix_table([(f"held-out ({held_out_label})", held_out), ("loop, all phases", loop_total)]),
    ]
    text = "\n".join(sections)
    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "report.md").write_text(text, encoding="utf-8")
    summary = Stage0Summary(tuple(phases), held_out_label, held_out, held_out_triggers)
    write_json_atomically(arguments.output / "summary.json", summary)
    print(text, flush=True)


if __name__ == "__main__":
    main()
