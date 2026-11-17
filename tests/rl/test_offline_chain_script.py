"""deployment/offline_chain.sh against stand-ins for every command it runs (tests/rl/study_chain_fakes/, shared with the
step-2 driver's test), restarted as supervisord would after any exit but 0: the order of its steps, its resume after a
kill at each step, its stops, and a start after its HOLD."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deployment" / "offline_chain.sh"
FAKES = Path(__file__).resolve().parent / "study_chain_fakes"
DEPLOYMENT_FAKES = (
    "environment.sh",
    "fake_common.sh",
    "grpo_loop.sh",
    "stop_model.sh",
    "background.sh",
    "probe_runs.sh",
)
SIDE_LINES = ("taskset ", "torchrun ", "trained ")
RATES = ("5e-5", "1e-4")


@dataclass(frozen=True)
class Node:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def scenario(self) -> Path:
        return self.root / "scenario"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def log(self) -> Path:
        return self.root / "commands.log"

    def set(self, name: str, text: str = "") -> None:
        (self.scenario / name).write_text(text, encoding="utf-8")

    def lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def steps(self) -> list[str]:
        return [line for line in self.lines() if not line.startswith(SIDE_LINES)]

    def stopped(self) -> str:
        return (self.state / "STOPPED").read_text(encoding="utf-8")


def executable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)


def make_node(root: Path) -> Node:
    node = Node(root)
    repository = root / "repository"
    for name in DEPLOYMENT_FAKES:
        executable(FAKES / name, repository / "deployment" / name)
    executable(FAKES / "python", repository / ".venv" / "bin" / "python")
    for name in ("taskset", "nvidia-smi"):
        executable(FAKES / name, root / "bin" / name)
    node.scenario.mkdir(parents=True)
    (node.workspace / "checkpoints" / "data_rewrite_sft_numbered" / "adapter").mkdir(parents=True)
    node.state.mkdir()
    return node


def start(node: Node) -> int:
    environment = os.environ | {
        "OFFLINE_CHAIN_STATE": str(node.state),
        "OFFLINE_CHAIN_REPOSITORY": str(node.root / "repository"),
        "OFFLINE_CHAIN_START_SECONDS": "0",
        "OFFLINE_CHAIN_POLL_SECONDS": "0",
        "FAKE_REPOSITORY": str(node.root / "repository"),
        "FAKE_WORKSPACE": str(node.workspace),
        "FAKE_BIN": str(node.root / "bin"),
        "FAKE_SCENARIO": str(node.scenario),
        "FAKE_LOG": str(node.log),
    }
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)], env=environment, start_new_session=True, timeout=300, check=False
    )
    return result.returncode


def supervise(node: Node, limit: int = 12) -> list[int]:
    codes = [start(node)]
    while codes[-1] != 0 and len(codes) < limit:
        codes.append(start(node))
    return codes


def held_out_steps(name: str) -> list[str]:
    return ["grpo_loop.sh servers", f"held_out_evaluate.py {name}", "learning_rate_step.py check-held-out"]


def subset_steps(subset: str, with_v0: bool) -> list[str]:
    steps = [f"dry run {subset} 5e-5", "stop_model.sh --all", *(f"train {subset} {rate}" for rate in RATES)]
    if with_v0:
        steps += held_out_steps("offline_v0_no_reasoning")
    for rate in RATES:
        steps += held_out_steps(f"offline_arm_{subset}_{rate}")
    return [
        *steps,
        f"rank_learning_rates.py {subset}",
        f"offline_arm.py probe-list {subset} {subset}_5e-5",
        f"probe_runs.sh PROBE_CONCURRENCY=112 runs_{subset}.toml",
        f"probe_compare.py pair offline_arm_{subset}",
        f"offline_arm.py report {subset}",
    ]


EXPECTED_STEPS = [
    "offline_arm.py download HF_HUB_OFFLINE=unset HF_HUB_DISABLE_XET=1",
    "offline_arm.py prepare",
    "offline_arm.py walk",
    "offline_arm.py build",
    "offline_arm.py held-out-config",
    *subset_steps("matched", with_v0=True),
    *subset_steps("pool", with_v0=False),
    "stop_model.sh --all",
]


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return make_node(tmp_path)


@pytest.fixture
def finished(tmp_path: Path) -> Node:
    node = make_node(tmp_path)
    assert supervise(node) == [0]
    return node


def test_a_clean_run_takes_the_steps_in_order(finished: Node) -> None:
    assert finished.steps() == EXPECTED_STEPS


def test_a_clean_run_ends_in_hold_with_the_servers_stopped(finished: Node) -> None:
    assert (finished.state / "HOLD").read_text(encoding="utf-8").rstrip().endswith("the servers are stopped")


def test_a_clean_run_writes_both_gate_reports(finished: Node) -> None:
    assert all((finished.state / f"report_{subset}.md").exists() for subset in ("matched", "pool"))


def test_every_training_runs_on_the_four_gpus_offline(finished: Node) -> None:
    launches = {line for line in finished.lines() if line.startswith("torchrun ")}
    assert launches == {"torchrun on CUDA_VISIBLE_DEVICES=0,1,2,3 HF_HUB_OFFLINE=1"}


def test_every_training_runs_on_the_training_cpus(finished: Node) -> None:
    assert {line for line in finished.lines() if line.startswith("taskset ")} == {"taskset 0-47,96-143"}


def test_a_start_after_hold_runs_nothing(finished: Node) -> None:
    before = finished.lines()
    assert (start(finished), finished.lines()) == (0, before)


KILL_POINTS = [
    "download",
    "walk",
    "build",
    "train_matched_5e-5",
    "held_out_offline_v0_no_reasoning",
    "rank_matched",
    "probe",
    "report",
    "train_pool_1e-4",
    "held_out_offline_arm_pool_5e-5",
]


def killed(node: Node, point: str) -> list[int]:
    node.set(f"kill_{point}")
    return supervise(node)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_every_kill_point_is_reached_and_kills_the_driver(node: Node, point: str) -> None:
    assert killed(node, point)[0] == -9


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_is_resumed_to_the_hold(node: Node, point: str) -> None:
    assert killed(node, point)[-1] == 0 and (node.state / "HOLD").exists()


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_trains_every_run_to_its_end_once(node: Node, point: str) -> None:
    killed(node, point)
    trained = sorted(line.removeprefix("trained ") for line in node.lines() if line.startswith("trained "))
    assert trained == sorted(f"offline_arm_{subset}_{rate}" for subset in ("matched", "pool") for rate in RATES)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_never_evaluates_a_missing_adapter_or_overwrites_an_output(node: Node, point: str) -> None:
    killed(node, point)
    assert [line for line in node.lines() if line.startswith(("MISSING", "OUTPUT EXISTS"))] == []


def test_a_training_killed_midway_restarts_into_a_fresh_output(node: Node) -> None:
    killed(node, "train_matched_5e-5")
    assert len(list((node.workspace / "checkpoints").glob("offline_arm_matched_5e-5.interrupted_*"))) == 1


def test_a_training_that_finished_before_failing_at_its_teardown_is_kept(node: Node) -> None:
    node.set("fail_after_train_matched_1e-4", "1")
    supervise(node)
    assert sum(line == "train matched 1e-4" for line in node.lines()) == 1


def test_v0s_held_out_run_is_shared_by_both_subsets(finished: Node) -> None:
    assert sum(line == "held_out_evaluate.py offline_v0_no_reasoning" for line in finished.lines()) == 1


def test_the_matched_subsets_probe_run_comes_before_the_pool_is_trained(finished: Node) -> None:
    lines = finished.lines()
    assert lines.index("probe_runs.sh PROBE_CONCURRENCY=112 runs_matched.toml") < lines.index("train pool 5e-5")


def test_a_failing_walk_is_retried_by_the_next_start(node: Node) -> None:
    node.set("fail_walk", "2")
    assert supervise(node) == [1, 1, 0]


def test_a_walk_failing_three_times_stops_the_chain(node: Node) -> None:
    node.set("fail_walk", "3")
    supervise(node)
    assert "step walk failed 3 times" in node.stopped()


def test_a_rejected_probe_run_stops_the_chain(node: Node) -> None:
    node.set("probe_exit", "3")
    supervise(node)
    assert "rejected" in node.stopped()


def test_a_probe_run_whose_servers_kept_dying_stops_the_chain(node: Node) -> None:
    node.set("probe_exit", "4")
    supervise(node)
    assert "kept dying" in node.stopped()


def test_a_probe_run_that_failed_otherwise_is_resumed(node: Node) -> None:
    node.set("probe_exit", "1")
    assert supervise(node) == [1, 0]


def test_busy_gpus_stop_the_chain_before_training(node: Node) -> None:
    node.set("gpu_memory", "0, 1\n1, 9000\n2, 1\n3, 1\n")
    supervise(node)
    assert "the GPUs stay in use" in node.stopped()


def test_a_refused_server_stop_stops_the_chain(node: Node) -> None:
    node.set("fail_stop", "1")
    supervise(node)
    assert "stop_model.sh refused" in node.stopped()
