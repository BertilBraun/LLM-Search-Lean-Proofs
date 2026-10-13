"""Training phases of the loop: pause the searches in place, train from the replay buffers, publish, resume.

A phase starts after `new_proofs` new proofs (at least `min_minutes` after the last phase) or after `max_minutes`, and
runs these stages, each recorded in training/state.json so that a crash resumes at the stage it interrupted:

pause    the searches stop sending requests and keep their trees and REPL proof states; the open shard closes
compress (thinking mode, with a reasoning shortener) new closed shards are digested and the reasoning of their
         proof-step pairs is shortened on the still-running servers, keeping only versions that still lead the policy
         to a working step
release  every vLLM server stops (or sleeps), freeing both GPUs
data     the digests not used yet (new closed shards are digested first); the value model's quality on held-out
         fresh trees decides whether
         value-jump pairs count; the search samples enter the policy and value FIFO buffers (capacities follow the
         inflow); each model trains on reuse x (samples added) drawn uniformly from its buffer
train    the policy (DPO + NLL, reference = the published policy) and the value model (bin cross-entropy) continue
         from the current adapters, in parallel, one GPU each
publish  version k + 1 is prepared (e.g. merged) and pointed at by models/current.json
restore  the servers come back with the new weights
evaluate (version 0 and every `evaluation.every_versions`-th) miniF2F-valid at the evaluation's reduced budget, with
         the GPUs and the service's CPUs to itself while the searches stay paused
resume   the searches continue where they paused; stale frontier states are re-scored as they come up
"""

import asyncio
import contextlib
import dataclasses
import datetime
import json
import os
import random
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from lean_search.corpora.records import DataSplit, read_traced_steps
from lean_search.expert_iteration.digests import (
    DigestConfig,
    VersionedPair,
    VersionedValueExample,
    digest_new_shards,
    digested,
    read_contexts,
    read_digest_summary,
    read_jumps,
    read_policy,
    read_values,
    write_policy,
)
from lean_search.expert_iteration.loop_config import LoopConfig, ThinkingConfig, TrainingConfig, TrainingStage
from lean_search.expert_iteration.loop_evaluation import (
    EvaluationRecord,
    append_evaluation,
    evaluation_config_text,
    evaluation_due,
    read_evaluations,
)
from lean_search.expert_iteration.mixing import is_held_out
from lean_search.expert_iteration.preferences import ValueJumpConfig
from lean_search.expert_iteration.proofs import identifier_problem
from lean_search.expert_iteration.replay_buffer import (
    BufferStatistics,
    FifoBuffer,
    PolicySample,
    SampleOrigin,
    ValueSample,
    adapted_capacity,
    phase_statistics,
    read_buffer_items,
    trained_count,
    updated_inflow,
    write_buffer,
)
from lean_search.expert_iteration.serving import (
    GpuRelease,
    LoopPaths,
    ModelVersion,
    Publisher,
    read_current,
    record_published,
    write_json_atomically,
)
from lean_search.expert_iteration.shards import SUMMARY_FILE, now, read_attempts, read_shard_summary
from lean_search.expert_iteration.thinking import ThinkingItem
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import RunSummary
from lean_search.training.dpo_data import PreferencePair, pair_key, write_pairs
from lean_search.value.labels import LabelKind, ValueExample, merge_duplicates, read_examples, write_examples
from lean_search.value.metrics import roc_auc, spearman_correlation

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
NO_SETTINGS: Mapping[str, object] = MappingProxyType({})
# Template tokens around a thinking completion (end of thoughts, fences, end of turn).
THINKING_COMPLETION_MARGIN = 64
COMPRESSED_MARKER = "compressed"
# Digests whose samples entered the buffers, one name per line.
USED_DIGESTS_FILE = "used_digests.txt"
VALIDATION_SAMPLES = 1000
EVALUATION_WAIT_SECONDS = 1800.0


class PhaseStage(StrEnum):
    PAUSE = "pause"
    COMPRESS = "compress"
    RELEASE = "release"
    DATA = "data"
    TRAIN = "train"
    PUBLISH = "publish"
    RESTORE = "restore"
    EVALUATE = "evaluate"
    RESUME = "resume"
    DONE = "done"


STAGE_ORDER = tuple(PhaseStage)


