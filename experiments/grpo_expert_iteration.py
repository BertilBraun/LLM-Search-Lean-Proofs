"""One expert-iteration round of the GRPO loop (src/lean_search/rl/README.md, "Expert iteration"): fine-tuning the
current policy adapter on the loop's own verified proof-graph blocks as sampled, with replay.

    python experiments/grpo_expert_iteration.py --config experiments/configs/grpo/expert_iteration_1.toml count
    HF_HUB_OFFLINE=1 BACKGROUND_CPUS=16 deployment/background.sh python experiments/grpo_expert_iteration.py \
        --config experiments/configs/grpo/expert_iteration_1.toml build --processes 16
    HF_HUB_OFFLINE=1 python experiments/grpo_expert_iteration.py --config ... train --dry-run
    HF_HUB_OFFLINE=1 torchrun --standalone --nproc-per-node 4 experiments/grpo_expert_iteration.py \
        --config experiments/configs/grpo/expert_iteration_1.toml train
    python experiments/grpo_expert_iteration.py --config ... compare --version N [--against M]

The trees are those of [data] loop's phases from the reward fix's first phase (reward_fix.json) to [data] last_phase;
only samples of the version that phase published or later count, never a rejected version's. count reads only the
tree index. build labels the solved trees in a process pool, selecting as the trees arrive, and writes
$LEAN_SEARCH_DATA/grpo_expert_iteration/<[sft] data>/{train,validation}.jsonl (one ProofGraphCompletion per line: the
recorded prompt and token ids), summary.json and README.md. train fine-tunes (training/sft.py) the loop's current
policy adapter, read from models/current.json, on [sft] model with the Lean and math replay at their completion-token
shares, evaluating at the start, halfway and at the end on the expert-iteration and the replay validation sets apart;
--dry-run assembles the data and prints the steps without a GPU. The adapter goes to
$LEAN_SEARCH_CHECKPOINTS/<run_name>/adapter (refused if it exists) with continued_from.json (the version it continued,
which publish-adapter checks), training_summary.json (both validation curves) beside it, the steps to
$LEAN_SEARCH_RUNS/<run_name>/. compare judges a published round (rl/expert_iteration_decision.py) against the loop's
runs of the version it continued and before, or against another published version with --against.
"""

import argparse
import dataclasses
import datetime
import functools
import json
import math
import os
import re
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.data import load_minif2f
from lean_search.expert_iteration.serving import ModelVersion, read_current, read_versions
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.evaluation import EvaluationPaths, EvaluationSummary
from lean_search.rl.expert_iteration_data import (
    CompletionFilter,
    CompletionSelector,
    DataSummary,
    ExpertIterationConfig,
    ExpertIterationDataConfig,
    FilterCounts,
    SpaceRequirement,
    TrainingData,
    TreeCompletions,
    data_summary,
    file_completions,
    parse_expert_iteration_config,
    space_shortages,
    training_data,
    write_completions,
)
from lean_search.rl.expert_iteration_decision import HeldOutRun, RoundEvidence, median_explanation, round_checks
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.grpo_groups import RewardConfig
from lean_search.rl.health_checks import (
    CONTINUED_FROM_FILE,
    ContinuedVersion,
    RewardFix,
    check_continued_adapter,
    held_out_rates,
    read_rejected_versions,
)
from lean_search.rl.loop import GrpoLoopPaths, read_progress
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.policy_data import PolicyTokenizer
from lean_search.rl.probe_rating import (
    DifferenceInterval,
    ProbeRun,
    earlier_references,
    finished_probe_runs,
    paired_comparison,
    probe_ratings,
    read_markers,
)
from lean_search.rl.tree_store import TreeEntry
from lean_search.rl.tree_summary import SearchHabits, search_habits
from lean_search.search.graph_labels import goal_key
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import markdown_table
from lean_search.training.sft import (
    EvaluationRecord,
    StepRecord,
    ValidationSet,
    distributed_context,
    plan_steps,
    train,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))
