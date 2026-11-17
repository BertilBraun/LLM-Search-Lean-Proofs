"""The offline arm (O; src/lean_search/rl/offline_arm.py, offline_walk.py, offline_report.py): v0's adapter continued by
SFT on the pool's known proofs without visible reasoning, two training sets (pool: every usable proof, O1; matched:
a stratified subsample of about an expert-iteration arm's completion tokens, O2), each at two learning rates.

    HF_HUB_DISABLE_XET=1 python experiments/offline_arm.py --config $CONFIG download
    python experiments/offline_arm.py --config $CONFIG prepare [--processes 32]
    HF_HUB_OFFLINE=1 deployment/background.sh python experiments/offline_arm.py --config $CONFIG walk
    HF_HUB_OFFLINE=1 python experiments/offline_arm.py --config $CONFIG build
    HF_HUB_OFFLINE=1 python experiments/offline_arm.py --config $CONFIG train --subset matched --learning-rate 5e-5 \
        --dry-run
    HF_HUB_OFFLINE=1 torchrun --standalone --nproc-per-node 4 experiments/offline_arm.py --config $CONFIG train \
        --subset matched --learning-rate 5e-5
    python experiments/offline_arm.py --config $CONFIG held-out-config --output <loop.toml>
    deployment/background.sh python experiments/offline_arm.py --config $CONFIG flat-references --output <file>
    python experiments/offline_arm.py --config $CONFIG rank --subset matched --v0 offline_v0_no_reasoning \
        --flat-references <file>
    python experiments/offline_arm.py --config $CONFIG chosen-rate --subset matched --rank rank_matched.txt
    python experiments/offline_arm.py --config $CONFIG probe-list --subset matched --rate 5e-5 \
        --output runs_matched.toml [--name N --evaluation-config C]
    python experiments/offline_arm.py --config $CONFIG report --subset matched [--probe-name N]
CONFIG = experiments/configs/grpo/followup/offline/offline_arm.toml

download fetches the two public proof corpora the pool's proofs came from (Goedel-LM/SFT_dataset_v2, Leanabell SFT) at
phase 2's pinned revisions into $LEAN_SEARCH_DATA/<name>/raw (no token). prepare drops the pool statements the
evaluations hold out and their near-duplicates (formal statement and root state, every pair), normalizes the corpora as
phase 2 did and recovers each kept statement's verified proof (its candidates: the proofs of the recorded source,
tactic count and characters), into proofs.jsonl and preparation.json (counts per reason). walk (Lean CPUs only, through
background.sh; resumable) walks each proof as the search runs policy blocks into walks.jsonl, the candidates in order
until one walks to the end, and records what decided the walks in walk.json (refusing walks.jsonl made otherwise; it
exits non-zero while more than 1% of all proofs' walks raised). build (refusing walks of another walk.json) tokenizes
the walked blocks in v0's no-reasoning SFT format (render_prompt(goals) with the fence prefill; the block, the fence,
end of turn), the prefix of a walk that failed at a block included, drops states near a held-out state, splits off the
validation statements, draws the matched subset, and writes <subset>/train.jsonl, validation.jsonl, build.json and
README.md. train continues v0's adapter on a subset (pool: [sft.optimization] epochs; matched: [matched] epochs) with
the Lean and math replay at their completion-token shares, into $LEAN_SEARCH_CHECKPOINTS/<name>_<subset>_<rate>/adapter
and training_summary.json beside it (refused if the adapter exists), logging the first steps' throughput and peak GPU
memory (throughput.json in its run directory); --dry-run assembles the data, prints its size, steps and peak host
memory, and exits 3 when the ranks' tokenized data would not fit the host's memory. held-out-config writes the follow-up
base in the no-reasoning sampling mode, the loop config of the held-out runs. flat-references runs each held-out
state's reference next step flattened and keeps the states inside it. rank compares the subset's held-out runs with v0's
on the standard success and on the flattened one (a block may also end inside the reference next step's nested proof)
and chooses the rate on the flattened one, the lower rate on a tie. chosen-rate prints the rate a ranking chose.
probe-list writes the subset's probe run list at a rate. report writes the gate report of the subset's probe run against
run 8 at equal expansions, the anchors' A/A difference beside it, and descriptively against run 4 and the anchors within
16 expansions; every run must have searched all 2,000 statements of one probe set.
"""

import argparse
import asyncio
import dataclasses
import datetime
import functools
import json
import math
import os
import random
import resource
import time
import tomllib
from collections import Counter
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import torch
import transformers
from huggingface_hub import snapshot_download

