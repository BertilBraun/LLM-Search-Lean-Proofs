"""The expert-iteration loop's search service, with its training phases.

    setsid nohup python experiments/phase6_service.py --config experiments/configs/expert_iteration/loop.toml \
        >> $LEAN_SEARCH_RUNS/<loop>/service.log 2>&1 < /dev/null &

Needs phase6_loop.py init and the vLLM servers it prints. Searches pool statements with many concurrent searches and,
every training.new_proofs proofs (or training.max_minutes), pauses them in place, frees both GPUs, trains the policy
and the value model from their replay buffers, publishes the next version, restarts the servers and resumes
(src/lean_search/expert_iteration/{search_service,trainer}.py). Attempts and trees go to
$LEAN_SEARCH_RUNS/<loop>/search/shards/, training state and buffers to training/, phase data to
$LEAN_SEARCH_DATA/expert_iteration/<loop>/. SIGTERM stops it; a restart rebuilds the queue from the shards and first
finishes a phase that was interrupted.
"""

import argparse
import asyncio
import dataclasses
import datetime
import os
import signal
from pathlib import Path

from lean_search.expert_iteration.loop_config import load_loop_config
from lean_search.expert_iteration.merging import merged_publisher
from lean_search.expert_iteration.search_service import SearchService, served_run_config
from lean_search.expert_iteration.serving import LoopPaths, SleepRelease
from lean_search.expert_iteration.thinking_compression import CompressingShortener
from lean_search.expert_iteration.trainer import PhaseTrainer
from lean_search.search import load_run_config
from lean_search.value.training import ValueTrainingConfig

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
CHECKPOINTS_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"])


def log(message: str) -> None:
    print(f"{datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')} {message}", flush=True)


def value_training_continues() -> bool:
    """Whether value training can start from an adapter (ValueTrainingConfig.initial_adapter)."""
    return "initial_adapter" in {field.name for field in dataclasses.fields(ValueTrainingConfig)}


async def run(config_path: Path) -> None:
    config = load_loop_config(config_path)
    paths = LoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, config.name)
    template = load_run_config(REPOSITORY_DIRECTORY / config.search.search_config)
    publisher = merged_publisher(config, CHECKPOINTS_DIRECTORY)
    shortener = (
        CompressingShortener(config.training.compression, served_run_config(template, config).policy)
        if config.training.compress_reasoning
        else None
    )
    trainer = PhaseTrainer(
        config,
        paths,
        publisher,
        SleepRelease(publisher),
        CHECKPOINTS_DIRECTORY,
        log,
        value_training_continues(),
        shortener,
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    await SearchService(config, template, paths, trainer, log).run(stop)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    asyncio.run(run(parser.parse_args().config))


if __name__ == "__main__":
    main()