OUTPUT_DIRECTORY = DATA_DIRECTORY / "grpo_expert_iteration"
SHARED_MEMORY = Path("/dev/shm")
# The adapter (~0.5 GB) and the merge publish-adapter writes (~9 GB) next to the loop's checkpoints.
MIN_FREE_CHECKPOINT_GIB = 20.0
# NCCL's buffers; the persistent trainer's parked bases (~28 GiB) must be gone from the 32 GiB tmpfs.
MIN_FREE_SHARED_MEMORY_GIB = 8.0
HELD_OUT_DIRECTORY = re.compile(r"held_out_states_v(\d{4})")
TRAINING_SUMMARY_FILE = "training_summary.json"
REPLAY_VALIDATION = "replay"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("count")
    build = commands.add_parser("build")
    build.add_argument("--processes", type=int, default=8)
    training = commands.add_parser("train")
    training.add_argument("--dry-run", action="store_true", help="assemble the data and plan the steps, then stop")
    compare = commands.add_parser("compare")
    compare.add_argument("--version", type=int, required=True, help="the published round's version")
    compare.add_argument("--against", type=int, help="another published version, head to head on the whole probe set")
    return parser.parse_args()


def loop_paths(config: ExpertIterationConfig) -> GrpoLoopPaths:
    return GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.data.loop)