import lean_search
from lean_search.corpora.download import HUGGING_FACE_DATASETS
from lean_search.corpora.lean_text import split_top_level_tactics
from lean_search.corpora.normalize import Rejection, normalize_proof
from lean_search.corpora.pipeline import statement_key
from lean_search.corpora.sources import PROOF_SOURCES, ProofShard
from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.expert_iteration.known_proofs import VerifiedStatement, read_verified
from lean_search.expert_iteration.pool import pool_problem
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.monitoring.cgroup import memory_limit_bytes
from lean_search.policy.prompts import FENCE
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.arm_comparison import Arm, read_arm_run
from lean_search.rl.expert_iteration_data import ValidationPoint, replay_data, replay_loss_change
from lean_search.rl.fixed_sets import hash_order, read_fixed_set
from lean_search.rl.learning_rate_step import chosen_label
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.offline_arm import (
    MAX_HOST_MEMORY_SHARE,
    BandSize,
    BandWalks,
    CorpusProof,
    ExampleCounts,
    ExampleTokens,
    OfflineArmConfig,
    PoolProof,
    ProofExamples,
    ProofTarget,
    Subset,
    WalkFingerprint,
    band_sizes,
    band_walks,
    fingerprint_differences,
    held_out_references,
    load_offline_arm_config,
    matched_sample,
    pool_selection,
    ranks_fit,
    read_pool_proofs,
    recovered_candidates,
    run_label,
    run_name,
    split_examples,
    steady_tokens_per_second,
    subset_epochs,
    usable_blocks,
    walk_fingerprint,
    walk_settings_text,
)
from lean_search.rl.offline_held_out import (
    FlatReference,
    HeldOutMeasures,
    flat_reference,
    held_out_measures,
    read_flat_references,
)
from lean_search.rl.offline_report import PairedDifference, gate_report, paired_difference
from lean_search.rl.offline_walk import ProofWalk, WalkedProof, WalkSettings, WalkStatus, walk_candidates
from lean_search.rl.probe_rating import DifferenceInterval
from lean_search.rl.rate_ranking import HeldOutRunStart, Variant, against_v0, choose_rate
from lean_search.rl.single_step import StateProblem, state_problem
from lean_search.rl.study_configs import with_sampling_mode
from lean_search.rl.training_overlap import exhaustive_duplicates, fingerprints
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import markdown_table
from lean_search.training.sft import EvaluationRecord, StepRecord, ValidationSet, distributed_context, plan_steps, train
from lean_search.training.sft_data import SftExample, TokenizedExample, tokenize_example

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_DATA", "/workspace/data"))
RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
CHECKPOINTS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_CHECKPOINTS", "/workspace/checkpoints"))
FOLLOWUP = "experiments/configs/grpo/followup"
BASE_LOOP_CONFIG = f"{FOLLOWUP}/base.toml"
PROBE_EVALUATION = f"{FOLLOWUP}/offline/probe_evaluation.toml"
PROBE_SEARCH = f"{FOLLOWUP}/offline/search_no_reasoning_16.toml"
PROBE_SET = "grpo/fixed_sets/probe_v2.jsonl"
GATE_RUN = "step1_run8_v35_value_v0"
NO_REASONING_RUN = "step1_run4_no_reasoning_T"
ANCHOR_RUNS = ("step1_run1_v0_value_v0", "step1_run2_v0_value_v0")
EQUAL_EXPANSIONS = 16
PROBE_STATEMENTS = 2000
TRAINING_SUMMARY_FILE = "training_summary.json"
REPLAY_VALIDATION = "replay"
WALK_RECORD = "walk.json"
LOG_EVERY = 500
# More walks than this share of all proofs raised: the walk exits non-zero, and the next start walks them again.
MAX_ERROR_SHARE = 0.01
MAX_FAILURE_CHARACTERS = 300
# Steps logged one by one at a training's start, and the steps left out of its steady throughput (compilation,
# autotuning).
LOGGED_FIRST_STEPS = 20
WARMUP_STEPS = 10
# The exit status of a dry run whose ranks' data would not fit the host's memory.
MEMORY_EXIT_STATUS = 3
# For scale in the build summary: an expert-iteration arm trains about 800 examples (0.13M completion tokens, with
# visible reasoning) per phase, about 13k examples and 2M completion tokens over 16 phases.
EXPERT_ITERATION_ARM_EXAMPLES = 13_000


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--processes", type=int, default=32)
    commands.add_parser("walk")
    commands.add_parser("build")
    training = commands.add_parser("train")
    training.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    training.add_argument("--learning-rate", required=True)
    training.add_argument("--dry-run", action="store_true")
    training.add_argument("--gpus", type=int, default=4, help="the dry run's world size")
    held_out = commands.add_parser("held-out-config")
    held_out.add_argument("--mode", type=Path, default=Path(f"{FOLLOWUP}/modes/no_reasoning.toml"))
    held_out.add_argument("--output", type=Path, required=True)
    flat = commands.add_parser("flat-references")
    flat.add_argument("--output", type=Path, required=True)
    flat.add_argument("--processes", type=int, default=16)
    rank = commands.add_parser("rank")
    rank.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    rank.add_argument("--v0", required=True, help="v0's held-out run (held_out_evaluations/held_out_<name>)")
    rank.add_argument("--flat-references", type=Path, required=True)
    rank.add_argument("--seed", type=int, default=0, help="the bootstraps'")
    chosen = commands.add_parser("chosen-rate")
    chosen.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    chosen.add_argument("--rank", type=Path, required=True, help="rank's output")
    probe_list = commands.add_parser("probe-list")
    probe_list.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    probe_list.add_argument("--rate", required=True)
    probe_list.add_argument("--output", type=Path, required=True)
    probe_list.add_argument("--name", default="", help="the probe run's name; default <name>_<subset>")
    probe_list.add_argument("--evaluation-config", default=PROBE_EVALUATION, help="e.g. one at a doubled wall cap")
    report = commands.add_parser("report")
    report.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    report.add_argument("--probe-name", default="", help="the probe run's name; default <name>_<subset>")
    report.add_argument("--seed", type=int, default=0, help="the bootstrap's")
    return parser.parse_args()


def log(message: str) -> None:
    print(f"{datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')} {message}", flush=True)


def arm_directory(config: OfflineArmConfig) -> Path:
    return DATA_DIRECTORY / config.name


