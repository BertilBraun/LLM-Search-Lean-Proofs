"""A probe evaluation of any checkpoint outside a loop (experiments/probe_evaluate.py): a policy adapter with a value
adapter, value v0 or no value model, over the whole probe set with a given search config, concurrency and wall cap.

The run's directory holds what a loop's probe run holds (results.jsonl, summary.json, trees, config.toml), so
`probe_rating.finished_probe_runs` reads it, and run.json: the checkpoint and the share of searches stopped on the wall
clock against the configured maximum.
"""

import dataclasses
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.expert_iteration.loop_config import ServingConfig
from lean_search.rl.evaluation import EvaluationSummary
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.search_models import evaluation_run_config, served_run_config
from lean_search.rl.search_options import without_search_options
from lean_search.search import PriorityKind, RunConfig

# The value version recorded for a run without a value model.
NO_VALUE_VERSION = -1


@dataclass(frozen=True)
class ProbeEvaluationConfig:
    # A loop config: its [serving] (the servers, their model names and base models) and [initial] value_adapter (v0).
    loop_config: str
    # The search template (budgets, harvesting and ε are the probe's: off); `--search-config` replaces it per run.
    search_config: str
    # Under $LEAN_SEARCH_DATA.
    probe_set: str = "grpo/fixed_sets/probe_v2.jsonl"
    probe: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(16, 7200.0, 56))
    # A run with a larger share of searches stopped on the wall clock is rejected (run.json, the exit status).
    max_wall_clock_stop_share: float = 0.05
    # Under $LEAN_SEARCH_RUNS the runs (probe_<name>/), under $LEAN_SEARCH_CHECKPOINTS the merged weights.
    output: str = "probe_evaluations"


@dataclass(frozen=True)
class ProbeCheckpoint:
    policy_adapter: str
    # Empty: no value model, the search best-first on the policy's log-probabilities.
    value_adapter: str
    # The rating's labels (`probe_rating`: the lowest policy version is the anchor).
    policy_version: int
    value_version: int


@dataclass(frozen=True)
class ProbeRunStart:
    checkpoint: ProbeCheckpoint
    search_config: str


@dataclass(frozen=True)
class ProbeRunRecord:
    checkpoint: ProbeCheckpoint
    search_config: str
    problems: int
    solved: int
    wall_clock_stops: int
    wall_clock_stop_share: float
    max_wall_clock_stop_share: float
    accepted: bool


def resolve_value_adapter(value: str, value_v0_adapter: str) -> str:
    """`--value`: "none", "v0" (the loop config's starting value adapter) or an adapter's path."""
    match value:
        case "none":
            return ""
        case "v0":
            return value_v0_adapter
        case _:
            return value


def default_value_version(value: str) -> int | None:
    """None for an adapter's path: its label must be given."""
    match value:
        case "none":
            return NO_VALUE_VERSION
        case "v0":
            return 0
        case _:
            return None


def probe_run_config(
    template: RunConfig, serving: ServingConfig, target: EvaluationTarget, value_adapter: str
) -> RunConfig:
    """The template on the servers at the probe's budget, wall cap and REPLs, search options off; without a value
    adapter no value model and the value-free priority, the template's other priority settings kept."""
    if not value_adapter:
        template = dataclasses.replace(
            template,
            value=dataclasses.replace(template.value, model=""),
            priority=dataclasses.replace(template.priority, kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY),
        )
    return evaluation_run_config(served_run_config(without_search_options(template), serving), target)


def run_directory(runs_root: Path, name: str) -> Path:
    """`probe_` first, so that `probe_rating.finished_probe_runs(runs_root)` finds it."""
    return runs_root / f"probe_{name}"


def merged_weights_directory(weights_root: Path, adapter: str, kind: str) -> Path:
    """One merge per adapter path and kind (policy or value), reused by every run of it."""
    return weights_root / hashlib.sha256(adapter.encode()).hexdigest()[:16] / kind


def run_record(
    checkpoint: ProbeCheckpoint, search_config: str, summary: EvaluationSummary, max_share: float
) -> ProbeRunRecord:
    share = summary.wall_clock_stops / summary.problems
    return ProbeRunRecord(
        checkpoint=checkpoint,
        search_config=search_config,
        problems=summary.problems,
        solved=summary.solved,
        wall_clock_stops=summary.wall_clock_stops,
        wall_clock_stop_share=share,
        max_wall_clock_stop_share=max_share,
        accepted=share <= max_share,
    )