def index_entries(paths: GrpoLoopPaths) -> list[TreeEntry]:
    """The tree index; a last line the running loop is still appending is left out."""
    lines = [line for line in (paths.trees / "index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = []
    for number, line in enumerate(lines, start=1):
        try:
            entries.append(from_json_object(TreeEntry, json.loads(line)))
        except ValueError:
            if number < len(lines):
                raise
    return entries


@dataclass(frozen=True)
class LoopInputs:
    paths: GrpoLoopPaths
    loop_config: GrpoLoopConfig
    first_phase: int
    last_phase: int
    completion_filter: CompletionFilter
    entries: tuple[TreeEntry, ...]


def loop_inputs(config: ExpertIterationConfig) -> LoopInputs:
    """The loop's phases, versions, held-out sets and trees of those phases, as its run directory records them."""
    paths = loop_paths(config)
    if not paths.reward_fix.exists():
        raise SystemExit(f"{paths.reward_fix} is missing: the reward fix's first phase is unknown.")
    first_phase = from_json_object(RewardFix, json.loads(paths.reward_fix.read_text(encoding="utf-8"))).first_phase
    minimum_version = read_markers(paths.directory).reward_fix_version
    if minimum_version is None:
        raise SystemExit(f"No version was published by phase {first_phase}, the reward fix's first phase.")
    last_phase = config.data.last_phase or read_progress(paths.progress).phase - 1
    loop_config = load_loop_config(paths.config)
    held_out_sets = {*loop_config.statements.held_out, loop_config.evaluation.probe_set}
    held_out_statements = {entry.name for path in held_out_sets for entry in read_fixed_set(DATA_DIRECTORY / path)}
    held_out_statements |= {problem.name for problem in load_minif2f()}
    states = read_records(RUNS_DIRECTORY / loop_config.evaluation.held_out_states_file, ReasoningState)
    completion_filter = CompletionFilter(
        minimum_version=minimum_version,
        rejected_versions=frozenset(read_rejected_versions(paths.rejected_versions)),
        held_out_statements=frozenset(held_out_statements),
        held_out_goal_keys=frozenset(goal_key(state.goals) for state in states),
    )
    entries = tuple(entry for entry in index_entries(paths) if first_phase <= entry.phase <= last_phase)
    return LoopInputs(paths, loop_config, first_phase, last_phase, completion_filter, entries)


def count(config: ExpertIterationConfig) -> None:
    inputs = loop_inputs(config)
    held_out = inputs.completion_filter.held_out_statements
    rows = []
    for phase in range(inputs.first_phase, inputs.last_phase + 1):
        solved = [entry for entry in inputs.entries if entry.phase == phase and entry.proved]
        usable = [entry for entry in solved if entry.problem_name not in held_out]
        rows.append(
            [
                phase,
                sum(entry.phase == phase for entry in inputs.entries),
                len(solved),
                len(solved) - len(usable),
                len({entry.problem_name for entry in usable}),
                sum(entry.summary.proof_steps or 0 for entry in usable),
                sum(entry.summary.trainable_groups for entry in usable),
            ]
        )
    usable = [entry for entry in inputs.entries if entry.proved and entry.problem_name not in held_out]
    print(
        f"Every tree of phases {inputs.first_phase}-{inputs.last_phase}, whichever version sampled it; build keeps "
        f"only the samples of versions >= {inputs.completion_filter.minimum_version} except "
        f"{sorted(inputs.completion_filter.rejected_versions)}:"
    )
    headers = ["phase", "trees", "solved", "held out", "statements", "shortest-proof steps", "trainable groups"]
    print(markdown_table(headers, rows))
    print(
        f"{len(usable):,} solved trees on {len({entry.problem_name for entry in usable}):,} statements; "
        f"{sum(entry.summary.proof_steps or 0 for entry in usable):,} states on the trees' shortest proofs."
    )


@dataclass(frozen=True)
class WorkerInputs:
    model: str
    data: ExpertIterationDataConfig
    completion_filter: CompletionFilter


@dataclass(frozen=True)
class TreeTask:
    path: Path
    below_band: bool


# Set once per worker process by `start_worker`, so the filter is not pickled with every task.
worker_inputs: WorkerInputs | None = None


def start_worker(inputs: WorkerInputs) -> None:
    global worker_inputs
    worker_inputs = inputs


@functools.cache
def policy_tokenizer(model: str) -> PolicyTokenizer:
    return transformers.AutoTokenizer.from_pretrained(model)


def tree_completions(task: TreeTask) -> TreeCompletions:
    inputs = worker_inputs
    assert inputs is not None
    tokenizer = policy_tokenizer(inputs.model)
    return file_completions(task.path, tokenizer, inputs.data, inputs.completion_filter, task.below_band)


@dataclass(frozen=True)
class BuildSummary:
    name: str
    built_at: str
    git_revision: str
    loop: str
    first_phase: int
    last_phase: int
    minimum_version: int
    rejected_versions: tuple[int, ...]
    trees: int
    held_out_statements: int
    held_out_states: int
    counts: FilterCounts
    states: int
    capped_states: int
    dropped_easy_examples: int
    easy_states: int
    sampled_states: int
    data: DataSummary


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def build(config: ExpertIterationConfig, processes: int) -> None:
    inputs = loop_inputs(config)
    held_out = inputs.completion_filter.held_out_statements
    entries = [entry for entry in inputs.entries if entry.proved]
    tasks = [TreeTask(inputs.paths.trees / entry.file, entry.summary.below_band) for entry in entries]
    print(f"Labelling {len(tasks):,} solved trees of phases {inputs.first_phase}-{inputs.last_phase}", flush=True)
    started = time.monotonic()
    selector = CompletionSelector(config.data)
    worker = WorkerInputs(config.sft.model, config.data, inputs.completion_filter)
    try:
        with ProcessPoolExecutor(processes, initializer=start_worker, initargs=(worker,)) as executor:
            for index, tree in enumerate(executor.map(tree_completions, tasks, chunksize=4), start=1):
                selector.add(tree)
                if index % 250 == 0:
                    print(f"{index:,} trees, {len(selector.blocks):,} states, {time.monotonic() - started:.0f} s")
    except BrokenProcessPool as error:
        raise SystemExit(f"A build worker died ({error}), killed for memory perhaps; nothing was written.") from error
    selected = selector.selected()
    directory = OUTPUT_DIRECTORY / config.sft.data
    write_completions(directory / "train.jsonl", selected.train)
    write_completions(directory / "validation.jsonl", selected.validation)
    summary = BuildSummary(
        name=config.sft.data,
        built_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=git_revision(),
        loop=config.data.loop,
        first_phase=inputs.first_phase,
        last_phase=inputs.last_phase,
        minimum_version=inputs.completion_filter.minimum_version,
        rejected_versions=tuple(sorted(inputs.completion_filter.rejected_versions)),
        trees=len(tasks),
        held_out_statements=sum(entry.problem_name in held_out for entry in entries),
        held_out_states=selector.counts.held_out_state,
        counts=selector.counts,
        states=selected.states,
        capped_states=selected.capped_states,
        dropped_easy_examples=selected.dropped_easy_examples,
        easy_states=selected.easy_states,
        sampled_states=selected.sampled_states,
        data=data_summary(selected),
    )
    (directory / "summary.json").write_text(to_json(summary) + "\n", encoding="utf-8", newline="\n")
    markdown = build_markdown(summary)
    (directory / "README.md").write_text(markdown, encoding="utf-8", newline="\n")
    print(markdown, flush=True)


def build_markdown(summary: BuildSummary) -> str:
    data = summary.data
    counts = dataclasses.asdict(summary.counts)
    lengths = [*(str(length) for length in range(1, len(data.tactics))), f"{len(data.tactics)}+"]
    settings = [
        ["Loop, phases", f"`{summary.loop}`, {summary.first_phase}-{summary.last_phase}"],
        ["Versions", f">= {summary.minimum_version}, without {list(summary.rejected_versions)}"],
        ["Solved trees read", f"{summary.trees:,}"],
        ["Held out (should be 0)", f"{summary.held_out_statements} trees, {summary.held_out_states} samples at states"],
        [
            "Selection",
            f"{summary.states:,} states, {summary.capped_states:,} after the per-statement cap, "
            f"{summary.dropped_easy_examples:,} easy examples dropped",
        ],
        ["Easy states (pooled samples)", f"{summary.easy_states:,} of {summary.sampled_states:,} sampled states"],
        [
            "Examples",
            f"{data.train_examples:,} train, {data.validation_examples:,} validation; {data.statements:,} statements, "
            f"{data.tokens:,} tokens ({data.completion_tokens:,} completion)",
        ],
        ["Easy share", f"{data.easy_share:.1%}"],
        ["From below the band", f"{data.below_band_share:.1%}"],
        ["Ending in an end of turn", f"{data.ended_turn_share:.1%}"],
        ["Prompts unlike the replay's", f"{data.prompts_unlike_replay:,}"],
        ["Explanation characters (p10, median, p90)", ", ".join(map(str, data.explanation_characters))],
        ["Sampling versions", ", ".join(map(str, data.policy_versions))],
    ]
    sections = [
        f"# Expert-iteration data `{summary.name}`",
        markdown_table(["Setting", "Value"], settings),
        "Recorded samples at expanded proof-graph nodes by the first filter that dropped them (kept: before the caps):",
        markdown_table(["Filter", "Samples"], [[name, f"{value:,}"] for name, value in counts.items()]),
        "Examples by block length (tactics):",
        markdown_table(lengths, [data.tactics]),
        f"Built {summary.built_at}, git {summary.git_revision[:10]}.",
    ]
    return "\n\n".join(sections) + "\n"


def append_json_line(path: Path, record: object) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ValidationPoint:
    step: int
    expert_iteration_loss: float
    # None without a replay validation set.
    replay_loss: float | None


@dataclass(frozen=True)
class TrainingSummary:
    """Beside the adapter: what the run trained on and its two validation curves, to screen variants on."""

    run_name: str
    continued: ContinuedVersion
    learning_rate: float
    epochs: int
    steps: int
    expert_iteration_examples: int
    lean_replay_examples: int
    math_replay_examples: int
    # Of the training completion tokens: expert iteration, Lean replay, math replay.
    completion_token_shares: tuple[float, float, float]
    tokens: int
    training_seconds: float
    curve: tuple[ValidationPoint, ...]


def completion_token_shares(data: TrainingData) -> tuple[float, float, float]:
    parts = [data.expert_iteration, data.lean_replay, data.math_replay]
    tokens = [sum(example.completion_token_count for example in part) for part in parts]
    total = max(1, sum(tokens))
    return tokens[0] / total, tokens[1] / total, tokens[2] / total


def validation_point(record: EvaluationRecord) -> ValidationPoint:
    replay = next((item.loss for item in record.sets if item.name == REPLAY_VALIDATION), None)
    return ValidationPoint(record.step, record.validation_loss, replay)


def training_refusals(config: ExpertIterationConfig, current: ModelVersion, adapter_directory: Path) -> list[str]:
    """Before any GPU time: an existing adapter, an adapter the loop could not continue, too little disk or tmpfs."""
    refusals = []
    if adapter_directory.exists():
        refusals.append(f"{adapter_directory} exists: choose another run_name.")
    try:
        check_continued_adapter(Path(current.policy_adapter), "", config.sft.model)
    except ValueError as error:
        refusals.append(f"The current adapter would not publish after training: {error}")
    refusals += space_shortages(
        [
            SpaceRequirement(CHECKPOINTS_DIRECTORY, MIN_FREE_CHECKPOINT_GIB, "the adapter and the publish's merge"),
            SpaceRequirement(SHARED_MEMORY, MIN_FREE_SHARED_MEMORY_GIB, "NCCL"),
        ]
    )
    return refusals


def run_training(config: ExpertIterationConfig, dry_run: bool) -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    paths = loop_paths(config)
    adapter_directory = CHECKPOINTS_DIRECTORY / config.run_name / "adapter"
    current = read_current(paths.models)
    refusals = training_refusals(config, current, adapter_directory)
    # The dry run goes on beside the running loop, whose persistent trainer still fills the tmpfs.
    if refusals and not dry_run:
        raise SystemExit("\n".join(refusals))
    for refusal in refusals:
        print(f"train would refuse: {refusal}")
    sft = dataclasses.replace(config.sft, initial_adapter=current.policy_adapter)
    tokenizer = transformers.AutoTokenizer.from_pretrained(sft.model)
    data = training_data(tokenizer, OUTPUT_DIRECTORY / sft.data, config.replay, DATA_DIRECTORY)
    context = None if dry_run else distributed_context()
    world_size = len(load_loop_config(paths.config).training.gpus) if context is None else context.world_size
    steps = len(plan_steps(data.train, sft.optimization, world_size))
    shares = completion_token_shares(data)
    description = (
        f"Continuing v{current.version}'s adapter {current.policy_adapter}: {len(data.expert_iteration):,} expert-"
        f"iteration, {len(data.lean_replay):,} Lean and {len(data.math_replay):,} math replay examples "
        f"({', '.join(f'{share:.0%}' for share in shares)} of the completion tokens), "
        f"{sum(example.token_count for example in data.train):,} tokens, {steps} steps on {world_size} GPUs; "
        f"{len(data.expert_iteration_validation):,} expert-iteration and {len(data.replay_validation):,} replay "
        "validation examples"
    )
    if context is None:
        print(description)
        return
    # Three evaluations: the start, halfway and the end.
    evaluation = dataclasses.replace(
        sft.evaluation,
        interval_steps=max(1, math.ceil(steps / 2)),
        validation_examples=len(data.expert_iteration_validation),
    )
    sft = dataclasses.replace(sft, evaluation=evaluation)
    run_directory = RUNS_DIRECTORY / config.run_name
    if context.is_main:
        run_directory.mkdir(parents=True, exist_ok=True)
        for name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / name).unlink(missing_ok=True)
        print(description, flush=True)

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        point = validation_point(record)
        print(
            f"evaluation step {point.step}: expert-iteration loss {point.expert_iteration_loss:.4f}, replay loss "
            f"{point.replay_loss}",
            flush=True,
        )

    validation_sets = [ValidationSet(REPLAY_VALIDATION, data.replay_validation)] if data.replay_validation else []
    result = train(
        sft,
        tokenizer,
        data.train,
        data.expert_iteration_validation,
        context,
        adapter_directory,
        on_step,
        on_evaluation,
        validation_sets,
    )
    if not context.is_main:
        return
    continued = ContinuedVersion(current.version, current.policy_adapter)
    (adapter_directory / CONTINUED_FROM_FILE).write_text(to_json(continued) + "\n", encoding="utf-8", newline="\n")
    summary = TrainingSummary(
        run_name=config.run_name,
        continued=continued,
        learning_rate=sft.optimization.learning_rate,
        epochs=sft.optimization.epochs,
        steps=result.steps,
        expert_iteration_examples=len(data.expert_iteration),
        lean_replay_examples=len(data.lean_replay),
        math_replay_examples=len(data.math_replay),
        completion_token_shares=shares,
        tokens=result.tokens,
        training_seconds=result.training_seconds,
        curve=tuple(validation_point(record) for record in result.evaluations),
    )
    text = json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False) + "\n"
    (adapter_directory.parent / TRAINING_SUMMARY_FILE).write_text(text, encoding="utf-8", newline="\n")
    print(text, flush=True)