def write_text(path: Path, text: str) -> None:
    """Whole or not at all: a kill mid-write leaves the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


# download


def download(config: OfflineArmConfig) -> None:
    raw = arm_directory(config) / "raw"
    wanted = {"goedel_sft_v2", "leanabell_sft"}
    for dataset in HUGGING_FACE_DATASETS:
        if dataset.name in wanted:
            log(f"Downloading {dataset.repository} at {dataset.revision}")
            snapshot_download(
                repo_id=dataset.repository,
                repo_type="dataset",
                revision=dataset.revision,
                local_dir=raw / dataset.name,
                token=False,
            )


# prepare


@dataclass(frozen=True)
class ShardTask:
    source: str
    shard_number: int
    path: Path


@dataclass(frozen=True)
class ShardProofs:
    rows: int
    rejected: int
    proofs: tuple[CorpusProof, ...]


# Set once per worker process by `start_worker`, so the keys are not pickled with every task.
worker_keys: frozenset[str] = frozenset()


def start_worker(keys: frozenset[str]) -> None:
    global worker_keys
    worker_keys = keys


def shard_proofs(task: ShardTask) -> ShardProofs:
    """The shard's normalized proofs of target statements, the first row of each statement and proof text (phase 2's
    within-shard duplicates)."""
    source = next(source for source in PROOF_SOURCES if source.name == task.source)
    seen: set[tuple[str, str]] = set()
    proofs: list[CorpusProof] = []
    rows = rejected = 0
    for row_number, raw in enumerate(source.read(ProofShard(task.source, task.path))):
        rows += 1
        identifier = f"{task.source}/{task.shard_number}/{row_number}"
        record = normalize_proof(raw, identifier, source.lean_version_hint, source.statement_identifiers_unique)
        if isinstance(record, Rejection):
            rejected += 1
            continue
        key = statement_key(record.formal_statement)
        if key not in worker_keys:
            continue
        proof = CorpusProof(
            key, task.source, identifier, record.tactic_proof, len(split_top_level_tactics(record.tactic_proof))
        )
        if (key, proof.proof_key) not in seen:
            seen.add((key, proof.proof_key))
            proofs.append(proof)
    return ShardProofs(rows, rejected, tuple(proofs))


@dataclass(frozen=True)
class SourceRows:
    source: str
    shards: int
    rows: int
    rejected: int
    target_proofs: int


@dataclass(frozen=True)
class Preparation:
    prepared_at: str
    pool: str
    pool_records: int
    # Per exclusion, the statements dropped for it (rl/offline_arm.Exclusion).
    dropped: dict[str, int]
    selected: int
    sources: tuple[SourceRows, ...]
    recovered: int
    # Statements with more than one candidate proof (the walk takes the first that walks to the end).
    ambiguous: int
    not_recovered: int
    not_recovered_examples: tuple[str, ...]


def prepare(config: OfflineArmConfig, processes: int) -> None:
    data = config.data
    pool_path = DATA_DIRECTORY / data.pool
    if file_sha256(pool_path) != data.pool_sha256:
        raise SystemExit(f"{pool_path} is not the frozen pool ({data.pool_sha256[:12]}).")
    pool, _ = read_verified(pool_path)
    held_out = [entry.statement for path in data.held_out_sets for entry in read_fixed_set(DATA_DIRECTORY / path)]
    states = read_records(RUNS_DIRECTORY / data.held_out_states_file, ReasoningState)
    references = held_out_references(held_out, [state.step.formal_statement for state in states], pool)
    selection = pool_selection(pool, references, data.near_duplicate_threshold)
    log(f"{len(selection.kept):,} of {len(pool):,} pool statements kept: {selection.dropped}")
    targets: dict[str, ProofTarget] = {}
    by_key: dict[str, VerifiedStatement] = {}
    for record in selection.kept:
        key = statement_key(record.statement.formal_statement)
        assert key not in targets, f"two pool statements share the key {key}"
        assert record.proof_source is not None
        targets[key] = ProofTarget(record.proof_source, record.proof_tactics, record.proof_characters)
        by_key[key] = record
    raw = arm_directory(config) / "raw"
    tasks = [
        ShardTask(source.name, number, shard.path)
        for source in PROOF_SOURCES
        if source.name in {target.source for target in targets.values()}
        for number, shard in enumerate(source.shards(raw))
    ]
    if not tasks:
        raise SystemExit(f"No corpus shard under {raw}: run download first.")
    proofs: list[CorpusProof] = []
    counts: dict[str, Counter[str]] = {}
    with Pool(processes, initializer=start_worker, initargs=(frozenset(targets),)) as workers:
        for task, found in zip(tasks, workers.imap(shard_proofs, tasks), strict=True):
            counter = counts.setdefault(task.source, Counter())
            counter.update(shards=1, rows=found.rows, rejected=found.rejected, target_proofs=len(found.proofs))
            proofs.extend(found.proofs)
            log(f"{task.source} shard {task.shard_number}: {found.rows:,} rows, {len(found.proofs):,} target proofs")
    candidates = recovered_candidates(targets, proofs)
    missing = sorted(by_key[key].name for key in targets if key not in candidates)
    ordered = sorted(candidates, key=lambda key: hash_order(by_key[key].name, config.walk.seed))
    lines = []
    for key in ordered:
        record = by_key[key]
        entry = PoolProof(record.name, record.statement, record.proof_characters, record.proof_tactics, candidates[key])
        lines.append(to_json(entry) + "\n")
    write_text(arm_directory(config) / "proofs.jsonl", "".join(lines))
    preparation = Preparation(
        prepared_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        pool=data.pool,
        pool_records=len(pool),
        dropped=selection.dropped,
        selected=len(selection.kept),
        sources=tuple(
            SourceRows(source, counter["shards"], counter["rows"], counter["rejected"], counter["target_proofs"])
            for source, counter in sorted(counts.items())
        ),
        recovered=len(candidates),
        ambiguous=sum(len(found) > 1 for found in candidates.values()),
        not_recovered=len(missing),
        not_recovered_examples=tuple(missing[:20]),
    )
    write_text(arm_directory(config) / "preparation.json", to_json(preparation) + "\n")
    log(
        f"{preparation.recovered:,} proofs recovered ({preparation.ambiguous:,} with several candidates), "
        f"{preparation.not_recovered:,} not recovered"
    )


# walk


def walk_settings(config: OfflineArmConfig) -> WalkSettings:
    search = load_run_config(REPOSITORY_DIRECTORY / config.walk.search_config).search
    return WalkSettings(
        heartbeats=search.tactic_heartbeats,
        timeout_seconds=search.tactic_timeout_seconds,
        flatten=search.flatten_blocks,
        name_hypotheses=search.name_inaccessible_hypotheses,
        check_identifiers=search.check_identifiers,
        environment_names_directory=search.environment_names_directory,
        forbidden_steps=tuple(search.forbidden_steps),
        # The expander's: a sample's block naming one of them is unusable.
        forbidden_tokens=FORBIDDEN_TOKENS | frozenset(search.forbidden_steps),
        max_block_tactics=config.walk.max_block_tactics,
    )


def completion_fits(tokenizer: transformers.PreTrainedTokenizerBase, max_tokens: int, block: str) -> bool:
    """What the policy generates for the block (the stop sequence, the closing fence, included) within its cap."""
    return len(tokenizer.encode(f"{block}\n{FENCE}", add_special_tokens=False)) <= max_tokens


def latest_walks(walks: list[WalkedProof]) -> dict[str, WalkedProof]:
    """Each proof's last walk (a walk that raised is walked again by a later start)."""
    return {walked.name: walked for walked in walks}


