"""One expert-iteration round of the GRPO loop (src/lean_search/rl/README.md, "Expert iteration"): fine-tuning the
current policy adapter on the loop's own verified proof-graph blocks as sampled, with replay.

    python experiments/grpo_expert_iteration.py --config experiments/configs/grpo/expert_iteration_1.toml count
    HF_HUB_OFFLINE=1 BACKGROUND_CPUS=16 deployment/background.sh python experiments/grpo_expert_iteration.py \
        --config experiments/configs/grpo/expert_iteration_1.toml build --processes 16
    HF_HUB_OFFLINE=1 torchrun --standalone --nproc-per-node 4 experiments/grpo_expert_iteration.py \
        --config experiments/configs/grpo/expert_iteration_1.toml train
    python experiments/grpo_expert_iteration.py --config experiments/configs/grpo/expert_iteration_1.toml \
        compare --version 26

The trees are those of [data] loop's phases from the reward fix's first phase (reward_fix.json) to [data] last_phase;
only samples of the version that phase published or later count, never a rejected version's. count reads only the
tree index. build labels the solved trees in a process pool and writes $LEAN_SEARCH_DATA/grpo_expert_iteration/
<[sft] data>/{train,validation}.jsonl (one ProofGraphCompletion per line: the recorded prompt and token ids),
summary.json and README.md (counts per filter, the selection, block lengths, explanation characters, the easy share
and the share ending in an end of turn). train fine-tunes (training/sft.py) the loop's current policy adapter, read
from models/current.json, on [sft] model with the Lean and math replay at their token shares, evaluating every
quarter of the steps on the validation set plus [replay] validation_examples replay examples; the adapter goes to
$LEAN_SEARCH_CHECKPOINTS/<run_name>/adapter (refused if it exists), the steps and the summary to
$LEAN_SEARCH_RUNS/<run_name>/. Publish it with grpo_loop.py publish-adapter. compare applies the decision rule to the
published version's held-out states and whole-probe-set runs (grpo_evaluate.py) and says whether to keep it or roll
back to the version before it.
"""

import argparse
import dataclasses
import datetime
import functools
import importlib.util
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import transformers

from lean_search.data import load_minif2f
from lean_search.expert_iteration.serving import read_current
from lean_search.reasoning.dataset import read_examples as read_reasoning_examples
from lean_search.reasoning.dataset import tokenize_reasoning_example
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.evaluation import EvaluationSummary
from lean_search.rl.expert_iteration_data import (
    CompletionFilter,
    DataSummary,
    ExpertIterationConfig,
    FilterCounts,
    TreeCompletions,
    data_summary,
    examples_within_tokens,
    file_completions,
    parse_expert_iteration_config,
    read_completions,
    replay_token_budgets,
    selected_completions,
    write_completions,
)
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.health_checks import HeldOutRates, RewardFix, held_out_rates, read_rejected_versions
from lean_search.rl.loop import GrpoLoopPaths, read_progress
from lean_search.rl.loop_config import GrpoLoopConfig, load_loop_config
from lean_search.rl.policy_data import PolicyTokenizer
from lean_search.rl.probe_rating import finished_probe_runs, paired_solve_difference, probe_ratings, read_markers
from lean_search.rl.training_phase import chosen
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.search.graph_labels import goal_key
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import markdown_table
from lean_search.training.math_data import read_solutions, tokenize_math_solution
from lean_search.training.sft import (
    EvaluationRecord,
    SftRunSummary,
    StepRecord,
    distributed_context,
    plan_steps,
    train,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))
OUTPUT_DIRECTORY = DATA_DIRECTORY / "grpo_expert_iteration"
# The probe's run-to-run noise per third is about 2 points: a round is kept unless the paired difference may be worse.
MIN_PAIRED_DIFFERENCE_LOWER = -0.02


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("count")
    build = commands.add_parser("build")
    build.add_argument("--processes", type=int, default=8)
    commands.add_parser("train")
    compare = commands.add_parser("compare")
    compare.add_argument("--version", type=int, required=True, help="the published round's version")
    return parser.parse_args()