def held_out_run(paths: GrpoLoopPaths, version: int) -> HeldOutRun:
    summary_path = paths.evaluations / f"held_out_states_v{version:04d}" / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"{summary_path} is missing: run grpo_evaluate.py --target held_out_states first.")
    summary = from_json_object(EvaluationSummary, json.loads(summary_path.read_text(encoding="utf-8")))
    rates = held_out_rates(summary)
    assert rates is not None, summary_path
    return HeldOutRun(rates, summary.samples)


def latest_held_out_version(paths: GrpoLoopPaths, at_most: int, rejected: tuple[int, ...]) -> int:
    """The newest version up to `at_most`, not rejected, with a held-out run."""
    versions = [
        int(found[1])
        for directory in paths.evaluations.glob("held_out_states_v*")
        if (found := HELD_OUT_DIRECTORY.fullmatch(directory.name)) and (directory / "summary.json").exists()
    ]
    return max(version for version in versions if version <= at_most and version not in rejected)


def whole_set_run(runs: tuple[ProbeRun, ...], version: int) -> ProbeRun:
    found = [run for run in runs if run.policy_version == version and run.part is None]
    if not found:
        raise SystemExit(f"No finished whole-set probe run of version {version}: grpo_evaluate.py --target probe.")
    return found[-1]


