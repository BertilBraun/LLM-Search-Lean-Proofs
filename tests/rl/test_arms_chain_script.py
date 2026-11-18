"""deployment/arms_chain.sh against stand-ins for every command it runs (tests/rl/arms_chain_fakes/: the loop,
arm_loop.sh, the checkout's python and nvidia-smi; the rest from tests/rl/study_chain_fakes/), restarted as
supervisord would after any exit but 0: the order of its steps, the adopted arm A, the smoke test's kill and restart,
the health stop and the owner's word, its resume after a kill at each step, its stops."""

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deployment" / "arms_chain.sh"
FAKES = Path(__file__).resolve().parent / "arms_chain_fakes"
SHARED_FAKES = Path(__file__).resolve().parent / "study_chain_fakes"
MODE = REPOSITORY / "experiments/configs/grpo/followup/modes/visible.toml"


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
    def runs(self) -> Path:
        return self.root / "workspace" / "runs"

    @property
    def log(self) -> Path:
        return self.root / "commands.log"

    def set(self, name: str, text: str = "") -> None:
        (self.scenario / name).write_text(text, encoding="utf-8")

    def lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def stopped(self) -> str:
        return (self.state / "STOPPED").read_text(encoding="utf-8")

    def chain_log(self) -> str:
        return (self.state / "chain.log").read_text(encoding="utf-8")


def executable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)


def make_node(root: Path) -> Node:
    node = Node(root)
    deployment = root / "repository" / "deployment"
    for name in ("environment.sh", "fake_common.sh", "stop_model.sh", "probe_runs.sh", "background.sh"):
        executable(SHARED_FAKES / name, deployment / name)
    for name in ("arm_loop.sh", "fake_loop.sh"):
        executable(FAKES / name, deployment / name)
    executable(FAKES / "python", root / "repository" / ".venv" / "bin" / "python")
    executable(FAKES / "nvidia-smi", root / "bin" / "nvidia-smi")
    node.scenario.mkdir(parents=True)
    node.state.mkdir()
    (root / "shm").mkdir()
    shutil.copyfile(MODE, root / "mode.toml")
    return node


def environment(node: Node, extra: dict[str, str] | None = None) -> dict[str, str]:
    return (
        os.environ
        | {
            "ARMS_CHAIN_STATE": str(node.state),
            "STUDY_CHAIN_STATE": str(node.root / "study_state"),
            "OFFLINE_CHAIN_STATE": str(node.root / "offline_state"),
            "ARMS_CHAIN_REPOSITORY": str(node.root / "repository"),
            "ARMS_CHAIN_MODE": str(node.root / "mode.toml"),
            "ARMS_CHAIN_START_SECONDS": "0",
            "ARMS_CHAIN_POLL_SECONDS": "0.05",
            "ARMS_CHAIN_SMOKE_POLL_SECONDS": "0.05",
            "ARMS_CHAIN_SAMPLE_SECONDS": "0.05",
            "ARMS_CHAIN_KILL_DELAY_SECONDS": "0",
            "ARMS_CHAIN_LOOP_EXIT_SECONDS": "5",
            "ARMS_CHAIN_GPU_WAIT_SECONDS": "0",
            "ARMS_CHAIN_LOCK_WAIT_SECONDS": "60",
            "ARMS_CHAIN_SHARED_MEMORY": str(node.root / "shm"),
            "FAKE_REPOSITORY": str(node.root / "repository"),
            "FAKE_WORKSPACE": str(node.root / "workspace"),
            "FAKE_BIN": str(node.root / "bin"),
            "FAKE_SCENARIO": str(node.scenario),
            "FAKE_LOG": str(node.log),
        }
        | (extra or {})
    )


def start(node: Node, extra: dict[str, str] | None = None) -> int:
    """One start of the driver, in a process group of its own (a fake's kill takes the whole group)."""
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)], env=environment(node, extra), start_new_session=True, timeout=300, check=False
    )
    return result.returncode