@dataclass(frozen=True)
class LoopInputs:
    paths: GrpoLoopPaths
    loop_config: GrpoLoopConfig
    first_phase: int
    last_phase: int
    completion_filter: CompletionFilter


def loop_inputs(config: ExpertIterationConfig) -> LoopInputs:
    """The loop's phases, versions and held-out sets, as its run directory records them."""
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.data.loop)
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
    return LoopInputs(paths, loop_config, first_phase, last_phase, completion_filter)


def phase_entries(inputs: LoopInputs) -> list[TreeEntry]:
    return [
        entry
        for entry in TreeStore(inputs.paths.trees).entries
        if inputs.first_phase <= entry.phase <= inputs.last_phase
    ]


def count(config: ExpertIterationConfig) -> None:
    inputs = loop_inputs(config)
    entries = phase_entries(inputs)
    held_out = inputs.completion_filter.held_out_statements
    rows = []
    for phase in range(inputs.first_phase, inputs.last_phase + 1):
        solved = [entry for entry in entries if entry.phase == phase and entry.proved]
        usable = [entry for entry in solved if entry.problem_name not in held_out]
        rows.append(
            [
                phase,
                sum(entry.phase == phase for entry in entries),
                len(solved),
                len(solved) - len(usable),
                len({entry.problem_name for entry in usable}),
                sum(entry.summary.proof_steps or 0 for entry in usable),
                sum(entry.summary.trainable_groups for entry in usable),
            ]
        )
    usable = [entry for entry in entries if entry.proved and entry.problem_name not in held_out]
    print(
        f"Phases {inputs.first_phase}-{inputs.last_phase}, samples of versions >= "
        f"{inputs.completion_filter.minimum_version} except {sorted(inputs.completion_filter.rejected_versions)}:"
    )
    headers = ["phase", "trees", "solved", "held out", "statements", "shortest-proof steps", "trainable groups"]
    print(markdown_table(headers, rows))
    print(
        f"{len(usable):,} solved trees on {len({entry.problem_name for entry in usable}):,} statements; "
        f"{sum(entry.summary.proof_steps or 0 for entry in usable):,} states on the trees' shortest proofs."
    )


@functools.cache
def policy_tokenizer(model: str) -> PolicyTokenizer:
    return transformers.AutoTokenizer.from_pretrained(model)


def tree_completions(
    path: Path, model: str, config: ExpertIterationConfig, completion_filter: CompletionFilter
) -> TreeCompletions:
    return file_completions(path, policy_tokenizer(model), config.data, completion_filter)


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
    data: DataSummary


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def build(config: ExpertIterationConfig, processes: int) -> None:
    inputs = loop_inputs(config)
    held_out = inputs.completion_filter.held_out_statements
    entries = [entry for entry in phase_entries(inputs) if entry.proved]
    paths = [inputs.paths.trees / entry.file for entry in entries]
    print(f"Labelling {len(paths):,} solved trees of phases {inputs.first_phase}-{inputs.last_phase}", flush=True)
    started = time.monotonic()
    counts = FilterCounts()
    completions = []
    work = functools.partial(
        tree_completions, model=config.sft.model, config=config, completion_filter=inputs.completion_filter
    )
    with Pool(processes) as pool:
        for index, tree in enumerate(pool.imap_unordered(work, paths, chunksize=4), start=1):
            counts += tree.counts
            completions += tree.completions
            if index % 250 == 0:
                print(f"{index:,} trees, {len(completions):,} blocks, {time.monotonic() - started:.0f} s", flush=True)
    selected = selected_completions(completions, config.data)
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
        trees=len(paths),
        held_out_statements=sum(entry.problem_name in held_out for entry in entries),
        held_out_states=counts.held_out_state,
        counts=counts,
        states=selected.states,
        capped_states=selected.capped_states,
        dropped_easy_examples=selected.dropped_easy_examples,
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
        [
            "Examples",
            f"{data.train_examples:,} train, {data.validation_examples:,} validation; {data.statements:,} statements, "
            f"{data.tokens:,} tokens ({data.completion_tokens:,} completion)",
        ],
        ["Easy share", f"{data.easy_share:.1%}"],
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