def probe_tree_habits(paths: GrpoLoopPaths, run_names: tuple[str, ...]) -> SearchHabits:
    trees = [
        path for name in run_names for path in sorted(EvaluationPaths(paths.evaluations / name).trees.glob("*.json.gz"))
    ]
    return search_habits(trees, RewardConfig())


def interval_text(interval: DifferenceInterval) -> str:
    return (
        f"{100 * interval.difference:+.1f} [{100 * interval.lower:+.1f}, {100 * interval.upper:+.1f}] points on "
        f"{interval.problems} problems"
    )


def habits_rows(reference: SearchHabits, candidate: SearchHabits) -> list[list[str]]:
    def bare_have(habits: SearchHabits) -> str:
        return f"{habits.habits.bare_have_openings / max(1, habits.habits.block_samples):.1%}"

    def tactics(habits: SearchHabits) -> str:
        return f"{habits.habits.valid_block_tactics / max(1, habits.habits.valid_blocks):.2f}"

    return [
        ["Probe trees", f"{reference.trees:,}", f"{candidate.trees:,}"],
        [
            "Distinct blocks per expansion",
            f"{reference.distinct_blocks_per_expansion:.2f}",
            f"{candidate.distinct_blocks_per_expansion:.2f}",
        ],
        [
            "Median explanation characters",
            f"{median_explanation(reference):.0f}",
            f"{median_explanation(candidate):.0f}",
        ],
        ["Bare-have openings", bare_have(reference), bare_have(candidate)],
        ["Tactics per complete block", tactics(reference), tactics(candidate)],
    ]


