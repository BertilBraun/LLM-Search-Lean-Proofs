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
    python experiments/offline_arm.py --config $CONFIG probe-list --subset matched --rank rank_matched.txt \
        --output runs_matched.toml
    python experiments/offline_arm.py --config $CONFIG report --subset matched
CONFIG = experiments/configs/grpo/followup/offline/offline_arm.toml

download fetches the two public proof corpora the pool's proofs came from (Goedel-LM/SFT_dataset_v2, Leanabell SFT) at
phase 2's pinned revisions into $LEAN_SEARCH_DATA/<name>/raw (no token). prepare drops the pool statements the
evaluations hold out and their near-duplicates (formal statement and root state, every pair), normalizes the corpora as
phase 2 did and recovers each kept statement's verified proof (its candidates: the proofs of the recorded source,
tactic count and characters), into proofs.jsonl and preparation.json (counts per reason). walk (Lean CPUs only, through
background.sh; resumable) walks each proof as the search runs policy blocks into walks.jsonl, the candidates in order
until one walks to the end. build tokenizes the walked proofs' blocks in v0's no-reasoning SFT format
(render_prompt(goals) with the fence prefill; the block, the fence, end of turn), splits off the validation statements,
draws the matched subset, and writes <subset>/train.jsonl, validation.jsonl, build.json and README.md. train continues
v0's adapter on a subset (pool: [sft.optimization] epochs, one; matched: [matched] epochs, four) with the Lean and math
replay at their completion-token shares, into $LEAN_SEARCH_CHECKPOINTS/<name>_<subset>_<rate>/adapter and
training_summary.json beside it (refused if the adapter exists); --dry-run assembles the data and prints its size and
steps. held-out-config writes the follow-up base in the no-reasoning sampling mode, the loop config of the held-out
runs. probe-list writes the probe run list of the rate
experiments/rank_learning_rates.py chose. report writes the gate report of the subset's probe run (<name>_<subset>)
against run 8 at equal expansions, and descriptively against run 4 and the anchors within 16 expansions.
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
import time
import tomllib
from collections import Counter
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import transformers
from huggingface_hub import snapshot_download

from lean_search.corpora.download import HUGGING_FACE_DATASETS
from lean_search.corpora.lean_text import split_top_level_tactics
from lean_search.corpora.normalize import Rejection, normalize_proof
from lean_search.corpora.pipeline import statement_key
from lean_search.corpora.sources import PROOF_SOURCES, ProofShard
from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.expert_iteration.known_proofs import read_verified
from lean_search.expert_iteration.mixing import is_held_out
from lean_search.expert_iteration.pool import pool_problem
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.policy.prompts import FENCE
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.arm_comparison import Arm, read_arm_run
from lean_search.rl.expert_iteration_data import ValidationPoint, replay_data, replay_loss_change
from lean_search.rl.fixed_sets import read_fixed_set
from lean_search.rl.learning_rate_step import chosen_label
from lean_search.rl.loop_config import load_loop_config
from lean_search.rl.offline_arm import (
    EXAMPLE_SOURCE,
    BandSize,
    CorpusProof,
    ExampleTokens,
    OfflineArmConfig,
    PoolProof,
    ProofExamples,
    ProofTarget,
    Subset,
    band_sizes,
    hash_order,
    held_out_references,
    load_offline_arm_config,
    matched_sample,
    pool_selection,
    read_pool_proofs,
    recovered_candidates,
    run_label,
    run_name,
    subset_epochs,
)
from lean_search.rl.offline_report import gate_report, paired_difference
from lean_search.rl.offline_walk import ProofWalk, WalkedProof, WalkSettings, WalkStatus, walk_candidates
from lean_search.rl.study_configs import with_sampling_mode
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
TRAINING_SUMMARY_FILE = "training_summary.json"
REPLAY_VALIDATION = "replay"
LOG_EVERY = 500
# A walk session whose walks raised more often than this exits non-zero, so the driver's next start walks them again.
MAX_ERROR_SHARE = 0.01


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
    probe_list = commands.add_parser("probe-list")
    probe_list.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
    probe_list.add_argument("--rank", type=Path, required=True, help="experiments/rank_learning_rates.py's output")
    probe_list.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("--subset", type=Subset, choices=list(Subset), required=True)
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
    by_key = {}
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
    ordered = sorted(candidates, key=lambda key: hash_order(config.walk.seed, by_key[key].name))
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