def run_training(config: ExpertIterationConfig) -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.data.loop)
    adapter_directory = CHECKPOINTS_DIRECTORY / config.run_name / "adapter"
    if adapter_directory.exists():
        raise SystemExit(f"{adapter_directory} exists: choose another run_name.")
    current = read_current(paths.models)
    sft = dataclasses.replace(config.sft, initial_adapter=current.policy_adapter)
    context = distributed_context()
    run_directory = RUNS_DIRECTORY / config.run_name
    if context.is_main:
        (run_directory / "summary").mkdir(parents=True, exist_ok=True)
        for name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / name).unlink(missing_ok=True)
    tokenizer = transformers.AutoTokenizer.from_pretrained(sft.model)
    tokenization_start = time.perf_counter()
    directory = OUTPUT_DIRECTORY / sft.data
    expert_examples = [completion.tokenized for completion in read_completions(directory / "train.jsonl")]
    replay = config.replay
    lean_tokens, math_tokens = replay_token_budgets(sum(example.token_count for example in expert_examples), replay)
    lean_examples = examples_within_tokens(
        read_reasoning_examples(DATA_DIRECTORY / replay.lean_replay),
        functools.partial(tokenize_reasoning_example, tokenizer),
        lean_tokens,
        f"{replay.seed}/lean",
    )
    math_examples = examples_within_tokens(
        read_solutions(DATA_DIRECTORY / replay.math_replay),
        functools.partial(tokenize_math_solution, tokenizer),
        math_tokens,
        f"{replay.seed}/math",
    )
    train_examples = [*expert_examples, *lean_examples, *math_examples]
    validation_examples = [completion.tokenized for completion in read_completions(directory / "validation.jsonl")]
    if replay.validation:
        replay_validation = chosen(
            read_reasoning_examples(DATA_DIRECTORY / replay.validation),
            replay.validation_examples,
            f"{replay.seed}/validation",
        )
        validation_examples += [tokenize_reasoning_example(tokenizer, example) for example in replay_validation]
    tokenization_seconds = time.perf_counter() - tokenization_start
    steps = len(plan_steps(train_examples, sft.optimization, context.world_size))
    # Every example of the validation set, every quarter of the steps.
    evaluation = dataclasses.replace(
        sft.evaluation, interval_steps=max(1, math.ceil(steps / 4)), validation_examples=len(validation_examples)
    )
    sft = dataclasses.replace(sft, evaluation=evaluation)
    if context.is_main:
        print(
            f"Continuing v{current.version}'s adapter {current.policy_adapter}: {len(expert_examples):,} expert-"
            f"iteration examples, {len(lean_examples):,} Lean and {len(math_examples):,} math replay examples, "
            f"{steps} steps; {len(validation_examples):,} validation examples",
            flush=True,
        )

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        print(f"evaluation step {record.step}: loss {record.validation_loss:.4f}", flush=True)

    result = train(
        sft, tokenizer, train_examples, validation_examples, context, adapter_directory, on_step, on_evaluation
    )
    if not context.is_main:
        return
    summary = SftRunSummary(
        run_name=config.run_name,
        started=started,
        git_revision=git_revision(),
        config=sft,
        world_size=context.world_size,
        flash_linear_attention=importlib.util.find_spec("fla") is not None,
        train_examples=len(train_examples),
        train_tokens=sum(example.token_count for example in train_examples),
        validation_examples=len(validation_examples),
        tokenization_seconds=tokenization_seconds,
        result=result,
        trained_model_directory=str(adapter_directory),
        merged_directory="",
        merge_seconds=0.0,
    )
    (run_directory / "summary" / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    losses = [[record.step, f"{record.validation_loss:.4f}"] for record in result.evaluations]
    markdown = "\n\n".join(
        [
            f"# Expert-iteration SFT `{config.run_name}`",
            f"Continues version {current.version}'s policy adapter `{current.policy_adapter}` on `{sft.model}`: "
            f"{len(expert_examples):,} expert-iteration, {len(lean_examples):,} Lean and {len(math_examples):,} math "
            f"replay examples, {result.steps} steps, {result.tokens:,} tokens in {result.training_seconds / 60:.1f} "
            f"min ({result.tokens_per_second:,.0f} tokens/s). Adapter `{adapter_directory}`.",
            markdown_table(["Step", "Validation loss"], losses),
        ]
    )
    (run_directory / "summary" / "README.md").write_text(markdown + "\n", encoding="utf-8", newline="\n")
    print(markdown, flush=True)


def held_out_of(paths: GrpoLoopPaths, version: int) -> HeldOutRates:
    summary_path = paths.evaluations / f"held_out_states_v{version:04d}" / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"{summary_path} is missing: run grpo_evaluate.py --target held_out_states first.")
    rates = held_out_rates(from_json_object(EvaluationSummary, json.loads(summary_path.read_text(encoding="utf-8"))))
    assert rates is not None, summary_path
    return rates


