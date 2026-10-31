"""The loop's trees replayed under the reward of 2026-10-31 against the rules phases 1-12 trained with
(src/lean_search/rl/reward_replay.py), on the CPU: per phase the tactic label shares; the mean scores of bare claims,
attempts at invented and at provable claims, `have … :=` blocks and real closers, old against new over the same
samples; the ordering checks as violated pairs of samples within a group, under both rules; the samples, tactics and
groups whose advantage changes sign; and the drops. Any `FAILS` is a real inversion inside a group.

    nice -n 10 python experiments/reward_replay.py --trees /workspace/runs/grpo_loop_v1/trees --workers 6 \
        --output /workspace/runs/grpo_reward_replay

Reads trees/index.jsonl and the tree files (texts left out); an unreadable tree is counted and skipped. The reward is
[reward] of --phase-config (μ = 0). Prints the report and writes report.md and replay.jsonl (one PhaseReplay per phase,
then the total) to --output when given.
"""

import argparse
import tomllib
from dataclasses import dataclass
from functools import partial
from multiprocessing import Pool
from pathlib import Path

from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.reward_replay import TreeReplay, file_replay, report, total
from lean_search.rl.tree_store import TreeStore
from lean_search.search.records import from_json_object, to_json

PHASE_CONFIG = Path(__file__).resolve().parent / "configs" / "grpo" / "phase.toml"


@dataclass(frozen=True)
class PhaseReplay:
    # None: every phase replayed.
    phase: int | None
    replay: TreeReplay


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trees", type=Path, required=True, help="the loop's tree store")
    parser.add_argument("--phases", type=int, nargs="+", help="default: every phase in the index")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--phase-config", type=Path, default=PHASE_CONFIG)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    config = from_json_object(RewardConfig, tomllib.loads(arguments.phase_config.read_text(encoding="utf-8"))["reward"])
    store = TreeStore(arguments.trees)
    phases = sorted(arguments.phases or {entry.phase for entry in store.entries})
    by_phase: list[PhaseReplay] = []
    lines = []
    with Pool(arguments.workers) as pool:
        for phase in phases:
            paths = [store.directory / entry.file for entry in store.phase_entries(phase)]
            replay = total(list(pool.imap_unordered(partial(file_replay, config=config), paths, chunksize=8)))
            by_phase.append(PhaseReplay(phase, replay))
            lines.append(report(f"Phase {phase}", replay))
            print(lines[-1], flush=True)
    every = PhaseReplay(None, total([item.replay for item in by_phase]))
    lines.append(report(f"Phases {phases[0]}-{phases[-1]}", every.replay))
    print(lines[-1], flush=True)
    if arguments.output is not None:
        arguments.output.mkdir(parents=True, exist_ok=True)
        (arguments.output / "report.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        with (arguments.output / "replay.jsonl").open("w", encoding="utf-8") as handle:
            handle.writelines(to_json(item) + "\n" for item in [*by_phase, every])


if __name__ == "__main__":
    main()