@dataclass(frozen=True)
class Progress:
    minutes_since_phase: float
    new_attempts: int
    # Statements proved since the last phase, and all proofs with the harvested ones.
    new_solved: int
    new_proofs: int


@dataclass(frozen=True)
class ValueGate:
    """The value model's quality on held-out fresh trees, which decides whether value-jump pairs count."""

    exact_states: int
    dead_states: int
    spearman: float | None
    dead_auc: float | None
    open: bool


@dataclass(frozen=True)
class BufferInflows:
    # Moving averages of the search samples added per phase; None before the first phase.
    policy: float | None
    value: float | None


@dataclass(frozen=True)
class PhaseData:
    policy: BufferStatistics
    value: BufferStatistics
    gate: ValueGate
    digested_shards: int
    new_proofs: int
    new_policy_proofs: int
    new_pairs: int
    new_jump_pairs: int
    jump_pairs_used: int


@dataclass(frozen=True)
class PhaseState:
    # The phase number, which is also the version it publishes.
    phase: int
    stage: PhaseStage
    trigger: str
    started_at: str
    # Adapters after training; empty before the train stage.
    policy_adapter: str
    value_adapter: str
    data: PhaseData | None


@dataclass(frozen=True)
class PhaseRecord:
    phase: int
    trigger: str
    started_at: str
    finished_at: str
    data: PhaseData | None
    policy_adapter: str
    value_adapter: str


class PausableSearches(Protocol):
    # Held by a phase and by an operator's hold, so that at most one of them owns the GPUs at a time.
    gpu_lock: asyncio.Lock

    async def pause(self) -> None: ...

    async def resume(self, rescore: bool) -> None: ...


class ReasoningShortener(Protocol):
    """Per item, a shorter reasoning that still leads the policy to a working step, or the item's own."""

    async def shorten(self, items: Sequence[ThinkingItem]) -> list[str]: ...


def phase_trigger(progress: Progress, config: TrainingConfig) -> str | None:
    if progress.new_proofs >= config.new_proofs and progress.minutes_since_phase >= config.min_minutes:
        return "proofs"
    if progress.minutes_since_phase >= config.max_minutes and progress.new_proofs >= config.minimum_new_proofs:
        return "time"
    return None


def minutes_since(timestamp: str, current: datetime.datetime) -> float:
    return (current - datetime.datetime.fromisoformat(timestamp)).total_seconds() / 60


def progress_since(shards: Path, since: str, current: datetime.datetime) -> Progress:
    """Attempts finished since a time: only shards still open or closed after it are read."""
    attempts = solved = proofs = 0
    directories = sorted((path for path in shards.iterdir() if path.is_dir()), reverse=True) if shards.exists() else []
    for shard in directories:
        if (shard / SUMMARY_FILE).exists() and read_shard_summary(shard).closed_at < since:
            break
        for attempt in read_attempts(shard):
            if attempt.finished_at >= since:
                attempts += 1
                solved += attempt.proved
                proofs += attempt.proofs
    return Progress(minutes_since(since, current), attempts, solved, proofs)


def value_gate(values: Sequence[VersionedValueExample], config: ValueJumpConfig) -> ValueGate:
    """Spearman of h with the exact remaining steps, and h separating dead from exact states (higher h, dead)."""
    scored = [value for value in values if value.estimate is not None and value.example.kind != LabelKind.AT_LEAST]
    exact = [value for value in scored if value.example.kind == LabelKind.EXACT]
    dead = len(scored) - len(exact)
    spearman = (
        spearman_correlation([value.estimate for value in exact], [float(value.example.steps) for value in exact])
        if len(exact) > 1
        else None
    )
    dead_auc = roc_auc([value.estimate for value in scored], [value.example.kind == LabelKind.DEAD for value in scored])
    is_open = (
        len(exact) >= config.gate_minimum_states
        and spearman is not None
        and dead_auc is not None
        and spearman >= config.gate_spearman
        and dead_auc >= config.gate_dead_auc
    )
    return ValueGate(len(exact), dead, spearman, dead_auc, is_open)