def compare(config: ExpertIterationConfig, version: int, against: int | None) -> None:
    """Without --against the references are the loop's runs of the version the round continued and of earlier ones,
    never another round's or a rejected version's; with it, version `against`'s held-out and whole-set probe runs."""
    paths = loop_paths(config)
    health = load_loop_config(paths.config).health
    versions = {entry.version: entry for entry in read_versions(paths.models)}
    markers = read_markers(paths.directory)
    found = finished_probe_runs(paths.evaluations)
    candidate = whole_set_run(found.runs, version)
    continued = ContinuedVersion(version, versions[version].policy_adapter)
    continued_path = Path(versions[version].policy_adapter) / CONTINUED_FROM_FILE
    if continued_path.exists():
        continued = from_json_object(ContinuedVersion, json.loads(continued_path.read_text(encoding="utf-8")))
    if against is None:
        reference_version = latest_held_out_version(paths, continued.version, markers.rejected_versions)
        references = [
            run
            for run in earlier_references(found.runs, candidate, markers.rejected_versions)
            if run.policy_version <= continued.version
        ]
    else:
        reference_version = against
        references = [whole_set_run(found.runs, against)]
    paired = paired_comparison(candidate, references)
    evidence = RoundEvidence(
        version_zero=held_out_run(paths, 0),
        reference_held_out=held_out_run(paths, reference_version),
        candidate_held_out=held_out_run(paths, version),
        paired=paired,
        reference_habits=probe_tree_habits(paths, paired.reference_runs),
        candidate_habits=probe_tree_habits(paths, (candidate.name,)),
    )
    held_out = [evidence.version_zero, evidence.reference_held_out, evidence.candidate_held_out]
    held_out_row = [f"{run.rates.valid_rate:.1%} / {run.rates.success:.1%}" for run in held_out]
    headers = ["Held-out states", "version 0", f"version {reference_version}", f"version {version}"]
    print(markdown_table(headers, [["valid Lean / success", *held_out_row]]))
    probe_rows = [
        ["All problems", interval_text(paired.overall)],
        ["Neither on the wall-clock cap", interval_text(paired.without_wall_clock_stops)],
        *(
            [f"Reference version {item.policy_version}", interval_text(item.difference)]
            for item in paired.by_reference_version
        ),
        ["Wall-clock stops (candidate, references)", f"{paired.wall_clock_stops}, {paired.reference_wall_clock_stops}"],
    ]
    print(markdown_table(["Probe paired solve difference", f"version {version} minus its references"], probe_rows))
    ratings = probe_ratings(found, markers)
    rated = {rating.policy_version: rating for rating in ratings.versions}
    rating_rows = [
        [f"version {rated_version}", f"{rated[rated_version].rating:+.3f}"]
        + [f"[{rated[rated_version].lower:+.3f}, {rated[rated_version].upper:+.3f}]"]
        for rated_version in sorted({version, *([] if against is None else [against])})
    ]
    if ratings.latest_pass is not None:
        latest = ratings.latest_pass
        rating_rows.append(["latest pass", f"{latest.rating:+.3f}", f"[{latest.lower:+.3f}, {latest.upper:+.3f}]"])
    print(markdown_table(["Joint-scale rating", "rating", "95%"], rating_rows))
    habits = habits_rows(evidence.reference_habits, evidence.candidate_habits)
    print(markdown_table(["Probe trees' first round", "references", f"version {version}"], habits))
    checks = round_checks(evidence, health)
    print(markdown_table(["Check", "passed", ""], [[check.name, check.passed, check.detail] for check in checks]))
    kept = all(check.passed for check in checks)
    adapter = versions[version].policy_adapter
    match against:
        case None if kept:
            print(f"Keep version {version}: set [training] kl_reference_policy_adapter = {json.dumps(adapter)}.")
        case None:
            print(f"Roll back: grpo_loop.py rollback --version {continued.version} (the version the round continued).")
        case _ if kept:
            print(f"Version {version} beats version {against}: kl_reference_policy_adapter = {json.dumps(adapter)}.")
        case _:
            print(f"Version {against} stays ahead of version {version}: grpo_loop.py rollback --version {against}.")


def main() -> None:
    arguments = parse_arguments()
    config = parse_expert_iteration_config(arguments.config.read_text(encoding="utf-8"))
    match arguments.command:
        case "count":
            count(config)
        case "build":
            build(config, arguments.processes)
        case "train":
            run_training(config, arguments.dry_run)
        case "compare":
            compare(config, arguments.version, arguments.against)


if __name__ == "__main__":
    main()