def supervise(node: Node, extra: dict[str, str] | None = None, limit: int = 12) -> list[int]:
    """Starts until an exit 0, as supervisord does with autorestart=unexpected and exitcodes=0."""
    codes = [start(node, extra)]
    while codes[-1] != 0 and len(codes) < limit:
        codes.append(start(node, extra))
    return codes


def loop_starts(node: Node) -> list[str]:
    return [line for line in node.lines() if line.startswith("arm_loop.sh ")]


def held(node: Node) -> bool:
    return (node.state / "HOLD").exists()


@pytest.fixture(scope="module")
def finished(tmp_path_factory: pytest.TempPathFactory) -> Node:
    """A node whose driver ran everything once without trouble."""
    node = make_node(tmp_path_factory.mktemp("finished"))
    assert supervise(node) == [0]
    return node


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return make_node(tmp_path)


def test_a_clean_run_starts_the_loops_in_order(finished: Node) -> None:
    expected = ["arm_loop.sh arm A", "arm_loop.sh smoke C", "arm_loop.sh smoke D", "arm_loop.sh smoke D"]
    assert loop_starts(finished) == [*expected, "arm_loop.sh arm C", "arm_loop.sh arm D"]


def test_a_clean_run_probes_each_arm_once_at_the_studys_concurrency(finished: Node) -> None:
    probes = [line for line in finished.lines() if line.startswith("probe_runs.sh ")]
    assert probes == [f"probe_runs.sh PROBE_CONCURRENCY=112 runs_{arm}.toml" for arm in "ACD"]


def test_each_probe_run_follows_its_arms_adapters(finished: Node) -> None:
    order = [line for line in finished.lines() if line.startswith(("arms_chain.py adapters", "probe_runs.sh"))]
    assert order == [
        line
        for arm in "ACD"
        for line in ("arms_chain.py adapters", f"probe_runs.sh PROBE_CONCURRENCY=112 runs_{arm}.toml")
    ]


def test_the_last_arm_is_compared_with_the_anchors_run_7_and_both_arms_before_it(finished: Node) -> None:
    compared = [line for line in finished.lines() if line.startswith("probe_compare.py pair arm_D")]
    labels = [line.split(" against ", 1)[1] for line in compared]
    assert labels == ["v0 anchors", "v35 value final", "arm A", "arm C"]


def test_the_smoke_test_runs_between_arm_a_and_arm_c(finished: Node) -> None:
    lines = finished.lines()
    assert lines.index("arms_chain.py smoke-check") < lines.index("arm_loop.sh arm C") and lines.index(
        "probe_runs.sh PROBE_CONCURRENCY=112 runs_A.toml"
    ) < lines.index("arm_loop.sh smoke C")


def test_the_smoke_loop_of_d_is_killed_while_publishing(finished: Node) -> None:
    record = (finished.state / "smoke" / "kill_D.json").read_text(encoding="utf-8")
    assert '"stage": "publishing"' in record and '"phase": 1' in record


def test_the_killed_smoke_loop_resumes_without_training_again(finished: Node) -> None:
    run = finished.runs / "followup_smoke_D"
    trained = (run / "trained").read_text(encoding="utf-8").splitlines()
    assert (trained, (run / "published").read_text(encoding="utf-8").splitlines()) == (["trained 1"], ["published 1"])


def test_the_restart_after_the_kill_uses_no_attempt(finished: Node) -> None:
    assert (finished.state / "attempts_loop_smoke_D_start").read_text(encoding="utf-8").strip() == "1"


def test_the_smoke_runs_gpu_memory_and_shared_memory_are_sampled(finished: Node) -> None:
    lines = (finished.state / "smoke" / "readings_D.tsv").read_text(encoding="utf-8").splitlines()
    assert any(line.split("\t")[2] == "training" and len(line.split("\t")) == 8 for line in lines)


def test_every_loop_starts_after_the_servers_stopped_and_the_gpus_free(finished: Node) -> None:
    lines = finished.lines()
    assert all(
        lines[index - 1] == "stop_model.sh --all" for index, line in enumerate(lines) if line.startswith("arm_loop")
    )