def search_policy_samples(pairs: Iterable[VersionedPair], phase: int, known: set[bytes]) -> list[PolicySample]:
    """New search samples, each (goals, chosen, rejected) once; `known` gains their keys."""
    samples = []
    for versioned in pairs:
        key = pair_key(versioned.pair)
        if key not in known:
            known.add(key)
            samples.append(PolicySample(SampleOrigin.SEARCH, phase, versioned.pair))
    return samples


def search_value_samples(values: Iterable[VersionedValueExample], phase: int) -> list[ValueSample]:
    return [ValueSample(SampleOrigin.SEARCH, phase, example) for example in merge_duplicates(v.example for v in values)]


def dataset_policy_samples(traced_directory: Path, sources: Sequence[str], count: int, seed: str) -> list[PolicySample]:
    """Traced train-split steps of the given sources as chosen-only samples, a fixed pseudo-random subset."""
    steps = [
        step
        for step in read_traced_steps(traced_directory / f"steps_{DataSplit.TRAIN}.jsonl")
        if step.source in sources
    ]
    chosen = random.Random(seed).sample(steps, min(count, len(steps)))
    return [
        PolicySample(
            SampleOrigin.DATASET,
            0,
            PreferencePair(
                step.source,
                step.proof_identifier,
                step.step_index,
                step.goals_before,
                normalize_tactic_block(step.step),
                None,
                "dataset",
            ),
        )
        for step in chosen
    ]


def dataset_value_samples(path: Path, count: int, seed: str) -> list[ValueSample]:
    examples = list(read_examples(path))
    chosen = random.Random(seed).sample(examples, min(count, len(examples)))
    return [ValueSample(SampleOrigin.DATASET, 0, example) for example in chosen]


def training_config_text(
    template: str, data: str, initial_adapter: str, settings: Mapping[str, object] = NO_SETTINGS
) -> str:
    """The template with the phase's data and adapter, and `settings` (top-level keys) on top."""
    table = tomllib.loads(template) | dict(settings)
    table["data"] = data
    table["initial_adapter"] = initial_adapter
    return toml_text(table)


def policy_settings(thinking: ThinkingConfig) -> Mapping[str, object]:
    """Thinking pairs render with the search's instruction, and their completions hold the reasoning too."""
    if not thinking.enabled:
        return NO_SETTINGS
    return {
        "thinking_instruction": thinking.instruction,
        "max_completion_tokens": thinking.max_tokens + THINKING_COMPLETION_MARGIN,
    }


def relative_data(directory: Path, root: Path) -> str:
    return os.path.relpath(directory, root).replace(os.sep, "/")


def next_stage(stage: PhaseStage) -> PhaseStage:
    return STAGE_ORDER[STAGE_ORDER.index(stage) + 1]


def read_phase_state(paths: LoopPaths) -> PhaseState | None:
    if not paths.phase_state.exists():
        return None
    return from_json_object(PhaseState, json.loads(paths.phase_state.read_text(encoding="utf-8")))


def read_inflows(paths: LoopPaths) -> BufferInflows:
    path = paths.buffers / "inflows.json"
    if not path.exists():
        return BufferInflows(None, None)
    return from_json_object(BufferInflows, json.loads(path.read_text(encoding="utf-8")))