def read_walks(path: Path) -> list[WalkedProof]:
    """The complete lines; a line cut by a kill is dropped from the file, so the next append starts clean."""
    if not path.exists():
        return []
    data = path.read_bytes()
    complete = data[: data.rfind(b"\n") + 1]
    if len(complete) < len(data):
        path.write_bytes(complete)
    return [from_json_object(WalkedProof, json.loads(line)) for line in complete.decode("utf-8").splitlines() if line]


def current_walk_fingerprint(config: OfflineArmConfig) -> WalkFingerprint:
    policy = load_run_config(REPOSITORY_DIRECTORY / config.walk.search_config).policy
    settings = walk_settings_text(walk_settings(config), config.walk, policy.tokenizer, policy.max_tokens)
    proofs_sha256 = file_sha256(arm_directory(config) / "proofs.jsonl")
    return walk_fingerprint(Path(lean_search.__file__).resolve().parent, settings, proofs_sha256)


def check_walk_record(config: OfflineArmConfig, record_missing: bool) -> None:
    """walk.json against what decides a walk now; a missing one is written with `record_missing`, else refused."""
    path = arm_directory(config) / WALK_RECORD
    current = current_walk_fingerprint(config)
    if not path.exists():
        if not record_missing:
            raise SystemExit(f"No {path}: the walks' code and settings are unknown; run walk first.")
        write_text(path, to_json(current) + "\n")
        return
    differences = fingerprint_differences(from_json_object(WalkFingerprint, json.loads(path.read_text())), current)
    if differences:
        raise SystemExit(
            f"walks.jsonl was walked with another {', '.join(differences)} ({path}): move walks.jsonl and "
            f"{WALK_RECORD} aside and walk again."
        )


async def walk(config: OfflineArmConfig) -> None:
    directory = arm_directory(config)
    proofs = read_pool_proofs(directory / "proofs.jsonl")
    output = directory / "walks.jsonl"
    check_walk_record(config, record_missing=True)
    # A walk that raised is walked again.
    done = {
        walked.name for walked in latest_walks(read_walks(output)).values() if walked.walk.status != WalkStatus.ERROR
    }
    remaining = [proof for proof in proofs if proof.name not in done]
    log(f"{len(done):,} of {len(proofs):,} proofs walked; walking {len(remaining):,}")
    if remaining:
        await walk_proofs(config, remaining, output)
    raised = sum(walked.walk.status == WalkStatus.ERROR for walked in latest_walks(read_walks(output)).values())
    if raised > MAX_ERROR_SHARE * len(proofs):
        raise SystemExit(f"{raised:,} of {len(proofs):,} walks raised: they are walked again by the next start.")


async def walk_proofs(config: OfflineArmConfig, remaining: list[PoolProof], output: Path) -> None:
    run_config = load_run_config(REPOSITORY_DIRECTORY / config.walk.search_config)
    settings = walk_settings(config)
    tokenizer = transformers.AutoTokenizer.from_pretrained(run_config.policy.tokenizer)
    fits = functools.partial(completion_fits, tokenizer, run_config.policy.max_tokens)
    queue: asyncio.Queue[PoolProof] = asyncio.Queue()
    for proof in remaining:
        queue.put_nowait(proof)
    statuses: Counter[str] = Counter()
    started = time.monotonic()
    header = Counter(proof.statement.header for proof in remaining).most_common(1)[0][0]
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        async with LeanReplPool(config.walk.processes, LeanReplConfig(), run_config.lean.restart_fraction) as pool:
            await pool.start([header])

            async def work() -> None:
                while not queue.empty():
                    proof = queue.get_nowait()
                    problem = pool_problem(proof.statement)
                    begun = time.monotonic()
                    try:
                        async with pool.acquire() as repl:
                            walked = await walk_candidates(
                                repl, problem, proof.candidates, settings, config.walk.seed, fits, time.monotonic
                            )
                    except Exception as error:
                        failure = ProofWalk(WalkStatus.ERROR, (), 0, repr(error)[:MAX_FAILURE_CHARACTERS], None)
                        walked = WalkedProof(proof.name, None, (WalkStatus.ERROR,), failure, time.monotonic() - begun)
                    handle.write(to_json(walked) + "\n")
                    handle.flush()
                    statuses[walked.walk.status] += 1
                    total = sum(statuses.values())
                    if total % LOG_EVERY == 0:
                        rate = total / (time.monotonic() - started)
                        log(f"{total:,} of {len(remaining):,} walked ({rate:.2f}/s): {dict(statuses)}")

            await asyncio.gather(*(work() for _ in range(config.walk.processes)))
    log(f"Walked {len(remaining):,} proofs: {dict(statuses)}")


# build