def compare(config: ExpertIterationConfig, version: int) -> None:
    """The decision rule: held-out valid Lean and success at least the health check's fractions of version 0's, and
    the whole probe set's paired solve difference against each problem's latest earlier run at least 0 with its lower
    95% bound above MIN_PAIRED_DIFFERENCE_LOWER."""
    paths = GrpoLoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, CHECKPOINTS_DIRECTORY, config.data.loop)
    health = load_loop_config(paths.config).health
    start, candidate = held_out_of(paths, 0), held_out_of(paths, version)
    found = finished_probe_runs(paths.evaluations)
    whole_set = next((run for run in found.runs if run.policy_version == version and run.part is None), None)
    if whole_set is None:
        raise SystemExit(f"No finished whole-set probe run of version {version}: grpo_evaluate.py --target probe.")
    markers = read_markers(paths.directory)
    paired = paired_solve_difference(found.runs, whole_set, markers.rejected_versions)
    ratings = probe_ratings(found, markers)
    rated = next(rating for rating in ratings.versions if rating.policy_version == version)
    held_out_kept = (
        candidate.valid_rate >= health.min_held_out_valid_fraction * start.valid_rate
        and candidate.success >= health.min_held_out_success_fraction * start.success
    )
    probe_kept = paired.difference >= 0 and paired.lower > MIN_PAIRED_DIFFERENCE_LOWER
    rows = [
        ["Held-out valid Lean", f"{start.valid_rate:.1%}", f"{candidate.valid_rate:.1%}"],
        ["Held-out success", f"{start.success:.1%}", f"{candidate.success:.1%}"],
        [
            "Probe paired solve difference (points)",
            "",
            f"{100 * paired.difference:+.1f} [{100 * paired.lower:+.1f}, {100 * paired.upper:+.1f}] "
            f"on {paired.problems} problems",
        ],
        ["Probe rating", "0", f"{rated.rating:+.3f} [{rated.lower:+.3f}, {rated.upper:+.3f}]"],
    ]
    if ratings.latest_pass is not None:
        latest = ratings.latest_pass
        rows.append(["Latest pass rating", "", f"{latest.rating:+.3f} [{latest.lower:+.3f}, {latest.upper:+.3f}]"])
    print(markdown_table(["", "version 0", f"version {version}"], rows))
    if held_out_kept and probe_kept:
        print(f"Keep version {version}; set [training] kl_reference_policy_adapter, then start the loop.")
    else:
        print(
            f"Roll back: grpo_loop.py rollback --version {version - 1} (held out ok: {held_out_kept}, probe ok: "
            f"{probe_kept})."
        )


def main() -> None:
    arguments = parse_arguments()
    config = parse_expert_iteration_config(arguments.config.read_text(encoding="utf-8"))
    match arguments.command:
        case "count":
            count(config)
        case "build":
            build(config, arguments.processes)
        case "train":
            run_training(config)
        case "compare":
            compare(config, arguments.version)


if __name__ == "__main__":
    main()
