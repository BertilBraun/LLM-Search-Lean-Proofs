"""experiments/learning_rate_step.py report end to end, over a state directory and a workspace in the files' real
formats: held-out runs of a few states (checkpoint.json, summary.json, one tree per state), the rank_<signal>.txt
choices, timings.tsv, the dry-run logs, each round's phase.json or training_summary.json and the shared run's
finished.json, all written through the production dataclasses."""

import dataclasses
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from loop_fakes import zero  # noqa: E402
from test_single_step import REFERENCE_NEXT, ROOT, STATEMENT, single_step_tree  # noqa: E402

from lean_search.corpora.records import DataSplit, TracedStep  # noqa: E402
from lean_search.reasoning.states import ReasoningState  # noqa: E402
from lean_search.rl.expert_iteration_data import TrainingSummary  # noqa: E402
from lean_search.rl.learning_rate_step import (  # noqa: E402
    STEP_VARIANTS,
    V0_END_HELD_OUT,
    V0_HELD_OUT,
    RoundKind,
    Signal,
)
from lean_search.rl.loop import RunFinished  # noqa: E402
from lean_search.rl.probe_evaluation import ProbeCheckpoint  # noqa: E402
from lean_search.rl.rate_ranking import HeldOutRunStart  # noqa: E402
from lean_search.rl.single_step import state_problem, state_tree_path  # noqa: E402
from lean_search.rl.training_phase import PhaseOutcome, PolicyOutcome  # noqa: E402
from lean_search.search import write_tree  # noqa: E402
from lean_search.search.records import to_json  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
VISIBLE = REPOSITORY / "experiments/configs/grpo/followup/modes/visible.toml"
STATES_FILE = "phase5_eval_visible_student_v2_visible/states.jsonl"
SHARED_RUN = "followup_shared_sampling"
# Every variant samples alike, so the rule ties within each signal and takes the lower rate, C's window 1 first.
CHOSEN = {Signal.A: "A_2e-5", Signal.B2: "B2_2e-5", Signal.C: "C_w1_5e-5"}
DRY_RUN = "Continuing v0's adapter /a: 800 expert-iteration examples, 9 steps on 4 GPUs\n"


def reasoning_state(index: int) -> ReasoningState:
    step = TracedStep(
        "s",
        f"s{index}/1",
        f"s{index}",
        DataSplit.VALIDATION,
        "",
        STATEMENT,
        1,
        3,
        2,
        (ROOT,),
        "simp",
        (REFERENCE_NEXT,),
        ("intro",),
        0,
        0,
    )
    return ReasoningState(f"s{index}/1#1", step, ((),), False)


STATES = [reasoning_state(index) for index in range(8)]


def write_held_out_run(runs: Path, name: str, states_sha256: str) -> None:
    directory = runs / "held_out_evaluations" / f"held_out_{name}"
    start = HeldOutRunStart(zero(ProbeCheckpoint), STATES_FILE, states_sha256, 56)
    (directory / "trees").mkdir(parents=True)
    (directory / "checkpoint.json").write_text(to_json(start), encoding="utf-8")
    (directory / "summary.json").write_text('{"dropped": []}', encoding="utf-8")
    for index, state in enumerate(STATES):
        write_tree(state_tree_path(directory / "trees", state_problem(state)), single_step_tree(closing=index % 2 == 0))


def write_round(checkpoints: Path, run_name: str, kind: RoundKind) -> None:
    output = checkpoints / run_name
    output.mkdir(parents=True)
    match kind:
        case RoundKind.GRPO:
            outcome = dataclasses.replace(zero(PhaseOutcome), trees=2400, policy=zero(PolicyOutcome))
            (output / "phase.json").write_text(to_json(outcome), encoding="utf-8")
        case RoundKind.EXPERT_ITERATION:
            summary = dataclasses.replace(
                zero(TrainingSummary), expert_iteration_examples=800, completion_token_shares=(0.6, 0.3, 0.1)
            )
            (output / "training_summary.json").write_text(to_json(summary), encoding="utf-8")


@dataclasses.dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    def environment(self) -> dict[str, str]:
        return os.environ | {
            "LEAN_SEARCH_RUNS": str(self.runs),
            "LEAN_SEARCH_DATA": str(self.root / "data"),
            "LEAN_SEARCH_CHECKPOINTS": str(self.root / "checkpoints"),
        }