def test_a_clean_run_ends_in_hold_with_the_servers_stopped(finished: Node) -> None:
    hold = (finished.state / "HOLD").read_text(encoding="utf-8")
    assert (finished.lines()[-1], hold.rstrip().endswith("the servers are stopped")) == ("stop_model.sh --all", True)


def test_a_start_after_hold_runs_nothing(finished: Node) -> None:
    before = finished.lines()
    assert (start(finished), finished.lines()) == (0, before)


def test_a_running_arm_a_is_adopted_not_started_again(node: Node) -> None:
    run = node.runs / "followup_A"
    run.mkdir(parents=True)
    loop = subprocess.Popen(  # noqa: S603
        ["bash", str(FAKES / "fake_loop.sh"), "grpo_loop.py", str(run), "16", "0.1", str(node.scenario)],
        start_new_session=True,
    )
    (run / "loop.pid").write_text(f"{loop.pid}\n", encoding="utf-8")
    codes = supervise(node)
    loop.wait()
    before_adapters = node.lines()[: node.lines().index("arms_chain.py adapters")]
    assert (codes, before_adapters, "adopted" in node.chain_log()) == ([0], [], True)


def test_a_loop_that_died_is_started_again(node: Node) -> None:
    node.set("die_followup_C", "1")
    assert supervise(node) == [0] and loop_starts(node).count("arm_loop.sh arm C") == 2


def test_a_loop_dying_on_every_start_stops_the_chain_after_three(node: Node) -> None:
    node.set("die_followup_A", "9")
    supervise(node)
    assert (loop_starts(node), node.stopped().split(" ", 1)[1]) == (
        ["arm_loop.sh arm A"] * 3,
        "step loop_A_start failed 3 times\n",
    )


def test_a_health_stop_stops_the_chain_with_a_report_and_the_servers_stopped(node: Node) -> None:
    node.set("health_stop_followup_C")
    supervise(node)
    reported = (node.state / "health_report_C.md").exists()
    assert ("arm C stopped on its health rule" in node.stopped(), reported, node.lines()[-1]) == (
        True,
        True,
        "stop_model.sh --all",
    )


def test_a_health_stopped_arm_is_never_started_again(node: Node) -> None:
    node.set("health_stop_followup_C")
    supervise(node)
    (node.state / "STOPPED").rename(node.state / "STOPPED.health_C")
    supervise(node)
    assert loop_starts(node).count("arm_loop.sh arm C") == 1


def owner_word(node: Node, word: str) -> None:
    node.set("health_stop_followup_C")
    supervise(node)
    (node.state / "word_C").write_text(f"{word}\n", encoding="utf-8")
    (node.state / "STOPPED").rename(node.state / "STOPPED.health_C")
    assert supervise(node) == [0]


def test_after_skip_the_stopped_arm_gets_no_probe_run_and_the_next_arm_runs(node: Node) -> None:
    owner_word(node, "skip")
    probes = [line for line in node.lines() if line.startswith("probe_runs.sh ")]
    assert (probes, held(node)) == (
        ["probe_runs.sh PROBE_CONCURRENCY=112 runs_A.toml", "probe_runs.sh PROBE_CONCURRENCY=112 runs_D.toml"],
        True,
    )


def test_after_skip_the_next_arm_is_not_compared_with_the_skipped_one(node: Node) -> None:
    owner_word(node, "skip")
    labels = [line.split(" against ", 1)[1] for line in node.lines() if line.startswith("probe_compare.py pair arm_D")]
    assert labels == ["v0 anchors", "v35 value final", "arm A"]


def test_after_evaluate_the_stopped_arm_gets_its_probe_run(node: Node) -> None:
    owner_word(node, "evaluate")
    assert "probe_runs.sh PROBE_CONCURRENCY=112 runs_C.toml" in node.lines()


def test_an_unknown_word_stops_the_chain(node: Node) -> None:
    node.set("health_stop_followup_C")
    supervise(node)
    (node.state / "word_C").write_text("maybe\n", encoding="utf-8")
    (node.state / "STOPPED").rename(node.state / "STOPPED.health_C")
    supervise(node)
    assert "write skip or evaluate" in node.stopped()


