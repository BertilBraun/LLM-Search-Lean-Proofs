"""Lists of probe evaluations for deployment/probe_runs.sh: each run one experiments/probe_evaluate.py command, the
lists' runs interleaved (an arm's phase 4, the other's, then phase 8, ...), a finished run skipped and an interrupted
one resumed by running its command again, and one ledger line per finished run. A run already started under a name is
skipped or resumed only when its record (checkpoint.json) is what the list asks for.

A run list is a TOML file of [[runs]] tables (`PlannedRun`), e.g. experiments/configs/grpo/followup/step1/. Evaluation
configs are read with their `base` resolved (`study_configs.resolved_toml`), as probe_evaluate.py reads them.
"""

import json
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import zip_longest
from pathlib import Path

from lean_search.rl.probe_evaluation import ProbeRunRecord, ProbeRunStart, ValueFreePriority, run_directory
from lean_search.rl.study_configs import PLACEHOLDER, placeholders, resolved_toml
from lean_search.search.records import from_json_object

DEFAULT_EVALUATION_CONFIG = "experiments/configs/grpo/followup/probe_evaluation.toml"
DEFAULT_OUTPUT = "probe_evaluations"
LEDGER_FILE = "ledger.tsv"
LEDGER_HEADER = "name\tidentity\tsolved\tproblems\twall-clock stop share\thours (last session)\taccepted\n"
VALUE_CHOICES = ("none", "v0")


@dataclass(frozen=True)
class PlannedRun:
    """probe_evaluate.py's arguments."""

    name: str
    arm: str
    phase: int
    policy_adapter: str
    # "none", "v0" or a value adapter's path.
    value: str
    value_version: int | None = None
    # The evaluation config (ProbeEvaluationConfig), relative to the repository.
    config: str = DEFAULT_EVALUATION_CONFIG
    search_config: str = ""
    problems: int = 0
    anchor: bool = False
    # What the run answers, for whoever reads the list.
    purpose: str = ""


@dataclass(frozen=True)
class RunList:
    runs: tuple[PlannedRun, ...]


def read_run_list(path: Path) -> RunList:
    return from_json_object(RunList, tomllib.loads(path.read_text(encoding="utf-8")))


def interleaved(lists: Sequence[RunList]) -> list[PlannedRun]:
    """The first run of every list, then the second of every list, ...; ValueError on a name given twice."""
    runs = [run for turn in zip_longest(*(run_list.runs for run_list in lists)) for run in turn if run is not None]
    names = [run.name for run in runs]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ValueError(f"Run names given more than once: {repeated}")
    return runs


def probe_arguments(run: PlannedRun) -> list[str]:
    arguments = ["--config", run.config, "--name", run.name, "--arm", run.arm, "--phase", str(run.phase)]
    arguments += ["--policy-adapter", run.policy_adapter, "--value", run.value]
    if run.value_version is not None:
        arguments += ["--value-version", str(run.value_version)]
    if run.search_config:
        arguments += ["--search-config", run.search_config]
    if run.problems:
        arguments += ["--problems", str(run.problems)]
    if run.anchor:
        arguments.append("--anchor")
    return arguments


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def evaluation_config(run: PlannedRun, repository: Path) -> dict:
    return resolved_toml(repository / run.config, repository)


def run_refusals(run: PlannedRun, repository: Path, concurrency: int) -> list[str]:
    """Why the run cannot start yet, from the repository alone: a placeholder in its own settings, its evaluation config
    or the search config it searches with, an uncalibrated automation constant for a value-free run, arguments
    probe_evaluate.py would refuse, or a probe concurrency other than the study's one."""
    own = {
        "policy_adapter": run.policy_adapter,
        "value": run.value,
        "config": run.config,
        "search_config": run.search_config,
    }
    refusals = [f"{run.name}: {key} is a placeholder" for key, value in own.items() if value.startswith(PLACEHOLDER)]
    if refusals:
        return refusals
    evaluation = evaluation_config(run, repository)
    refusals += [f"{run.name}: {run.config} has a placeholder at {key}" for key in placeholders(evaluation)]
    search_config = run.search_config or evaluation["search_config"]
    refusals += [
        f"{run.name}: {search_config} has a placeholder at {key}"
        for key in placeholders(read_toml(repository / search_config))
    ]
    if run.value == "none":
        priority = from_json_object(ValueFreePriority, evaluation.get("value_free_priority", {}))
        try:
            priority.automation_log_probability()
        except ValueError as error:
            refusals.append(f"{run.name}: {run.config}: {error}")
    if run.value not in VALUE_CHOICES and run.value_version is None:
        refusals.append(f"{run.name}: a value adapter given by path needs value_version")
    if run.anchor and (run.value != "v0" or run.phase or run.problems or run.search_config):
        refusals.append(f"{run.name}: the anchor is v0 with value v0 at phase 0, without search_config or problems")
    found = evaluation.get("probe", {}).get("concurrency")
    if found != concurrency:
        refusals.append(f"{run.name}: {run.config} searches at concurrency {found}, the study's is {concurrency}")
    return refusals


