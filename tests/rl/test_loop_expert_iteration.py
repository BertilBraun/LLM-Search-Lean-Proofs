"""A GRPO-only loop records exactly what it recorded before expert iteration joined the loop: its phase records, metric
lines, versions and the phase configs it sent the trainer (tests/rl/golden/grpo_only_loop.json, captured on master
40c266d)."""

import json
from pathlib import Path

from loop_fakes import LoopWorld, run_until
from test_loop_budget import TOKEN_TOML, token_world

GOLDEN = Path(__file__).resolve().parent / "golden" / "grpo_only_loop.json"
# Wall-clock, machine and per-query readings: they differ run to run.
VOLATILE = ("finished_at", "cpu_counters", "gpus_at_start", "gpus_at_end", "time")
GOLDEN_FAMILIES = ("grpo", "value_training", "budget", "health", "timing")
GOLDEN_TOML = TOKEN_TOML.replace("value_every_phases = 1\n", "value_every_phases = 2\n")


def stable(value: object, root: str) -> object:
    match value:
        case dict():
            return {
                key: stable(item, root)
                for key, item in value.items()
                if key not in VOLATILE and not key.endswith("_seconds")
            }
        case list():
            return [stable(item, root) for item in value]
        case str():
            return value.replace(root, "<root>")
        case _:
            return value


def loop_records(world: LoopWorld, root: Path) -> object:
    """What the loop recorded and sent the trainer, without wall-clock, machine and temporary-path detail."""
    phases = [json.loads(line) for line in world.paths.phases.read_text(encoding="utf-8").splitlines()]
    metrics = {
        family: [
            json.loads(line)["fields"]
            for line in (world.paths.directory / "metrics" / f"{family}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for family in GOLDEN_FAMILIES
    }
    requests = [
        {
            "phase": request.phase,
            "config": request.config_text,
            "value_trees": [str(path) for path in request.value_trees],
        }
        for request in world.trainer.requests
    ]
    versions = world.paths.models.versions.read_text(encoding="utf-8").splitlines()
    records = {
        "phases": phases,
        "metrics": metrics,
        "requests": requests,
        "versions": [
            {key: value for key, value in json.loads(line).items() if key != "published_at"} for line in versions
        ],
    }
    return stable(records, str(root))


async def test_a_grpo_only_loop_records_what_it_recorded_before_expert_iteration(tmp_path: Path) -> None:
    world = token_world(tmp_path, GOLDEN_TOML)
    await run_until(world, world.loop(), phases=3)
    assert loop_records(world, tmp_path) == json.loads(GOLDEN.read_text(encoding="utf-8"))