async def walk(config: OfflineArmConfig) -> None:
    directory = arm_directory(config)
    proofs = read_pool_proofs(directory / "proofs.jsonl")
    output = directory / "walks.jsonl"
    # A walk that raised is walked again.
    done = {
        walked.name for walked in latest_walks(read_walks(output)).values() if walked.walk.status != WalkStatus.ERROR
    }
    remaining = [proof for proof in proofs if proof.name not in done]
    log(f"{len(done):,} of {len(proofs):,} proofs walked; walking {len(remaining):,}")
    if not remaining:
        return
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
                        failure = ProofWalk(WalkStatus.ERROR, (), 0, repr(error)[:300], None)
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
    if statuses[WalkStatus.ERROR] > MAX_ERROR_SHARE * len(remaining):
        raise SystemExit(f"{statuses[WalkStatus.ERROR]:,} walks raised: they are walked again by the next start.")


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
    # Per walk status (rl/offline_walk.WalkStatus), the proofs.
    walks: dict[str, int]
    # Complete walks by the candidate that walked (1 is the first).
    candidates: dict[str, int]
    skipped_blocks: int
    # Examples dropped for a prompt over walk.max_prompt_tokens, and repeated (state, block) pairs.
    over_prompt_cap: int
    duplicates: int
    # Training examples by the block's tactics (1, 2, ..., the last bucket and more).
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


def build(config: OfflineArmConfig) -> None:
    directory = arm_directory(config)
    proofs = {proof.name: proof for proof in read_pool_proofs(directory / "proofs.jsonl")}
    walks = list(latest_walks(read_walks(directory / "walks.jsonl")).values())
    if {walked.name for walked in walks} != set(proofs):
        raise SystemExit(f"walks.jsonl covers {len(walks):,} of the {len(proofs):,} proofs: walk first.")
    run_config = load_run_config(REPOSITORY_DIRECTORY / config.walk.search_config)
    tokenizer = transformers.AutoTokenizer.from_pretrained(run_config.policy.tokenizer)
    seen: set[tuple[tuple[str, ...], str]] = set()
    over_cap = duplicates = 0
    train: list[ProofExamples] = []
    validation: list[ProofExamples] = []
    lengths: Counter[int] = Counter()
    for walked in sorted(walks, key=lambda walked: hash_order(config.walk.seed, walked.name)):
        if walked.walk.status != WalkStatus.COMPLETE:
            continue
        examples: list[SftExample] = []
        tokens: list[ExampleTokens] = []
        for index, block in enumerate(walked.walk.blocks):
            if (block.goals, block.block) in seen:
                duplicates += 1
                continue
            seen.add((block.goals, block.block))
            example = SftExample(EXAMPLE_SOURCE, walked.name, index, block.goals, block.block)
            tokenized = tokenize_example(tokenizer, example)
            if tokenized.prompt_token_count > config.walk.max_prompt_tokens:
                over_cap += 1
                continue
            examples.append(example)
            tokens.append(ExampleTokens(tokenized.prompt_token_count, tokenized.completion_token_count))
        if not examples:
            continue
        found = ProofExamples(walked.name, proofs[walked.name].proof_characters, tuple(examples), tuple(tokens))
        if is_held_out(walked.name, config.data.seed, config.data.validation_fraction):
            validation.append(found)
        else:
            train.append(found)
            lengths.update(min(block.tactics, config.walk.max_block_tactics) for block in walked.walk.blocks)
    matched = matched_sample(train, config.matched)
    edges = config.matched.band_edges
    write_examples(directory / "validation.jsonl", validation)
    write_examples(directory / Subset.POOL / "train.jsonl", train)
    write_examples(directory / Subset.MATCHED / "train.jsonl", matched)
    summary = BuildSummary(
        built_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        proofs=len(proofs),
        walks=dict(Counter(str(walked.walk.status) for walked in walks)),
        candidates=dict(
            sorted(Counter(str(walked.candidate + 1) for walked in walks if walked.candidate is not None).items())
        ),
        skipped_blocks=sum(walked.walk.skipped_blocks for walked in walks),
        over_prompt_cap=over_cap,
        duplicates=duplicates,
        block_tactics={str(length): lengths[length] for length in sorted(lengths)},
        validation=subset_size("validation", validation, edges),
        subsets=(subset_size(Subset.POOL, train, edges), subset_size(Subset.MATCHED, matched, edges)),
    )
    write_text(directory / "build.json", to_json(summary) + "\n")
    markdown = build_markdown(config, summary)
    write_text(directory / "README.md", markdown)
    print(markdown, flush=True)