def missing_files(run: PlannedRun, repository: Path, data_root: Path) -> list[str]:
    """What the node lacks for the run: its adapters and its probe set."""
    paths = [Path(run.policy_adapter), *([Path(run.value)] if run.value not in VALUE_CHOICES else [])]
    missing = [f"{run.name}: no adapter directory at {path}" for path in paths if not path.is_dir()]
    probe_set = data_root / evaluation_config(run, repository)["probe_set"]
    if not probe_set.is_file():
        missing.append(f"{run.name}: no probe set at {probe_set}")
    return missing


def start_mismatches(run: PlannedRun, start: ProbeRunStart, repository: Path) -> list[str]:
    """Where a run already started under the name differs from what the list asks for."""
    evaluation = evaluation_config(run, repository)
    loop = read_toml(repository / evaluation["loop_config"])
    match run.value:
        case "none":
            value_adapter = ""
        case "v0":
            value_adapter = loop["initial"]["value_adapter"]
        case _:
            value_adapter = str(Path(run.value).absolute())
    expected = [
        ("policy adapter", start.checkpoint.policy_adapter, str(Path(run.policy_adapter).absolute())),
        ("value adapter", start.checkpoint.value_adapter, value_adapter),
        ("problems", start.checkpoint.problems, run.problems),
        ("anchor mark", start.anchor, run.anchor),
        ("search config", start.search_config, run.search_config or evaluation["search_config"]),
        ("probe set", start.probe_set, evaluation["probe_set"]),
        ("wall cap", start.max_wall_seconds, float(evaluation["probe"]["max_wall_seconds"])),
        ("concurrency", start.concurrency, evaluation["probe"]["concurrency"]),
    ]
    return [
        f"{run.name}: its record has {what} {found!r}, the list asks for {wanted!r}"
        for what, found, wanted in expected
        if found != wanted
    ]


def loop_configs(runs: Sequence[PlannedRun], repository: Path) -> list[str]:
    """The loop configs whose servers the runs search on: one, for one set of servers."""
    return sorted({evaluation_config(run, repository)["loop_config"] for run in runs})


def planned_directory(run: PlannedRun, runs_root: Path, repository: Path) -> Path:
    return run_directory(runs_root / evaluation_config(run, repository).get("output", DEFAULT_OUTPUT), run.name)


class RunState(StrEnum):
    # Not started, or interrupted: its command resumes it.
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def run_state(directory: Path) -> RunState:
    record = directory / "run.json"
    if not record.exists():
        return RunState.PENDING
    accepted = json.loads(record.read_text(encoding="utf-8"))["accepted"]
    return RunState.ACCEPTED if accepted else RunState.REJECTED


def recorded_start(directory: Path) -> ProbeRunStart | None:
    path = directory / "checkpoint.json"
    if not path.exists():
        return None
    return from_json_object(ProbeRunStart, json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class LedgerLine:
    name: str
    identity: str
    solved: int
    problems: int
    wall_clock_stop_share: float
    # The summary's wall clock: the last session's, when the run was resumed.
    hours: float
    accepted: bool

    @property
    def text(self) -> str:
        cells = [self.name, self.identity, self.solved, self.problems, f"{self.wall_clock_stop_share:.4f}"]
        return "\t".join(map(str, [*cells, f"{self.hours:.2f}", self.accepted])) + "\n"


def ledger_line(name: str, directory: Path) -> LedgerLine:
    record = from_json_object(ProbeRunRecord, json.loads((directory / "run.json").read_text(encoding="utf-8")))
    wall_seconds = json.loads((directory / "summary.json").read_text(encoding="utf-8"))["wall_seconds"]
    return LedgerLine(
        name,
        record.start.identity,
        record.solved,
        record.problems,
        record.wall_clock_stop_share,
        wall_seconds / 3600,
        record.accepted,
    )


def ledger_paths(runs: Sequence[PlannedRun], runs_root: Path, repository: Path) -> list[Path]:
    return sorted({planned_directory(run, runs_root, repository).parent / LEDGER_FILE for run in runs})


def recorded_names(ledger: Path) -> set[str]:
    if not ledger.exists():
        return set()
    return {line.split("\t", 1)[0] for line in ledger.read_text(encoding="utf-8").splitlines()[1:] if line}


def record_finished(runs: Sequence[PlannedRun], runs_root: Path, repository: Path) -> list[LedgerLine]:
    """One ledger line (beside the runs, <output>/ledger.tsv) per finished run not in it yet; returns the new lines."""
    added = []
    for run in runs:
        directory = planned_directory(run, runs_root, repository)
        ledger = directory.parent / LEDGER_FILE
        if run_state(directory) == RunState.PENDING or run.name in recorded_names(ledger):
            continue
        line = ledger_line(run.name, directory)
        if not ledger.exists():
            ledger.write_text(LEDGER_HEADER, encoding="utf-8")
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(line.text)
        added.append(line)
    return added