class PhaseTrainer:
    def __init__(
        self,
        config: LoopConfig,
        paths: LoopPaths,
        publisher: Publisher,
        gpu_release: GpuRelease,
        checkpoints: Path,
        log: Callable[[str], None],
        value_continues: bool,
        reasoning_shortener: ReasoningShortener | None = None,
    ) -> None:
        self.config = config
        self.reasoning_shortener = reasoning_shortener
        self.paths = paths
        self.publisher = publisher
        self.gpu_release = gpu_release
        self.checkpoints = checkpoints
        self.log = log
        # Whether value training can start from an adapter; otherwise the value model stays as published.
        self.value_continues = value_continues

    @property
    def digest_config(self) -> DigestConfig:
        training = self.config.training
        return DigestConfig(
            training.preferences,
            training.chosen_only_steps,
            training.value_jumps,
            training.labels,
            training.max_labels_per_tree,
        )

    def held_out(self, problem_name: str) -> bool:
        return is_held_out(problem_name, self.config.training.seed, self.config.training.held_out_fraction)

    async def watch(self, searches: PausableSearches, stop: asyncio.Event) -> None:
        """Starts a phase whenever the trigger fires, until stopped."""
        training = self.config.training
        while not stop.is_set():
            current = read_current(self.paths)
            progress = progress_since(self.paths.shards, current.published_at, datetime.datetime.now(datetime.UTC))
            trigger = phase_trigger(progress, training)
            if trigger is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), training.check_seconds)
                continue
            async with searches.gpu_lock:
                self.log(f"Phase {current.version + 1} ({trigger}): {progress}")
                state = PhaseState(current.version + 1, PhaseStage.PAUSE, trigger, now(), "", "", None)
                write_json_atomically(self.paths.phase_state, state)
                await self.run_phase(state, searches)

    async def run_phase(self, state: PhaseState, searches: PausableSearches | None) -> None:
        """From the state's stage to the end; without searches (after a restart) pausing and resuming do nothing."""
        while state.stage != PhaseStage.DONE:
            started = datetime.datetime.now(datetime.UTC)
            state = await self.run_stage(state, searches)
            seconds = (datetime.datetime.now(datetime.UTC) - started).total_seconds()
            self.log(f"Phase {state.phase}: {state.stage} took {seconds:.0f} s")
            state = dataclasses.replace(state, stage=next_stage(state.stage))
            write_json_atomically(self.paths.phase_state, state)
        record = PhaseRecord(
            state.phase, state.trigger, state.started_at, now(), state.data, state.policy_adapter, state.value_adapter
        )
        with self.paths.phases.open("a", encoding="utf-8") as handle:
            handle.write(to_json(record) + "\n")
        self.log(f"Phase {state.phase} done: {state.data}")

    async def run_stage(self, state: PhaseState, searches: PausableSearches | None) -> PhaseState:
        servers = self.config.serving.servers
        match state.stage:
            case PhaseStage.PAUSE:
                await self.wait_for_evaluation()
                if searches is not None:
                    await searches.pause()
            case PhaseStage.COMPRESS:
                if self.reasoning_shortener is not None:
                    await self.compress_reasoning()
            case PhaseStage.RELEASE:
                await asyncio.gather(*(self.gpu_release.release(server) for server in servers))
            case PhaseStage.DATA:
                return dataclasses.replace(state, data=await asyncio.to_thread(self.build_data, state.phase))
            case PhaseStage.TRAIN:
                policy, value = await self.train(state)
                return dataclasses.replace(state, policy_adapter=policy, value_adapter=value)
            case PhaseStage.PUBLISH:
                await asyncio.to_thread(self.publish, state)
            case PhaseStage.RESTORE:
                version = read_current(self.paths)
                await asyncio.gather(*(self.gpu_release.restore(server, version) for server in servers))
            case PhaseStage.EVALUATE:
                await self.evaluate_if_due()
            case PhaseStage.RESUME:
                if searches is not None:
                    await searches.resume(self.config.training.rescore_frontier)
            case PhaseStage.DONE:
                pass
        return state

    async def wait_for_evaluation(self) -> None:
        """The searches keep running meanwhile; the phase pauses them once the evaluation is done."""
        waited = 0.0
        if self.paths.evaluation_lock.exists():
            self.log("Waiting for the running evaluation before pausing the searches")
        while self.paths.evaluation_lock.exists() and waited < EVALUATION_WAIT_SECONDS:
            await asyncio.sleep(10)
            waited += 10

    async def evaluate_if_due(self) -> None:
        """The published version on miniF2F-valid when due; a failed evaluation is logged and skipped, not retried."""
        version = read_current(self.paths)
        evaluations = read_evaluations(self.paths.evaluations)
        if not evaluation_due(evaluations, datetime.datetime.now(datetime.UTC), self.config.evaluation):
            return
        run_name = f"{self.paths.name}_evaluation_v{version.version:04d}"
        run_directory = self.paths.runs_root / run_name
        if run_directory.exists():
            run_directory.rename(run_directory.with_name(f"{run_name}.incomplete_{int(time.time())}"))
        template = (REPOSITORY_DIRECTORY / self.config.evaluation.config).read_text(encoding="utf-8")
        config_path = self.paths.directory / "evaluations" / f"v{version.version:04d}.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_text = evaluation_config_text(
            template, self.config.serving, self.config.evaluation, self.config.search.thinking
        )
        config_path.write_text(config_text, encoding="utf-8")
        started_at = now()
        self.log(f"Evaluating version {version.version} on miniF2F-valid")
        log_path = self.paths.directory / "training" / f"evaluation_v{version.version:04d}.log"
        command = f"python experiments/run_search.py --config {config_path} --split valid --run-name {run_name}"
        with log_path.open("a", encoding="utf-8") as log_file:
            process = await asyncio.create_subprocess_exec(
                "bash", "-c", command, cwd=REPOSITORY_DIRECTORY, stdout=log_file, stderr=log_file
            )
            if await process.wait():
                self.log(f"Evaluation of version {version.version} failed; see {log_path}")
                return
        summary = from_json_object(
            RunSummary, json.loads((run_directory / "summary" / "summary.json").read_text(encoding="utf-8"))
        )
        record = EvaluationRecord(version.version, run_name, summary.problems, summary.solved, started_at, now())
        append_evaluation(self.paths.evaluations, record)
        self.log(f"Version {version.version}: {record.solved}/{record.problems} on miniF2F-valid")

    async def compress_reasoning(self) -> None:
        """Shortens the reasoning of the new digests' proof-step pairs, once per digest."""
        assert self.reasoning_shortener is not None
        await asyncio.to_thread(digest_new_shards, self.paths.shards, self.paths.digests, self.digest_config)
        used = self.used_digests()
        for digest in digested(self.paths.digests):
            marker = digest / COMPRESSED_MARKER
            if digest.name in used or marker.exists():
                continue
            pairs = list(read_policy(digest))
            contexts = {context.pair_key: context for context in read_contexts(digest)}
            positions = [position for position, pair in enumerate(pairs) if pair_key(pair.pair).hex() in contexts]
            items = [
                ThinkingItem(pairs[position].pair, contexts[pair_key(pairs[position].pair).hex()])
                for position in positions
            ]
            shortened = await self.reasoning_shortener.shorten(items)
            for position, reasoning in zip(positions, shortened, strict=True):
                pair = dataclasses.replace(pairs[position].pair, chosen_reasoning=reasoning)
                pairs[position] = dataclasses.replace(pairs[position], pair=pair)
            write_policy(digest, pairs)
            marker.write_text(now(), encoding="utf-8")
            self.log(f"Reasoning of {len(items):,} pairs of digest {digest.name} shortened where it stayed sufficient")

    def used_digests(self) -> set[str]:
        path = self.paths.buffers / USED_DIGESTS_FILE
        return set(path.read_text(encoding="utf-8").split()) if path.exists() else set()

    def build_data(self, phase: int) -> PhaseData:
        training = self.config.training
        digest_new_shards(self.paths.shards, self.paths.digests, self.digest_config)
        used = self.used_digests()
        digests = [digest for digest in digested(self.paths.digests) if digest.name not in used]
        new_digests = [read_digest_summary(digest) for digest in digests]
        new_values = [value for digest in digests for value in read_values(digest)]
        gate = value_gate(
            [value for value in new_values if self.held_out(value.example.identifier)], training.value_jumps
        )
        new_pairs = [pair for digest in digests for pair in read_policy(digest)]
        new_jumps = [pair for digest in digests for pair in read_jumps(digest)] if gate.open else []
        inflows = read_inflows(self.paths)

        policy_buffer = self.load_policy_buffer()
        known = {pair_key(sample.pair) for sample in policy_buffer.items()}
        new_policy = search_policy_samples(
            (
                pair
                for pair in [*new_pairs, *new_jumps]
                if not self.held_out(identifier_problem(pair.pair.proof_identifier))
            ),
            phase,
            known,
        )
        policy_inflow = updated_inflow(inflows.policy, len(new_policy))
        policy_buffer.capacity = adapted_capacity(training.policy_buffer, policy_inflow)
        policy_buffer.minimum_dataset_share = training.policy_buffer.minimum_dataset_share
        self.top_up_policy_dataset(policy_buffer, phase)
        policy_evicted = policy_buffer.add(new_policy)
        policy_trained = policy_buffer.sample(
            min(trained_count(len(new_policy), training.policy_buffer.reuse), training.max_policy_samples),
            random.Random(f"{training.seed}/{phase}"),
        )

        value_buffer = self.load_value_buffer()
        new_value = search_value_samples(
            (value for value in new_values if not self.held_out(value.example.identifier)), phase
        )
        value_inflow = updated_inflow(inflows.value, len(new_value))
        value_buffer.capacity = adapted_capacity(training.value_buffer, value_inflow)
        value_buffer.minimum_dataset_share = training.value_buffer.minimum_dataset_share
        self.top_up_value_dataset(value_buffer, phase)
        value_evicted = value_buffer.add(new_value)
        value_trained = value_buffer.sample(
            min(trained_count(len(new_value), training.value_buffer.reuse), training.max_value_samples),
            random.Random(f"{training.seed}/{phase}"),
        )

        directory = self.paths.phase_data(phase)
        held_out_pairs = [
            pair.pair for pair in new_pairs if self.held_out(identifier_problem(pair.pair.proof_identifier))
        ]
        write_pairs(directory / "policy" / "train.jsonl", (sample.pair for sample in policy_trained))
        write_pairs(directory / "policy" / "validation.jsonl", held_out_pairs[:VALIDATION_SAMPLES])
        write_examples(directory / "value" / "train.jsonl", (sample.example for sample in value_trained))
        write_examples(directory / "value" / "validation.jsonl", self.value_validation(new_values))
        write_buffer(self.paths.buffers / "policy.jsonl", policy_buffer)
        write_buffer(self.paths.buffers / "value.jsonl", value_buffer)
        write_json_atomically(self.paths.buffers / "inflows.json", BufferInflows(policy_inflow, value_inflow))
        (self.paths.buffers / USED_DIGESTS_FILE).write_text(
            "".join(f"{name}\n" for name in sorted(used | {digest.name for digest in digests})), encoding="utf-8"
        )
        data = PhaseData(
            policy=phase_statistics(
                "policy", policy_buffer, policy_inflow, len(new_policy), policy_evicted, policy_trained
            ),
            value=phase_statistics("value", value_buffer, value_inflow, len(new_value), value_evicted, value_trained),
            gate=gate,
            digested_shards=len(new_digests),
            new_proofs=sum(summary.proofs for summary in new_digests),
            new_policy_proofs=sum(summary.policy_proofs for summary in new_digests),
            new_pairs=len(new_pairs),
            new_jump_pairs=sum(summary.jump_pairs for summary in new_digests),
            jump_pairs_used=len(new_jumps),
        )
        (directory / "data.json").write_text(to_json(data), encoding="utf-8")
        return data

    def value_validation(self, new_values: Sequence[VersionedValueExample]) -> list[ValueExample]:
        dataset = self.paths.data_root / "value" / self.config.training.value_dataset / "validation.jsonl"
        tree = merge_duplicates(value.example for value in new_values if self.held_out(value.example.identifier))
        return [*tree[:VALIDATION_SAMPLES], *list(read_examples(dataset))[:VALIDATION_SAMPLES]]

    def top_up_policy_dataset(self, buffer: FifoBuffer[PolicySample], phase: int) -> None:
        """Fresh dataset samples (not in the buffer) when the dataset share would fall below its floor."""
        shortfall = buffer.dataset_shortfall()
        if not shortfall:
            return
        training = self.config.training
        present = {pair_key(sample.pair) for sample in buffer.dataset}
        drawn = dataset_policy_samples(
            self.paths.data_root / training.traced_directory,
            [source.name for source in training.traced_sources],
            shortfall + len(present),
            f"{training.seed}/{phase}",
        )
        buffer.add([sample for sample in drawn if pair_key(sample.pair) not in present][:shortfall])

    def top_up_value_dataset(self, buffer: FifoBuffer[ValueSample], phase: int) -> None:
        shortfall = buffer.dataset_shortfall()
        if not shortfall:
            return
        training = self.config.training
        present = {sample.example for sample in buffer.dataset}
        dataset = self.paths.data_root / "value" / training.value_dataset / "train.jsonl"
        drawn = dataset_value_samples(dataset, shortfall + len(present), f"{training.seed}/{phase}")
        buffer.add([sample for sample in drawn if sample.example not in present][:shortfall])

    def load_policy_buffer(self) -> FifoBuffer[PolicySample]:
        training = self.config.training
        path = self.paths.buffers / "policy.jsonl"
        if path.exists():
            # The phase sets the capacity; until then the buffer holds what it held.
            stored = list(read_buffer_items(path, PolicySample))
            return FifoBuffer(len(stored), stored)
        sources = [source.name for source in training.traced_sources]
        samples = dataset_policy_samples(
            self.paths.data_root / training.traced_directory,
            sources,
            training.policy_buffer.initial_capacity,
            training.seed,
        )
        return FifoBuffer(training.policy_buffer.initial_capacity, samples)

    def load_value_buffer(self) -> FifoBuffer[ValueSample]:
        training = self.config.training
        path = self.paths.buffers / "value.jsonl"
        if path.exists():
            stored = list(read_buffer_items(path, ValueSample))
            return FifoBuffer(len(stored), stored)
        dataset = self.paths.data_root / "value" / training.value_dataset / "train.jsonl"
        samples = dataset_value_samples(dataset, training.value_buffer.initial_capacity, training.seed)
        return FifoBuffer(training.value_buffer.initial_capacity, samples)

    async def train(self, state: PhaseState) -> tuple[str, str]:
        assert state.data is not None, state.phase
        current = read_current(self.paths)
        directory = self.paths.phase_data(state.phase)
        jobs = []
        policy, value = current.policy_adapter, current.value_adapter
        if state.data.policy.trained:
            run = self.paths.phase_run_name(state.phase, "policy")
            data = relative_data(directory / "policy", self.paths.data_root)
            config = self.stage_config(state.phase, "policy", self.config.training.policy, data, policy)
            jobs.append(
                self.run_training(
                    state.phase,
                    "policy",
                    self.config.training.policy,
                    f"python experiments/phase6_dpo.py --config {config} --run-name {run}",
                )
            )
            policy = str(self.checkpoints / run / "adapter")
        if state.data.value.trained and self.value_continues:
            run = self.paths.phase_run_name(state.phase, "value")
            data = relative_data(directory / "value", self.paths.data_root / "value")
            config = self.stage_config(state.phase, "value", self.config.training.value, data, value)
            jobs.append(
                self.run_training(
                    state.phase,
                    "value",
                    self.config.training.value,
                    f"python experiments/phase3_value.py --config {config} --run-name {run}",
                )
            )
            value = str(self.checkpoints / run / "adapter")
        elif state.data.value.trained:
            self.log("Value training cannot start from an adapter yet: the value model stays as published")
        await asyncio.gather(*jobs)
        return policy, value

    def stage_config(self, phase: int, name: str, stage: TrainingStage, data: str, initial_adapter: str) -> Path:
        """The stage's template with the phase's data (relative to where its script reads data) and adapter."""
        path = self.paths.phase_data(phase) / f"{name}.toml"
        template = (REPOSITORY_DIRECTORY / stage.config).read_text(encoding="utf-8")
        settings = policy_settings(self.config.search.thinking) if name == "policy" else NO_SETTINGS
        path.write_text(training_config_text(template, data, initial_adapter, settings), encoding="utf-8")
        return path

    async def run_training(self, phase: int, name: str, stage: TrainingStage, command: str) -> None:
        log_path = self.paths.directory / "training" / f"phase_{phase:04d}_{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ | {"CUDA_VISIBLE_DEVICES": str(stage.gpu)}
        # The service runs pinned and niced (deployment/background.sh); training ranks feed a GPU and run unpinned.
        unpinned = f"taskset --cpu-list 0-{os.cpu_count() - 1} {command}"
        with log_path.open("a", encoding="utf-8") as log_file:
            process = await asyncio.create_subprocess_exec(
                "bash", "-c", unpinned, cwd=REPOSITORY_DIRECTORY, env=environment, stdout=log_file, stderr=log_file
            )
            if await process.wait():
                raise RuntimeError(f"{name} training for phase {phase} failed; see {log_path}")

    def publish(self, state: PhaseState) -> None:
        if read_current(self.paths).version >= state.phase:
            return
        version = self.publisher.prepare(
            ModelVersion(state.phase, state.policy_adapter, state.value_adapter, now(), state.trigger)
        )
        record_published(self.paths, version)
