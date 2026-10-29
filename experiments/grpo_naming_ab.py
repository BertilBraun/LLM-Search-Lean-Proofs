"""Cheap test (DESIGN.md "Order of work", step 3): the naming A/B, numbered vs descriptive hypothesis names.

    python experiments/grpo_naming_ab.py --config experiments/configs/grpo/naming_ab.toml probe --arm numbered
    python experiments/grpo_naming_ab.py --config ... probe --arm named
    python experiments/reasoning_retention.py \
        --config experiments/configs/evaluation/reasoning_retention_naming_ab.toml \
        run --gpu 0 --labels naming-numbered naming-named      # MATH-500, visible (thinking off)
    python experiments/grpo_naming_ab.py --config ... report

The arms are the two short fine-tunes of the data rewrite (experiments/configs/data_rewrite/sft_{numbered,named}.toml).
`probe` merges an arm's adapter (once, on the CPU), swaps it into the loop's policy servers in place and searches the
probe set at its budget with the loop's search template and value model; the named arm searches renamed statements
(grpo_fixed_sets.py rename) and every proof it finds is verified against the original statement. `report` compares
the arms on the probe (solved, by stratum), the unknown-name error rate per policy sample of the probe searches and
MATH-500 (the retention run's scores, when present), into $LEAN_SEARCH_RUNS/<name>/report.md. The winner becomes the
GRPO starting policy (with `[renaming] enabled = true` in the loop config if it is the named arm).
"""

import argparse
import asyncio
import datetime
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lean_search.policy.adapters import merge_adapter
from lean_search.policy.server_control import publish_weights
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary, read_summary
from lean_search.rl.fixed_targets import evaluate_target
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.phase_metrics import unknown_names
from lean_search.rl.renaming import read_renamings
from lean_search.rl.search_models import served_run_config
from lean_search.search import load_run_config, read_tree
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])
RETENTION_SCORES = RUNS_DIRECTORY / "reasoning_retention" / "models_nothinking"


@dataclass(frozen=True)
class NamingArm:
    name: str
    # The fine-tune's LoRA adapter on `base_model`.
    adapter: str
    # Search renamed statements (the named arm); the files under $LEAN_SEARCH_DATA.
    renamings: tuple[str, ...] = ()
    # Its label in the MATH-500 retention config.
    math500_label: str = ""


@dataclass(frozen=True)
class NamingAbConfig:
    name: str
    # The loop config whose search template, servers and probe budget the arms are compared with.
    loop_config: str
    base_model: str
    arms: tuple[NamingArm, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--arm", required=True)
    commands.add_parser("report")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def arm_directory(config: NamingAbConfig, arm: NamingArm) -> Path:
    return RUNS_DIRECTORY / config.name / arm.name


async def probe(config: NamingAbConfig, arm: NamingArm) -> None:
    loop = load_loop_config(REPOSITORY_DIRECTORY / config.loop_config)
    merged = CHECKPOINTS_DIRECTORY / config.name / arm.name / "merged"
    if not merged.exists():
        log(f"Merging {arm.adapter} into {config.base_model}")
        merge_adapter(config.base_model, Path(arm.adapter), merged)
    for server in loop.serving.policy_servers:
        await publish_weights(server.url, merged)
    log(f"Serving {arm.name} on {len(loop.serving.policy_servers)} policy servers")
    template = served_run_config(load_run_config(REPOSITORY_DIRECTORY / loop.sampling.search_config), loop.serving)
    renamings = read_renamings([DATA_DIRECTORY / path for path in arm.renamings]) if arm.renamings else None
    directory = arm_directory(config, arm) / "probe"
    directory.mkdir(parents=True, exist_ok=True)
    summary = await evaluate_target(
        EvaluationKind.PROBE,
        loop.evaluation,
        template,
        directory,
        (0, 0),
        DATA_DIRECTORY,
        RUNS_DIRECTORY,
        renamings,
        log,
    )
    log(f"{arm.name}: probe {summary.solved}/{summary.problems}")


def math500_accuracy(label: str) -> float | None:
    path = RETENTION_SCORES / label / "scores.jsonl"
    if not label or not path.exists():
        return None
    scores = [json.loads(line)["correct"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sum(scores) / len(scores) if scores else None


def arm_row(config: NamingAbConfig, arm: NamingArm) -> str | None:
    directory = arm_directory(config, arm) / "probe"
    if not (directory / "summary.json").exists():
        return None
    summary: EvaluationSummary = read_summary(directory / "summary.json")
    names = unknown_names([read_tree(path) for path in sorted((directory / "trees").glob("*.json.gz"))])
    strata = ", ".join(f"{outcome.stratum} {outcome.solved}/{outcome.problems}" for outcome in summary.by_stratum)
    accuracy = math500_accuracy(arm.math500_label)
    math = "–" if accuracy is None else f"{accuracy:.1%}"
    return (
        f"| {arm.name} | {summary.solved}/{summary.problems} | {strata} | {names.rate:.2%} ({names.samples:,} samples) "
        f"| {math} |"
    )


def report(config: NamingAbConfig) -> None:
    rows = [row for arm in config.arms if (row := arm_row(config, arm)) is not None]
    header = "| arm | probe solved | by stratum | unknown names per policy sample | MATH-500 visible |"
    text = "# Naming A/B\n\n" + "\n".join([header, "|---|---|---|---|---|", *rows]) + "\n"
    (RUNS_DIRECTORY / config.name).mkdir(parents=True, exist_ok=True)
    (RUNS_DIRECTORY / config.name / "report.md").write_text(text, encoding="utf-8")
    print(text)


def main() -> None:
    arguments = parse_arguments()
    config = from_json_object(NamingAbConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    match arguments.command:
        case "probe":
            (arm,) = (arm for arm in config.arms if arm.name == arguments.arm)
            asyncio.run(probe(config, arm))
        case "report":
            report(config)


if __name__ == "__main__":
    main()
