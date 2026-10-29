import asyncio
import dataclasses
import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from loop_fakes import LOOP_TOML

from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.rl.loop import GrpoLoopPaths, TrainingRequest
from lean_search.rl.loop_config import parse_loop_config
from lean_search.rl.loop_services import ChildProcess, PersistentTrainer, run_logged, running_start_ticks
from lean_search.training.resident import HostDirectories

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="process groups and /proc are POSIX")

FAKE_JOB = Path(__file__).resolve().parent / "fake_trainer_job.py"


@dataclass
class TrainerWorld:
    root: Path
    trainer: PersistentTrainer
    log: list[str] = field(default_factory=list)

    @property
    def behaviour(self) -> Path:
        return self.root / "behaviour"

    def request(self, phase: int) -> TrainingRequest:
        trees = self.root / "trees" / f"phase_{phase:04d}"
        return TrainingRequest(phase, "", trees, f"loop_phase_{phase:04d}", self.root / "out" / str(phase), False)

    def lines(self, name: str) -> list[str]:
        path = self.behaviour / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@asynccontextmanager
async def persistent_trainer(
    root: Path, deaths: int = 0, hangs: int = 0, first_train_timeout_minutes: float = 45.0
) -> AsyncIterator[TrainerWorld]:
    paths = GrpoLoopPaths(root / "runs", root / "data", root / "checkpoints", "loop")
    behaviour = root / "behaviour"
    behaviour.mkdir()
    (behaviour / "deaths").write_text(str(deaths))
    (behaviour / "hangs").write_text(str(hangs))
    arguments = [sys.executable, str(FAKE_JOB), str(paths.training / "trainer"), str(behaviour)]
    log: list[str] = []
    config = dataclasses.replace(
        parse_loop_config(LOOP_TOML).training, first_train_timeout_minutes=first_train_timeout_minutes
    )
    trainer = PersistentTrainer(
        paths,
        config,
        arguments,
        dict(os.environ),
        HostDirectories(root / "host"),
        log.append,
        poll_seconds=0.01,
        stop_seconds=5.0,
    )
    try:
        yield TrainerWorld(root, trainer, log)
    finally:
        await trainer.close()


async def test_a_phase_returns_the_outcome_the_job_wrote(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        outcome = await world.trainer.train(world.request(3))
    assert outcome.trees == 3


async def test_one_job_trains_every_phase(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        for phase in (1, 2, 3):
            await world.trainer.train(world.request(phase))
        process_ids = {line.split()[0] for line in world.lines("trained")}
    assert len(process_ids) == 1


async def test_a_job_that_dies_while_training_is_started_again_and_trains_the_phase(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path, deaths=1) as world:
        outcome = await world.trainer.train(world.request(2))
    assert outcome.trees == 2


async def test_the_loop_log_reports_a_job_that_died_while_training(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path, deaths=1) as world:
        await world.trainer.train(world.request(2))
    assert any("ended while training phase 2" in line for line in world.log)


async def test_a_job_that_dies_twice_fails_the_phase(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path, deaths=2) as world:
        with pytest.raises(RuntimeError, match="failed twice"):
            await world.trainer.train(world.request(2))


async def test_a_job_that_hangs_while_training_is_stopped_and_trains_the_phase_again(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path, hangs=1, first_train_timeout_minutes=0.05) as world:
        outcome = await world.trainer.train(world.request(2))
    assert outcome.trees == 2


async def test_a_job_that_hangs_twice_fails_the_phase(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path, hangs=2, first_train_timeout_minutes=0.05) as world:
        with pytest.raises(RuntimeError, match="failed twice"):
            await world.trainer.train(world.request(2))


@pytest.mark.parametrize(
    ("value_phase", "minutes"), [(False, 15.0), (True, 30.0)], ids=["at least the minimum", "twice the median"]
)
async def test_a_later_phase_waits_the_timeout_of_its_kind(tmp_path: Path, value_phase: bool, minutes: float) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.train(world.request(1))
        world.trainer.train_seconds = {False: [60.0], True: [600.0, 900.0, 1200.0]}
        request = dataclasses.replace(world.request(2), train_value=value_phase)
        assert world.trainer.train_timeout_seconds(request) == minutes * 60


async def test_closing_removes_the_parked_weights(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.train(world.request(1))
        parked = world.trainer.host.parked
        parked.mkdir(parents=True)
        (parked / "policy.bin").write_bytes(b"weights")
    assert not parked.exists()


async def test_a_job_that_died_between_phases_is_started_again_for_the_next(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.train(world.request(1))
        os.kill(int(world.lines("trained")[0].split()[0]), signal.SIGKILL)
        while world.trainer.running():
            await asyncio.sleep(0.01)
        outcome = await world.trainer.train(world.request(2))
    assert outcome.trees == 2


async def test_a_prepare_reaches_the_job(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.prepare(world.request(4))
        while not world.lines("prepared") and world.trainer.running():
            await asyncio.sleep(0.01)
    assert world.lines("prepared") == ["4"]


async def test_closing_stops_the_job(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.train(world.request(1))
        process_id = int(world.lines("trained")[0].split()[0])
    assert running_start_ticks(process_id) is None


async def test_an_evaluation_job_starts_while_the_persistent_job_runs(tmp_path: Path) -> None:
    async with persistent_trainer(tmp_path) as world:
        await world.trainer.train(world.request(1))
        children = world.trainer.paths.children
        await run_logged([sys.executable, "-c", "pass"], tmp_path / "evaluation.log", {}, children / "evaluation.pid")
    assert not (children / "evaluation.pid").exists()


def test_a_persistent_job_left_by_an_earlier_loop_is_reported(tmp_path: Path) -> None:
    paths = GrpoLoopPaths(tmp_path / "runs", tmp_path / "data", tmp_path / "checkpoints", "loop")
    start_ticks = running_start_ticks(os.getpid())
    assert start_ticks is not None
    write_json_atomically(paths.children / "persistent" / "training.pid", ChildProcess(os.getpid(), start_ticks, "x"))
    trainer = PersistentTrainer(
        paths, parse_loop_config(LOOP_TOML).training, [], {}, HostDirectories(tmp_path / "host"), print
    )
    assert trainer.earlier_jobs() is not None