def size_row(label: str, size: SubsetSize | BandSize) -> list[object]:
    return [label, f"{size.proofs:,}", f"{size.examples:,}", f"{size.prompt_tokens:,}", f"{size.completion_tokens:,}"]


def build_markdown(config: OfflineArmConfig, summary: BuildSummary) -> str:
    headers = ["Proofs, examples, tokens", "Proofs", "Examples", "Prompt tokens", "Completion tokens"]
    sections = [
        f"# Offline arm data `{config.name}`",
        f"Walks of {summary.proofs:,} recovered pool proofs, by status:",
        markdown_table(["Status", "Proofs"], [[status, f"{count:,}"] for status, count in summary.walks.items()]),
        f"Complete walks by the candidate proof that walked: {summary.candidates}. Blocks run without an example (one "
        f"step over the completion cap): {summary.skipped_blocks:,}; examples dropped for a prompt over "
        f"{config.walk.max_prompt_tokens:,} tokens: {summary.over_prompt_cap:,}; repeated (state, block) pairs: "
        f"{summary.duplicates:,}. Training blocks by tactics: {summary.block_tactics}.",
        markdown_table(headers, [size_row(size.subset, size) for size in (*summary.subsets, summary.validation)]),
    ]
    for size in summary.subsets:
        sections += [
            f"By proof characters, `{size.subset}`:",
            markdown_table(["Band", *headers[1:]], [size_row(band.band, band) for band in size.bands]),
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
    curve: tuple[ValidationPoint, ...]
    replay_loss_change: float | None


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
        print(description)
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

    def on_step(record: StepRecord) -> None:
        append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

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


def probe_list(config: OfflineArmConfig, subset: Subset, rank: Path, output: Path) -> None:
    label = chosen_label(rank.read_text(encoding="utf-8"))
    rates = {run_label(subset, rate): rate for rate in config.learning_rates}
    if label not in rates:
        raise SystemExit(f"The ranking chose {label}, not one of {sorted(rates)}.")
    adapter = CHECKPOINTS_DIRECTORY / run_name(config, subset, rates[label]) / "adapter"
    run = {
        "name": probe_run_name(config, subset),
        "arm": f"offline_{subset}",
        "phase": 1,
        "policy_adapter": str(adapter),
        "value": "v0",
        "config": PROBE_EVALUATION,
        "search_config": PROBE_SEARCH,
        "purpose": f"the offline arm's {subset} subset at {rates[label]}, the rate the held-out states chose",
    }
    lines = [f"# Written by offline_arm.py probe-list from {rank}", "[[runs]]"]
    lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in run.items()]
    write_text(output, "\n".join(lines) + "\n")
    print(output)


def report(config: OfflineArmConfig, subset: Subset, seed: int) -> None:
    strata = {entry.name: entry.stratum for entry in read_fixed_set(DATA_DIRECTORY / PROBE_SET)}
    runs = RUNS_DIRECTORY / "probe_evaluations"

    def arm(label: str, names: tuple[str, ...]) -> Arm:
        return Arm(label, tuple(read_arm_run(runs / f"probe_{name}", strata) for name in names))

    offline = arm(f"O ({subset})", (probe_run_name(config, subset),))
    gate = paired_difference(offline, arm("run 8 (v35, value v0)", (GATE_RUN,)), EQUAL_EXPANSIONS, seed)
    descriptive = [
        paired_difference(
            offline, arm("run 4 (v0, no reasoning, token cap)", (NO_REASONING_RUN,)), EQUAL_EXPANSIONS, seed
        ),
        paired_difference(offline, arm("anchors (v0, runs 1 and 2)", ANCHOR_RUNS), EQUAL_EXPANSIONS, seed),
    ]
    print(f"# Offline arm `{subset}`: probe run {probe_run_name(config, subset)}\n")
    print(gate_report(gate, descriptive))


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
        case "probe-list":
            probe_list(config, arguments.subset, arguments.rank, arguments.output)
        case "report":
            report(config, arguments.subset, arguments.seed)


if __name__ == "__main__":
    main()