@dataclass(frozen=True)
class SubsetSize:
    subset: str
    proofs: int
    examples: int
    prompt_tokens: int
    completion_tokens: int
    bands: tuple[BandSize, ...]


@dataclass(frozen=True)
class BuildSummary:
    built_at: str
    proofs: int
    # Per walk status (rl/offline_walk.WalkStatus), the proofs, in all and per band of proof characters.
    walks: dict[str, int]
    band_walks: tuple[BandWalks, ...]
    # Complete walks by the candidate that walked (1 is the first).
    candidates: dict[str, int]
    skipped_blocks: int
    examples: ExampleCounts
    # Kept training examples by the block's tactics.
    block_tactics: dict[str, int]
    validation: SubsetSize
    subsets: tuple[SubsetSize, ...]


def subset_size(name: str, proofs: list[ProofExamples], edges: tuple[int, ...]) -> SubsetSize:
    return SubsetSize(
        name,
        len(proofs),
        sum(len(proof.examples) for proof in proofs),
        sum(proof.prompt_tokens for proof in proofs),
        sum(proof.completion_tokens for proof in proofs),
        band_sizes(proofs, edges),
    )


def write_examples(path: Path, proofs: list[ProofExamples]) -> None:
    write_text(
        path,
        "".join(
            json.dumps(dataclasses.asdict(example), ensure_ascii=False) + "\n"
            for proof in proofs
            for example in proof.examples
        ),
    )


def read_examples(path: Path) -> list[SftExample]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(SftExample, json.loads(line)) for line in lines if line.strip()]


def held_out_state_goals() -> list[tuple[str, ...]]:
    loop = load_loop_config(REPOSITORY_DIRECTORY / BASE_LOOP_CONFIG)
    return [
        state.goals for state in read_records(RUNS_DIRECTORY / loop.evaluation.held_out_states_file, ReasoningState)
    ]


def near_held_out_states(walks: list[WalkedProof], threshold: float) -> frozenset[tuple[str, ...]]:
    """The walks' states whose fingerprint reaches the threshold with a held-out state's (every pair)."""
    states = sorted({block.goals for walked in walks for block in usable_blocks(walked)})
    hits = exhaustive_duplicates(fingerprints(states), fingerprints(held_out_state_goals()), threshold)
    return frozenset(state for state, hit in zip(states, hits, strict=True) if hit)


def build(config: OfflineArmConfig) -> None:
    directory = arm_directory(config)
    check_walk_record(config, record_missing=False)
    proofs = {proof.name: proof for proof in read_pool_proofs(directory / "proofs.jsonl")}
    walks = list(latest_walks(read_walks(directory / "walks.jsonl")).values())
    if {walked.name for walked in walks} != set(proofs):
        raise SystemExit(f"walks.jsonl covers {len(walks):,} of the {len(proofs):,} proofs: walk first.")
    run_config = load_run_config(REPOSITORY_DIRECTORY / config.walk.search_config)
    tokenizer = transformers.AutoTokenizer.from_pretrained(run_config.policy.tokenizer)

    def tokenize(example: SftExample) -> ExampleTokens:
        tokenized = tokenize_example(tokenizer, example)
        return ExampleTokens(tokenized.prompt_token_count, tokenized.completion_token_count)

    characters = {name: proof.proof_characters for name, proof in proofs.items()}
    near = near_held_out_states(walks, config.data.near_duplicate_threshold)
    max_depth = load_run_config(REPOSITORY_DIRECTORY / PROBE_SEARCH).search.max_depth
    split = split_examples(walks, characters, tokenize, near, config, max_depth)
    train = list(split.train)
    matched = matched_sample(train, config.matched)
    edges = config.matched.band_edges
    write_examples(directory / "validation.jsonl", list(split.validation))
    write_examples(directory / Subset.POOL / "train.jsonl", train)
    write_examples(directory / Subset.MATCHED / "train.jsonl", matched)
    summary = BuildSummary(
        built_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        proofs=len(proofs),
        walks=dict(Counter(str(walked.walk.status) for walked in walks)),
        band_walks=band_walks(walks, characters, edges),
        candidates=dict(
            sorted(Counter(str(walked.candidate + 1) for walked in walks if walked.candidate is not None).items())
        ),
        skipped_blocks=sum(walked.walk.skipped_blocks for walked in walks),
        examples=split.counts,
        block_tactics={str(length): count for length, count in split.block_tactics.items()},
        validation=subset_size("validation", list(split.validation), edges),
        subsets=(subset_size(Subset.POOL, train, edges), subset_size(Subset.MATCHED, matched, edges)),
    )
    write_text(directory / "build.json", to_json(summary) + "\n")
    markdown = build_markdown(config, summary)
    write_text(directory / "README.md", markdown)
    print(markdown, flush=True)


def size_row(label: str, size: SubsetSize | BandSize) -> list[object]:
    return [label, f"{size.proofs:,}", f"{size.examples:,}", f"{size.prompt_tokens:,}", f"{size.completion_tokens:,}"]


def band_row(size: BandSize) -> list[object]:
    return [*size_row(size.band, size), f"{size.prefix_proofs:,}"]