def make_workspace(root: Path, earlier_states_sha256: str | None = None) -> Workspace:
    """`earlier_states_sha256`: the 2026-11-15 run's states digest (another file than today's), default today's."""
    workspace = Workspace(root)
    states = workspace.runs / STATES_FILE
    states.parent.mkdir(parents=True)
    states.write_text("".join(to_json(state) + "\n" for state in STATES), encoding="utf-8")
    digest = hashlib.sha256(states.read_bytes()).hexdigest()
    for name in (V0_HELD_OUT, V0_END_HELD_OUT, *(variant.run_name for variant in STEP_VARIANTS)):
        write_held_out_run(workspace.runs, name, digest)
    write_held_out_run(workspace.runs, "v0", earlier_states_sha256 or digest)
    for variant in STEP_VARIANTS:
        write_round(root / "checkpoints", variant.run_name, variant.kind)
    workspace.state.mkdir()
    for signal, label in CHOSEN.items():
        text = f"| table |\n\nChosen: {label} (tied on the held-out states, no gate runs; the lower rate)\n"
        (workspace.state / f"rank_{signal}.txt").write_text(text, encoding="utf-8")
    for build in ("step2_C_w1", "step2_C_w4"):
        (workspace.state / f"dry_run_{build}.log").write_text(DRY_RUN, encoding="utf-8")
    names = ["s1_sampling", f"held_out_{V0_HELD_OUT}", *(f"round_{variant.label}" for variant in STEP_VARIANTS)]
    timings = "".join(f"{name}\t1000\t{1000 + 3600 * (index + 1)}\n" for index, name in enumerate(names))
    (workspace.state / "timings.tsv").write_text(timings, encoding="utf-8")
    finished = workspace.runs / SHARED_RUN / "finished.json"
    finished.parent.mkdir(parents=True)
    finished.write_text(to_json(RunFinished(0, 48_100_000, 20_000, "2026-11-17T08:00:00+00:00")), encoding="utf-8")
    return workspace


def report(workspace: Workspace) -> subprocess.CompletedProcess:
    output = workspace.state / "learning_rates_report.md"
    arguments = ["--state", str(workspace.state), "--mode", str(VISIBLE), "--shared-run", SHARED_RUN]
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(REPOSITORY / "experiments" / "learning_rate_step.py"),
            "report",
            *arguments,
            "--earlier-v0",
            "v0",
            "--output",
            str(output),
        ],
        env=workspace.environment(),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> str:
    """The report over a complete state directory (one run of the command for the tests that read it)."""
    workspace = make_workspace(tmp_path_factory.mktemp("report"))
    result = report(workspace)
    assert result.returncode == 0, result.stderr
    return (workspace.state / "learning_rates_report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "line",
    [
        "| arms/A.toml | phase.policy.optimization.learning_rate | 2e-5 |",
        "| arms/B2.toml | phase.policy.optimization.learning_rate | 2e-5 |",
        "| arms/C.toml | loop.training.expert_iteration_window_phases | 1 |",
        "| arms/C.toml | expert_iteration.sft.optimization.learning_rate | 5e-5 |",
    ],
)
def test_the_report_from_real_files_states_the_arms_values(written: str, line: str) -> None:
    assert line in written.splitlines()


def test_the_report_from_real_files_pairs_every_variant_with_v0(written: str) -> None:
    assert "| A_1e-4 | 1e-4 | +0.0 [+0.0, +0.0] | within noise | +0.0 [+0.0, +0.0] | within noise |" in written


def test_the_report_from_real_files_compares_v0_after_the_variants_with_v0_before(written: str) -> None:
    assert "After the variants minus before them, paired per state" in written


def test_the_report_from_real_files_reads_the_rounds_sizes(written: str) -> None:
    assert ("| A_2e-5 | 2400 |" in written, "| C_w4_1e-4 | 800 |" in written) == (True, True)


def test_the_report_from_real_files_says_cs_window_came_from_the_tie_rule(written: str) -> None:
    assert "C's window was chosen by the tie rule" in written


def test_the_report_from_real_files_reads_the_shared_runs_tokens(written: str) -> None:
    assert "Shared sampling: 48,100,000 generated tokens counted, 20,000 lost." in written


def test_a_ranking_file_disagreeing_with_the_report_fails_it(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace.state / "rank_B2.txt").write_text("Chosen: B2_1e-4 (the held-out states decide)\n", encoding="utf-8")
    assert "rank_B2.txt chose B2_1e-4" in report(workspace).stderr


def test_an_earlier_v0_run_of_other_states_is_named_not_a_failure(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, earlier_states_sha256="0" * 64)
    result = report(workspace)
    text = (workspace.state / "learning_rates_report.md").read_text(encoding="utf-8")
    assert (result.returncode, "The earlier run is not compared: v0" in text) == (0, True)