def test_a_failed_smoke_test_stops_the_chain_before_arm_c(node: Node) -> None:
    node.set("smoke_fails")
    supervise(node)
    assert ("the smoke test failed" in node.stopped(), "arm_loop.sh arm C" in node.lines()) == (True, False)


def test_a_smoke_loop_that_never_publishes_long_enough_is_not_killed_and_fails_the_smoke_test(node: Node) -> None:
    supervise(node, {"ARMS_CHAIN_KILL_DELAY_SECONDS": "100"})
    assert "failed: D killed while publishing" in node.stopped()


def test_a_smoke_runs_health_stop_stops_the_chain_before_arm_c(node: Node) -> None:
    node.set("health_stop_followup_smoke_C")
    supervise(node)
    assert ("stopped on its health check" in node.stopped(), "arm_loop.sh smoke D" in node.lines()) == (True, False)


@pytest.mark.parametrize("status", [3, 4])
def test_a_rejected_probe_run_or_dying_servers_stop_the_chain(node: Node, status: int) -> None:
    node.set("probe_exit", str(status))
    supervise(node)
    assert f"exit {status}" in node.stopped()


def test_a_failing_probe_run_is_retried_and_resumed(node: Node) -> None:
    node.set("fail_probe", "1")
    assert supervise(node) == [1, 0] and held(node)


def test_a_failing_comparison_is_logged_and_the_chain_goes_on(node: Node) -> None:
    node.set("fail_probe_compare", "1")
    assert supervise(node) == [0] and "probe_compare.py failed" in node.chain_log()


KILL_POINTS = ["arms_chain_adapters", "probe", "arms_chain_compare-plan", "arms_chain_smoke-check", "arms_chain_report"]


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_is_resumed_to_hold(node: Node, point: str) -> None:
    node.set(f"kill_{point}")
    codes = supervise(node)
    assert (codes[0], codes[-1], held(node)) == (-9, 0, True)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_starts_no_loop_twice(node: Node, point: str) -> None:
    node.set(f"kill_{point}")
    supervise(node)
    expected = ["arm_loop.sh arm A", "arm_loop.sh smoke C", "arm_loop.sh smoke D", "arm_loop.sh smoke D"]
    assert loop_starts(node) == [*expected, "arm_loop.sh arm C", "arm_loop.sh arm D"]