def build_markdown(config: OfflineArmConfig, summary: BuildSummary) -> str:
    headers = ["Proofs, examples, tokens", "Proofs", "Examples", "Prompt tokens", "Completion tokens"]
    statuses = sorted(summary.walks)
    counts = summary.examples
    matched = next(size for size in summary.subsets if size.subset == Subset.MATCHED)
    sections = [
        f"# Offline arm data `{config.name}`",
        f"Walks of {summary.proofs:,} recovered pool proofs, by status, in all and per band of proof characters:",
        markdown_table(
            ["Band", *statuses],
            [
                *(
                    [band.band, *(f"{band.statuses.get(status, 0):,}" for status in statuses)]
                    for band in summary.band_walks
                ),
                ["all", *(f"{summary.walks[status]:,}" for status in statuses)],
            ],
        ),
        f"Complete walks by the candidate proof that walked: {summary.candidates}. Blocks run without an example (one "
        f"step over the completion cap): {summary.skipped_blocks:,}. Examples kept from the valid prefix of "
        f"{counts.prefix_proofs:,} walks that failed at a block or a forbidden step: {counts.prefix_examples:,}. "
        f"Examples dropped: a repeated (state, block) pair {counts.duplicates:,}, a prompt over "
        f"{config.walk.max_prompt_tokens:,} tokens {counts.over_prompt_cap:,}, a state near one of the held-out states "
        f"{counts.near_held_out_state:,}. Kept examples deeper than the probe search's depth cap: "
        f"{counts.beyond_search_depth:,}. Training examples by the block's tactics: {summary.block_tactics}.",
        markdown_table(headers, [size_row(size.subset, size) for size in (*summary.subsets, summary.validation)]),
        f"For scale: the matched subset's {matched.examples:,} examples (about "
        f"{matched.completion_tokens / max(1, matched.examples):.0f} completion tokens each) against about "
        f"{EXPERT_ITERATION_ARM_EXAMPLES:,} for an expert-iteration arm's 2M completion tokens over 16 phases, whose "
        "examples carry visible reasoning (about 190 completion tokens each).",
    ]
    for size in summary.subsets:
        sections += [
            f"By proof characters, `{size.subset}`:",
            markdown_table(
                ["Band", *headers[1:], "Of them failed walks' prefixes"], [band_row(band) for band in size.bands]
            ),
        ]
    sections.append(f"Built {summary.built_at}.")
    return "\n\n".join(sections) + "\n"


# train


@dataclass(frozen=True)
class OfflineTrainingSummary:
    run_name: str
    initial_adapter: str
    subset: str
    learning_rate: float
    epochs: int
    steps: int
    offline_examples: int
    lean_replay_examples: int
    math_replay_examples: int
    validation_examples: int
    # Of the training completion tokens: the arm's, the Lean replay's, the math replay's.
    completion_token_shares: tuple[float, float, float]
    prompt_tokens: int
    completion_tokens: int
    training_seconds: float
    # Over the steps after the first WARMUP_STEPS (compilation and autotuning left out); the main rank's peak.
    steady_tokens_per_second: float | None
    peak_memory_gib: float
    curve: tuple[ValidationPoint, ...]
    replay_loss_change: float | None


@dataclass(frozen=True)
class Throughput:
    """A training's first steps, written once LOGGED_FIRST_STEPS are done."""

    run_name: str
    warmup_seconds: float
    steady_tokens_per_second: float | None
    peak_memory_gib: float


def append_json_line(path: Path, record: object) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def completion_tokens(examples: list[TokenizedExample]) -> int:
    return sum(example.completion_token_count for example in examples)


def validation_point(record: EvaluationRecord) -> ValidationPoint:
    replay = next((item.loss for item in record.sets if item.name == REPLAY_VALIDATION), None)
    return ValidationPoint(record.step, record.validation_loss, replay)


