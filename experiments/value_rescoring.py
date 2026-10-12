"""Time re-scoring open frontier states with the value model, as after publishing a new value version.

    python experiments/value_rescoring.py --config experiments/configs/phase3_astar_v0_sft_v2.toml \
        --trees $LEAN_SEARCH_RUNS/phase3_astar_v0_sft_v2/trees --states 20000

Takes up to --states distinct open states of a finished run's trees, scores them all at once through the config's
value servers and prints states per second.
"""

import argparse
import asyncio
import dataclasses
import json
import time
from pathlib import Path

from lean_search.search import NodeStatus, load_run_config, read_tree
from lean_search.value.estimator import open_value_estimator


@dataclasses.dataclass(frozen=True)
class RescoringResult:
    states: int
    seconds: float
    states_per_second: float
    prompt_tokens: int
    cached_prompt_tokens: int


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--trees", type=Path, required=True)
    parser.add_argument("--states", type=int, default=20000)
    return parser.parse_args()


def open_goals(trees: Path) -> list[tuple[str, ...]]:
    goals = (
        node.goals
        for path in sorted(trees.glob("*.json.gz"))
        for node in read_tree(path).nodes
        if node.status == NodeStatus.OPEN
    )
    return list(dict.fromkeys(goals))


async def rescore(config_path: Path, goals: list[tuple[str, ...]]) -> RescoringResult:
    config = load_run_config(config_path)
    async with open_value_estimator(config.value) as estimator:
        started = time.monotonic()
        await asyncio.gather(*(estimator.score(state) for state in goals))
        seconds = time.monotonic() - started
        statistics = estimator.statistics
    return RescoringResult(
        states=len(goals),
        seconds=seconds,
        states_per_second=len(goals) / seconds,
        prompt_tokens=statistics.prompt_tokens,
        cached_prompt_tokens=statistics.cached_prompt_tokens,
    )


def main() -> None:
    arguments = parse_arguments()
    goals = open_goals(arguments.trees)[: arguments.states]
    result = asyncio.run(rescore(arguments.config, goals))
    print(json.dumps(dataclasses.asdict(result), indent=1))


if __name__ == "__main__":
    main()