def test_a_driver_killed_while_its_loop_runs_adopts_the_loop_at_the_next_start(node: Node) -> None:
    extra = {"FAKE_ARM_STAGE_SECONDS": "0.1"}
    driver = subprocess.Popen(["bash", str(SCRIPT)], env=environment(node, extra), start_new_session=True)  # noqa: S603
    deadline = time.monotonic() + 60
    while not (node.runs / "followup_A" / "loop_state.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    os.killpg(driver.pid, signal.SIGKILL)
    driver.wait()
    assert supervise(node, extra) == [0] and loop_starts(node).count("arm_loop.sh arm A") == 1


def killed_while_starting(node: Node, extra: dict[str, str]) -> None:
    """The driver started, killed (its whole group) once arm_loop.sh for A is in flight in its own session."""
    driver = subprocess.Popen(["bash", str(SCRIPT)], env=environment(node, extra), start_new_session=True)  # noqa: S603
    deadline = time.monotonic() + 60
    while "arm_loop.sh arm A" not in node.lines() and time.monotonic() < deadline:
        time.sleep(0.05)
    os.killpg(driver.pid, signal.SIGKILL)
    driver.wait()


def test_a_driver_killed_while_arm_loop_is_in_flight_starts_the_arm_once(node: Node) -> None:
    extra = {"FAKE_ARM_LOOP_SECONDS": "3"}
    killed_while_starting(node, extra)
    assert supervise(node, extra) == [0] and loop_starts(node).count("arm_loop.sh arm A") == 1


def test_a_driver_killed_while_arm_loop_is_in_flight_stops_no_server_under_it(node: Node) -> None:
    extra = {"FAKE_ARM_LOOP_SECONDS": "3"}
    killed_while_starting(node, extra)
    supervise(node, extra)
    lines = node.lines()
    assert lines[: lines.index("arms_chain.py adapters")] == ["stop_model.sh --all", "arm_loop.sh arm A"]


def test_a_second_start_while_the_run_lock_is_held_is_refused(node: Node) -> None:
    runs = node.runs
    runs.mkdir(parents=True)
    holder = subprocess.Popen(["flock", str(runs / "followup_A.lock"), "sleep", "30"])  # noqa: S603, S607
    try:
        deadline = time.monotonic() + 10
        while subprocess.run(["flock", "-n", str(runs / "followup_A.lock"), "true"], check=False).returncode == 0:  # noqa: S603, S607
            assert time.monotonic() < deadline
            time.sleep(0.05)
        supervise(node, {"ARMS_CHAIN_LOCK_WAIT_SECONDS": "1"})
    finally:
        holder.kill()
    assert ("is held for 1 s without a live loop" in node.stopped(), loop_starts(node)) == (True, [])


def test_another_runs_live_loop_stops_the_chain_before_anything_runs(node: Node) -> None:
    run = node.runs / "followup_shared_sampling"
    run.mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])  # noqa: S603, S607
    (run / "loop.pid").write_text(f"{sleeper.pid}\n", encoding="utf-8")
    try:
        supervise(node)
    finally:
        sleeper.kill()
    assert ("the loop of" in node.stopped() and "followup_shared_sampling" in node.stopped(), node.lines()) == (
        True,
        [],
    )


def test_a_paused_arm_is_not_started(node: Node) -> None:
    (node.state / "pause_A").touch()
    supervise(node)
    assert ("A is paused" in node.stopped(), loop_starts(node)) == (True, [])