def run_training(config: OfflineArmConfig, subset: Subset, rate: str, dry_run: bool, dry_run_gpus: int) -> None:
    if rate not in config.learning_rates:
        raise SystemExit(f"{rate} is not one of the config's learning rates {list(config.learning_rates)}.")
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    name = run_name(config, subset, rate)
    adapter_directory = CHECKPOINTS_DIRECTORY / name / "adapter"
    if adapter_directory.exists() and not dry_run:
        raise SystemExit(f"{adapter_directory} exists: move it aside first.")
    directory = arm_directory(config)
    optimization = dataclasses.replace(
        config.sft.optimization, learning_rate=float(rate), epochs=subset_epochs(config, subset)
    )
    sft = dataclasses.replace(
        config.sft,
        data=str(directory / subset),
        initial_adapter=config.initial_policy_adapter,
        optimization=optimization,
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(sft.model)
    offline = [tokenize_example(tokenizer, example) for example in read_examples(directory / subset / "train.jsonl")]
    validation_all = read_examples(directory / "validation.jsonl")
    count = min(sft.evaluation.validation_examples, len(validation_all))
    chosen = random.Random(f"{config.data.seed}/validation").sample(validation_all, count)
    validation = [tokenize_example(tokenizer, example) for example in chosen]
    replay = replay_data(tokenizer, completion_tokens(offline), config.replay, DATA_DIRECTORY)
    examples = [*offline, *replay.lean, *replay.math]
    parts = [completion_tokens(offline), completion_tokens(list(replay.lean)), completion_tokens(list(replay.math))]
    shares = tuple(part / max(1, sum(parts)) for part in parts)
    context = None if dry_run else distributed_context()
    world_size = dry_run_gpus if context is None else context.world_size
    steps = len(plan_steps(examples, optimization, world_size))
    prompt_tokens = sum(example.prompt_token_count for example in examples)
    description = (
        f"{name}: continuing {config.initial_policy_adapter} at {rate}, {optimization.epochs} epochs: "
        f"{len(offline):,} offline, {len(replay.lean):,} Lean and {len(replay.math):,} math replay examples "
        f"({', '.join(f'{share:.0%}' for share in shares)} of the completion tokens); {prompt_tokens:,} prompt and "
        f"{sum(parts):,} completion tokens ({prompt_tokens + sum(parts):,} in all; offline alone "
        f"{sum(example.prompt_token_count for example in offline):,} prompt, {parts[0]:,} completion); {steps} steps "
        f"on {world_size} GPUs; {len(validation):,} offline and {len(replay.validation):,} replay validation examples"
    )
    if context is None:
        peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        limit_bytes = memory_limit_bytes() or os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        fits = ranks_fit(peak_bytes, world_size, limit_bytes)
        print(
            f"{description}; peak host memory {peak_bytes / 2**30:.1f} GiB, {world_size} ranks about "
            f"{world_size * peak_bytes / 2**30:.0f} GiB of the host's {limit_bytes / 2**30:.0f} GiB"
            + ("" if fits else f": WOULD NOT FIT (over {MAX_HOST_MEMORY_SHARE:.0%})")
        )
        if not fits:
            raise SystemExit(MEMORY_EXIT_STATUS)
        return
    evaluation = dataclasses.replace(
        sft.evaluation, interval_steps=max(1, math.ceil(steps / 2)), validation_examples=len(validation)
    )
    sft = dataclasses.replace(sft, evaluation=evaluation)
    run_directory = RUNS_DIRECTORY / name
    if context.is_main:
        run_directory.mkdir(parents=True, exist_ok=True)
        for file_name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / file_name).unlink(missing_ok=True)
        print(description, flush=True)

    records: list[StepRecord] = []

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)
        records.append(record)
        peak = torch.cuda.max_memory_allocated(context.device) / 2**30
        if record.step <= LOGGED_FIRST_STEPS:
            seconds = record.training_seconds - (records[-2].training_seconds if len(records) > 1 else 0.0)
            print(f"step {record.step}: {record.tokens / seconds:,.0f} tokens/s, peak {peak:.1f} GiB", flush=True)
        if record.step == LOGGED_FIRST_STEPS:
            throughput = Throughput(
                name, records[WARMUP_STEPS - 1].training_seconds, steady_tokens_per_second(records, WARMUP_STEPS), peak
            )
            write_text(run_directory / "throughput.json", to_json(throughput) + "\n")
            print(f"throughput: {to_json(throughput)}", flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        append_json_line(run_directory / "evaluations.jsonl", record)
        point = validation_point(record)
        print(
            f"evaluation step {point.step}: offline loss {point.expert_iteration_loss}, replay loss {point.replay_loss}"
        )

    validation_sets = [ValidationSet(REPLAY_VALIDATION, replay.validation)] if replay.validation else []
    result = train(
        sft, tokenizer, examples, validation, context, adapter_directory, on_step, on_evaluation, validation_sets
    )
    if not context.is_main:
        return
    curve = tuple(validation_point(record) for record in result.evaluations)
    summary = OfflineTrainingSummary(
        run_name=name,
        initial_adapter=config.initial_policy_adapter,
        subset=subset,
        learning_rate=float(rate),
        epochs=optimization.epochs,
        steps=result.steps,
        offline_examples=len(offline),
        lean_replay_examples=len(replay.lean),
        math_replay_examples=len(replay.math),
        validation_examples=len(validation),
        completion_token_shares=shares,
        prompt_tokens=prompt_tokens,
        completion_tokens=sum(parts),
        training_seconds=result.training_seconds,
        steady_tokens_per_second=steady_tokens_per_second(records, WARMUP_STEPS),
        peak_memory_gib=result.peak_memory_gib,
        curve=curve,
        replay_loss_change=replay_loss_change(curve),
    )
    write_text(adapter_directory.parent / TRAINING_SUMMARY_FILE, to_json(summary) + "\n")
    print(to_json(summary), flush=True)


# held-out-config, probe-list, report


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def held_out_config(mode: Path, output: Path) -> None:
    table = with_sampling_mode(
        read_toml(REPOSITORY_DIRECTORY / BASE_LOOP_CONFIG), read_toml(REPOSITORY_DIRECTORY / mode)
    )
    write_text(
        output,
        f"# {BASE_LOOP_CONFIG} in the sampling mode {mode} (offline_arm.py held-out-config)\n" + toml_text(table),
    )
    load_loop_config(output)
    print(output)


def probe_run_name(config: OfflineArmConfig, subset: Subset) -> str:
    return f"{config.name}_{subset}"


def checked_rate(config: OfflineArmConfig, rate: str) -> str:
    if rate not in config.learning_rates:
        raise SystemExit(f"{rate} is not one of the config's learning rates {list(config.learning_rates)}.")
    return rate


def probe_list(
    config: OfflineArmConfig, subset: Subset, rate: str, output: Path, name: str, evaluation_config: str
) -> None:
    adapter = CHECKPOINTS_DIRECTORY / run_name(config, subset, checked_rate(config, rate)) / "adapter"
    run = {
        "name": name or probe_run_name(config, subset),
        "arm": f"offline_{subset}",
        "phase": 1,
        "policy_adapter": str(adapter),
        "value": "v0",
        "config": evaluation_config,
        "search_config": PROBE_SEARCH,
        "purpose": f"the offline arm's {subset} subset at {rate}",
    }
    lines = ["# Written by offline_arm.py probe-list", "[[runs]]"]
    lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in run.items()]
    write_text(output, "\n".join(lines) + "\n")
    print(output)


def chosen_rate(config: OfflineArmConfig, subset: Subset, rank: Path) -> None:
    label = chosen_label(rank.read_text(encoding="utf-8"))
    rates = {run_label(subset, rate): rate for rate in config.learning_rates}
    if label not in rates:
        raise SystemExit(f"The ranking chose {label}, not one of {sorted(rates)}.")
    print(rates[label])


def held_out_problems() -> tuple[dict[str, StateProblem], list[ReasoningState], str]:
    loop = load_loop_config(REPOSITORY_DIRECTORY / BASE_LOOP_CONFIG)
    path = RUNS_DIRECTORY / loop.evaluation.held_out_states_file
    states = read_records(path, ReasoningState)
    return {state.identifier: state_problem(state) for state in states}, states, file_sha256(path)


