"""The periodic evaluation of the expert-iteration loop: miniF2F-valid at a reduced budget every few versions.

    setsid nohup python experiments/phase6_evaluator.py --config experiments/configs/expert_iteration/loop.toml \
        >> $LEAN_SEARCH_RUNS/<loop>/evaluator.log 2>&1 < /dev/null &

When the current version is due (every evaluation.every_versions-th) and no training phase runs, evaluates it with
experiments/run_search.py on the served adapters at evaluation.max_expansions and evaluation.concurrency searches,
next to the search service. A lock file makes the next phase wait for the evaluation to finish. Results append to
$LEAN_SEARCH_RUNS/<loop>/evaluations.jsonl; the runs are <loop>_evaluation_v<version>.
"""

import argparse
import asyncio
import contextlib
import datetime
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from lean_search.expert_iteration.loop_config import LoopConfig, load_loop_config
from lean_search.expert_iteration.loop_evaluation import (
    EvaluationRecord,
    append_evaluation,
    due_version,
    evaluation_config_text,
    read_evaluations,
)
from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, read_versions
from lean_search.expert_iteration.shards import now
from lean_search.expert_iteration.trainer import PhaseStage, read_phase_state
from lean_search.search.records import from_json_object
from lean_search.search.summary import RunSummary

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])


def log(message: str) -> None:
    print(f"{datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')} {message}", flush=True)


def evaluate(config: LoopConfig, paths: LoopPaths, version: ModelVersion) -> None:
    run_name = f"{paths.name}_evaluation_v{version.version:04d}"
    run_directory = RUNS_DIRECTORY / run_name
    if run_directory.exists():
        # A run cut off earlier: run_search.py refuses existing results, so it moves aside.
        run_directory.rename(run_directory.with_name(f"{run_name}.incomplete_{int(time.time())}"))
    template = (REPOSITORY_DIRECTORY / config.evaluation.config).read_text(encoding="utf-8")
    config_path = paths.directory / "evaluations" / f"v{version.version:04d}.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(evaluation_config_text(template, config.serving, config.evaluation), encoding="utf-8")
    started_at = now()
    log(f"Evaluating version {version.version}")
    paths.evaluation_lock.write_text(started_at, encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                "python",
                "experiments/run_search.py",
                "--config",
                str(config_path),
                "--split",
                "valid",
                "--run-name",
                run_name,
            ],
            cwd=REPOSITORY_DIRECTORY,
            check=False,
        )
    finally:
        paths.evaluation_lock.unlink(missing_ok=True)
    if completed.returncode:
        log(f"Evaluation of version {version.version} failed (exit {completed.returncode}); retried later")
        return
    summary = from_json_object(
        RunSummary, json.loads((run_directory / "summary" / "summary.json").read_text(encoding="utf-8"))
    )
    record = EvaluationRecord(version.version, run_name, summary.problems, summary.solved, started_at, now())
    append_evaluation(paths.evaluations, record)
    log(f"Version {version.version}: {record.solved}/{record.problems}")


def phase_running(paths: LoopPaths) -> bool:
    state = read_phase_state(paths)
    return state is not None and state.stage != PhaseStage.DONE


async def run(config_path: Path) -> None:
    config = load_loop_config(config_path)
    paths = LoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, config.name)
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    while not stop.is_set():
        evaluated = {record.version for record in read_evaluations(paths.evaluations)}
        version = due_version(read_versions(paths), evaluated, config.evaluation)
        if version is not None and not phase_running(paths):
            await asyncio.to_thread(evaluate, config, paths, version)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.evaluation.check_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    asyncio.run(run(parser.parse_args().config))


if __name__ == "__main__":
    main()