def test_an_arm_paused_while_it_runs_is_not_started_again_once_stopped(node: Node) -> None:
    extra = {"FAKE_ARM_STAGE_SECONDS": "0.1"}
    driver = subprocess.Popen(["bash", str(SCRIPT)], env=environment(node, extra), start_new_session=True)  # noqa: S603
    run = node.runs / "followup_A"
    deadline = time.monotonic() + 60
    while not (run / "loop_state.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    (node.state / "pause_A").touch()
    os.kill(int((run / "loop.pid").read_text(encoding="utf-8")), signal.SIGTERM)
    driver.wait(timeout=120)
    assert ("A is paused" in node.stopped(), loop_starts(node)) == (True, ["arm_loop.sh arm A"])


def test_a_paused_arm_resumes_once_the_pause_is_lifted(node: Node) -> None:
    node.set("die_followup_A", "1")
    (node.state / "pause_A").touch()
    supervise(node)
    (node.state / "pause_A").unlink()
    (node.state / "STOPPED").rename(node.state / "STOPPED.paused")
    assert supervise(node) == [0] and loop_starts(node).count("arm_loop.sh arm A") == 2


def continue_after_health_stop(node: Node) -> None:
    node.set("health_stop_followup_C")
    (node.state / "on_health_stop").write_text("continue\n", encoding="utf-8")
    supervise(node)


def test_with_continue_the_next_arm_runs_after_a_health_stop(node: Node) -> None:
    continue_after_health_stop(node)
    assert "arm_loop.sh arm D" in node.lines() and "probe_runs.sh PROBE_CONCURRENCY=112 runs_D.toml" in node.lines()


def test_with_continue_the_chain_asks_for_the_word_at_the_end_with_the_servers_stopped(node: Node) -> None:
    continue_after_health_stop(node)
    assert ("waits for the owner's word" in node.stopped(), node.lines()[-1]) == (True, "stop_model.sh --all")


def test_with_continue_the_stopped_arm_is_evaluated_after_the_word_against_both_other_arms(node: Node) -> None:
    continue_after_health_stop(node)
    (node.state / "word_C").write_text("evaluate\n", encoding="utf-8")
    (node.state / "STOPPED").rename(node.state / "STOPPED.word_C")
    assert supervise(node) == [0] and held(node)
    labels = [line.split(" against ", 1)[1] for line in node.lines() if line.startswith("probe_compare.py pair arm_C")]
    assert labels == ["v0 anchors", "v35 value final", "arm A", "arm D"]


def test_an_unknown_on_health_stop_stops_the_chain(node: Node) -> None:
    node.set("health_stop_followup_C")
    (node.state / "on_health_stop").write_text("later\n", encoding="utf-8")
    supervise(node)
    assert "write wait or continue" in node.stopped()


SMOKE_STARTS = ["arm_loop.sh smoke C", "arm_loop.sh smoke D", "arm_loop.sh smoke D"]


def ordered(node: Node, order: str) -> None:
    (node.state / "order").write_text(f"{order}\n", encoding="utf-8")


def test_the_order_file_sets_the_order(node: Node) -> None:
    ordered(node, "smoke C A D")
    assert supervise(node) == [0] and loop_starts(node) == [
        *SMOKE_STARTS,
        "arm_loop.sh arm C",
        "arm_loop.sh arm A",
        "arm_loop.sh arm D",
    ]


def test_an_order_may_span_lines(node: Node) -> None:
    ordered(node, "smoke\nC")
    supervise(node)
    assert loop_starts(node) == [*SMOKE_STARTS, "arm_loop.sh arm C"] and held(node)


@pytest.mark.parametrize(
    ("order", "refusal"),
    [
        ("smoke C B", "names 'B'"),
        ("smoke C C", "names C twice"),
        ("C smoke", "puts C before the smoke test"),
        ("A D", "puts D before the smoke test"),
        ("", "is empty"),
    ],
)
def test_a_bad_order_stops_the_chain_before_anything_runs(node: Node, order: str, refusal: str) -> None:
    ordered(node, order)
    supervise(node)
    assert (refusal in node.stopped(), node.lines()) == (True, [])


def test_an_order_without_the_smoke_test_is_accepted_once_it_is_done(node: Node) -> None:
    (node.state / "done_smoke").touch()
    ordered(node, "C")
    assert supervise(node) == [0] and loop_starts(node) == ["arm_loop.sh arm C"]


def old_stopped_arm_a(node: Node) -> Path:
    """Arm A's old run, stopped by hand: its run directory, a dead loop.pid, pause_A and hold_A."""
    run = node.runs / "followup_A"
    run.mkdir(parents=True)
    (run / "loop_state.json").write_text('{"phase": 7, "stage": "sampling"}\n', encoding="utf-8")
    (run / "loop.pid").write_text("999999999\n", encoding="utf-8")
    (node.state / "pause_A").touch()
    (node.state / "hold_A").touch()
    (node.state / "started_loop_A").write_text("1\n", encoding="utf-8")
    return run


@pytest.fixture
def waiting_for_a(node: Node) -> Node:
    """Order smoke C A D with A held: the chain ran the smoke test and C, then held."""
    ordered(node, "smoke C A D")
    old_stopped_arm_a(node)
    assert supervise(node) == [0]
    return node


def test_with_a_held_the_chain_runs_the_others_then_holds_waiting_for_a(waiting_for_a: Node) -> None:
    hold = (waiting_for_a.state / "HOLD").read_text(encoding="utf-8")
    assert ("waiting for: A" in hold, loop_starts(waiting_for_a)) == (True, [*SMOKE_STARTS, "arm_loop.sh arm C"])


def test_the_hold_comes_with_the_servers_stopped(waiting_for_a: Node) -> None:
    assert waiting_for_a.lines()[-1] == "stop_model.sh --all"


def test_a_held_arms_old_run_is_not_touched(waiting_for_a: Node) -> None:
    run = waiting_for_a.runs / "followup_A"
    assert sorted(path.name for path in run.iterdir()) == ["loop.pid", "loop_state.json"]


def test_a_held_arm_is_not_evaluated(waiting_for_a: Node) -> None:
    assert [line for line in waiting_for_a.lines() if line.endswith((" A", "runs_A.toml"))] == []


def test_once_the_hold_is_lifted_the_held_arm_starts_afresh_and_the_rest_follows(waiting_for_a: Node) -> None:
    node = waiting_for_a
    (node.runs / "followup_A").rename(node.runs / "followup_A.bug")
    for name in ("hold_A", "pause_A", "started_loop_A"):
        (node.state / name).unlink()
    (node.state / "HOLD").rename(node.state / "HOLD.waiting_for_A")
    assert supervise(node) == [0] and loop_starts(node)[-2:] == ["arm_loop.sh arm A", "arm_loop.sh arm D"]


def test_once_the_hold_is_lifted_each_arm_is_compared_with_every_other_done_arm(waiting_for_a: Node) -> None:
    node = waiting_for_a
    (node.runs / "followup_A").rename(node.runs / "followup_A.bug")
    for name in ("hold_A", "pause_A", "started_loop_A"):
        (node.state / name).unlink()
    (node.state / "HOLD").rename(node.state / "HOLD.waiting_for_A")
    supervise(node)
    labels = [line.split(" against ", 1)[1] for line in node.lines() if line.startswith("probe_compare.py pair arm_A")]
    assert labels == ["v0 anchors", "v35 value final", "arm C"]


def test_a_held_arm_whose_loop_runs_stops_the_chain(node: Node) -> None:
    ordered(node, "smoke C A D")
    run = node.runs / "followup_A"
    run.mkdir(parents=True)
    loop = subprocess.Popen(  # noqa: S603
        ["bash", str(FAKES / "fake_loop.sh"), "grpo_loop.py", str(run), "16", "1", str(node.scenario)],
        start_new_session=True,
    )
    (run / "loop.pid").write_text(f"{loop.pid}\n", encoding="utf-8")
    (node.state / "hold_A").touch()
    (node.state / "done_smoke").touch()
    (node.state / "done_loop_C").touch()
    for step in ("adapters_C", "probe_list_C", "probe_C", "compare_C", "report_C"):
        (node.state / f"done_{step}").touch()
    try:
        supervise(node)
    finally:
        loop.kill()
    assert ("arm A is held (hold_A) but its loop runs" in node.stopped(), loop_starts(node)) == (True, [])


def test_the_driver_records_the_checkout_each_loop_started_from(finished: Node) -> None:
    assert (finished.state / "loops" / "C.revisions").read_text(encoding="utf-8").count("\n") == 1


def other_chain_running(node: Node, directory: str, marker: str = "") -> None:
    state = node.root / directory
    state.mkdir(exist_ok=True)
    (state / "chain.log").write_text("driver start\n", encoding="utf-8")
    if marker:
        (state / marker).write_text("held\n", encoding="utf-8")


@pytest.mark.parametrize(("directory", "name"), [("study_state", "study"), ("offline_state", "offline")])
def test_a_running_other_chain_stops_the_arms_chain_before_anything_runs(node: Node, directory: str, name: str) -> None:
    other_chain_running(node, directory)
    supervise(node)
    assert (f"the {name} chain" in node.stopped(), node.lines()) == (True, [])


def test_other_chains_at_hold_let_the_arms_chain_run(node: Node) -> None:
    other_chain_running(node, "study_state", "HOLD")
    other_chain_running(node, "offline_state", "STOPPED")
    assert supervise(node) == [0] and held(node)


def test_without_the_mode_nothing_starts(node: Node) -> None:
    (node.root / "mode.toml").unlink()
    supervise(node)
    assert ("no sampling mode" in node.stopped(), node.lines()) == (True, [])


def test_gpus_held_by_another_process_stop_the_chain(node: Node) -> None:
    node.set("gpu_memory", "0, 9000, 24576\n1, 1, 24576\n2, 1, 24576\n3, 1, 24576\n")
    supervise(node)
    assert ("the GPUs stay in use" in node.stopped(), loop_starts(node)) == (True, [])