async def flat_references(processes: int, output: Path) -> None:
    _, states, _ = held_out_problems()
    async with LeanReplPool(processes, LeanReplConfig()) as pool:

        async def one(state: ReasoningState) -> FlatReference:
            try:
                async with pool.acquire() as repl:
                    return await flat_reference(repl, state)
            except Exception as error:
                # The state keeps the standard reference states in the ranking.
                return FlatReference(state.identifier, (), repr(error)[:MAX_FAILURE_CHARACTERS])

        references = await asyncio.gather(*(one(state) for state in states))
    write_text(output, "".join(to_json(reference) + "\n" for reference in references))
    failed = sum(bool(reference.failure) for reference in references)
    extended = sum(bool(reference.goal_keys) for reference in references)
    print(
        f"{len(references)} held-out states: {extended} with states inside their reference next step, {failed} whose "
        "next step did not run flattened (the standard reference states only). The file records each state's "
        "reference next step (one top-level tactic) and the goals after it and after each later top-level step; the "
        "later steps' texts are not kept, so states inside them are not known."
    )


def held_out_directory(name: str, states_sha256: str) -> Path:
    directory = RUNS_DIRECTORY / "held_out_evaluations" / f"held_out_{name}"
    if not (directory / "summary.json").exists():
        raise SystemExit(f"{directory} has no summary.json: the run has not sampled every state yet.")
    start = from_json_object(HeldOutRunStart, json.loads((directory / "checkpoint.json").read_text(encoding="utf-8")))
    if start.states_sha256 != states_sha256:
        raise SystemExit(f"{directory} sampled another states file ({start.states_file}).")
    return directory


def rank(config: OfflineArmConfig, subset: Subset, v0: str, references_path: Path, seed: int) -> None:
    problems, _, states_sha256 = held_out_problems()
    references = read_flat_references(references_path)
    without = sum(identifier not in references or not references[identifier].goal_keys for identifier in problems)
    print(
        f"{without} of {len(problems)} held-out states have no flattened reference (failed or missing): their "
        "flattened success counts the standard reference states only.\n"
    )

    def measures(label: str, name: str) -> HeldOutMeasures:
        return held_out_measures(label, held_out_directory(name, states_sha256) / "trees", problems, references)

    base = measures("v0", v0)
    found = {rate: measures(run_label(subset, rate), run_name(config, subset, rate)) for rate in config.learning_rates}
    for title, pick in (
        ("flattened", lambda measure: measure.flattened),
        ("standard", lambda measure: measure.standard),
    ):
        variants = [Variant(run_label(subset, rate), float(rate), pick(found[rate])) for rate in config.learning_rates]
        rows = [
            [report.label, interval_text(report.valid), interval_text(report.success)]
            for report in against_v0(variants, pick(base), None, seed)
        ]
        print(f"Held-out success, {title}: against v0 in points [95%], per state ({len(problems)})")
        print(markdown_table(["variant", "valid Lean", "success"], rows) + "\n")
    variants = [Variant(run_label(subset, rate), float(rate), found[rate].flattened) for rate in config.learning_rates]
    choice = choose_rate(variants, seed)
    print(
        f"Chosen: {choice.chosen} ({choice.reason}, on the flattened success; tied: {', '.join(choice.tied)})\n"
        "The flattened success also accepts a block ending inside the reference next step's nested proof, where the "
        "offline examples' blocks often end; the standard one only the states after whole top-level steps."
    )


def interval_text(found: DifferenceInterval) -> str:
    return f"{100 * found.difference:+.1f} [{100 * found.lower:+.1f}, {100 * found.upper:+.1f}]"


def report(config: OfflineArmConfig, subset: Subset, probe_name: str, seed: int) -> None:
    strata = {entry.name: entry.stratum for entry in read_fixed_set(DATA_DIRECTORY / PROBE_SET)}
    runs = RUNS_DIRECTORY / "probe_evaluations"
    name = probe_name or probe_run_name(config, subset)

    def arm(label: str, names: tuple[str, ...]) -> Arm:
        return Arm(label, tuple(read_arm_run(runs / f"probe_{run}", strata) for run in names))

    def paired(x: Arm, y: Arm) -> PairedDifference:
        try:
            return paired_difference(x, y, EQUAL_EXPANSIONS, seed, len(strata))
        except ValueError as error:
            raise SystemExit(f"Not evaluable: {error}") from error

    offline = arm(f"O ({subset})", (name,))
    gate = paired(offline, arm("run 8 (v35, value v0)", (GATE_RUN,)))
    noise = paired(arm("anchor run 1", ANCHOR_RUNS[:1]), arm("anchor run 2", ANCHOR_RUNS[1:]))
    descriptive = [
        paired(offline, arm("run 4 (v0, no reasoning, token cap)", (NO_REASONING_RUN,))),
        paired(offline, arm("anchors (v0, runs 1 and 2)", ANCHOR_RUNS)),
    ]
    print(f"# Offline arm `{subset}`: probe run {name}\n")
    print(gate_report(gate, noise, descriptive))


def main() -> None:
    arguments = parse_arguments()
    config = load_offline_arm_config(arguments.config)
    match arguments.command:
        case "download":
            download(config)
        case "prepare":
            prepare(config, arguments.processes)
        case "walk":
            asyncio.run(walk(config))
        case "build":
            build(config)
        case "train":
            run_training(config, arguments.subset, arguments.learning_rate, arguments.dry_run, arguments.gpus)
        case "held-out-config":
            held_out_config(arguments.mode, arguments.output)
        case "flat-references":
            asyncio.run(flat_references(arguments.processes, arguments.output))
        case "rank":
            rank(config, arguments.subset, arguments.v0, arguments.flat_references, arguments.seed)
        case "chosen-rate":
            chosen_rate(config, arguments.subset, arguments.rank)
        case "probe-list":
            probe_list(
                config, arguments.subset, arguments.rate, arguments.output, arguments.name, arguments.evaluation_config
            )
        case "report":
            report(config, arguments.subset, arguments.probe_name, arguments.seed)


if __name__ == "__main__":
    main()
