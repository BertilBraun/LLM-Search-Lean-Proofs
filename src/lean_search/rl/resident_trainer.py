"""The ranks of the persistent training job (experiments/grpo_trainer.py; rl/README.md, "Persistent trainer").

Each rank builds the policy and value models once (`training/resident.py`), parked in host memory between phases, and
then follows the loop's commands (`trainer_channel.py`). A `prepare` at the start of a phase's sampling builds the
models the phase needs and starts the main rank reading and labelling the phase's trees as they arrive, one thread on
the background CPUs; a `train` at the pause finishes that, sends the sequences to the other ranks and runs the phase as
`training_phase.run_training_phase` does, with the resident models: the policy, the value model with its gate, and the
merges of the new adapters, which go to host memory (`HostDirectories.handoff`) for the servers to load. Between
commands the ranks only poll, so no collective waits; they exit when the loop's process is gone.
"""

import dataclasses
import os
import threading
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import torch
import transformers

from lean_search.policy.adapters import MergeSeconds, PremergedWeights, handoff_directory
from lean_search.reasoning.dataset import ReasoningExample
from lean_search.rl.loop_services import running_start_ticks
from lean_search.rl.policy_data import PolicyDataParts, PolicyTokenizer, combined_policy_data
from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommand, TrainerCommandKind, TrainerReply
from lean_search.rl.training_phase import (
    PhaseInputs,
    PhaseOutcome,
    TrainingPhaseConfig,
    TrainingStage,
    ValueOutcome,
    append_json_line,
    compiled_graphs,
    label_value_trees,
    prepare_policy_tree,
    released_memory,
    train_policy_data,
    train_value_phase,
    trainer_timings,
)
from lean_search.search import read_tree
from lean_search.search.records import from_json_object, to_json
from lean_search.training.data_parallel import Ranks, broadcast_from_main, largest
from lean_search.training.math_data import MathSolution
from lean_search.training.resident import HostDirectories, ResidentModel, build_resident_model
from lean_search.value.benchmark import LabelledTree, read_benchmark
from lean_search.value.graph_trainer import value_initial_adapter
from lean_search.value.labels import ValueExample

POLL_SECONDS = 0.5
PREPARATION_POLL_SECONDS = 30.0
TREE_PATTERN = "*.json.gz"
# deployment/background.sh's default: CPU-heavy work shares the last this many logical CPUs with the Lean REPLs.
DEFAULT_BACKGROUND_CPUS = 32
BACKGROUND_NICENESS = 19


TokenizerLoader = Callable[[str], transformers.PreTrainedTokenizerBase]


class ModelKind(StrEnum):
    POLICY = "policy"
    VALUE = "value"


@dataclass(frozen=True)
class LoopProcess:
    process_id: int
    start_ticks: int

    def alive(self) -> bool:
        return running_start_ticks(self.process_id) == self.start_ticks


@dataclass(frozen=True)
class ResidentInputs:
    """What every phase reads, loaded once: the replay data, and the value benchmark's path (read per value phase on
    the main rank, which alone scores the gate)."""

    lean_replay: Sequence[ReasoningExample] = ()
    math_replay: Sequence[MathSolution] = ()
    # Only the main rank's, which builds the value data.
    value_replay: Sequence[ValueExample] = ()
    value_benchmark: Path | None = None


@dataclass(frozen=True)
class Merge:
    kind: ModelKind
    weights: PremergedWeights


def parse_phase_config(text: str) -> TrainingPhaseConfig:
    return from_json_object(TrainingPhaseConfig, tomllib.loads(text))


def background_cpus() -> set[int]:
    """The last BACKGROUND_CPUS logical CPUs, where deployment/background.sh pins CPU-heavy work (CPU budget)."""
    count = os.cpu_count() or 1
    background = int(os.environ.get("BACKGROUND_CPUS", str(DEFAULT_BACKGROUND_CPUS)))
    return set(range(max(0, count - background), count))


def run_in_background() -> None:
    """The calling thread on the background CPUs at nice 19, as the Lean REPLs it shares them with."""
    thread = threading.get_native_id()
    os.sched_setaffinity(thread, background_cpus())
    os.setpriority(os.PRIO_PROCESS, thread, BACKGROUND_NICENESS)


class PhasePreparation:
    """The phase's trees turned into policy sequences one by one while the searches run, by a thread of its own; the
    records themselves are not kept."""

    def __init__(self, directory: Path, config_text: str, tokenizer: PolicyTokenizer) -> None:
        self.directory = directory
        self.config_text = config_text
        self.config = parse_phase_config(config_text)
        assert self.config.policy is not None
        self.tokenizer = tokenizer
        self.parts: dict[Path, PolicyDataParts] = {}
        self.finishing = threading.Event()
        self.cancelled = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self.run, name="phase-preparation", daemon=True)
        self.thread.start()

    def matches(self, directory: Path, config_text: str) -> bool:
        return (directory, config_text) == (self.directory, self.config_text)

    def run(self) -> None:
        try:
            run_in_background()
            while True:
                finishing = self.finishing.is_set()
                self.prepare_new()
                if finishing or self.cancelled.is_set():
                    return
                self.finishing.wait(PREPARATION_POLL_SECONDS)
        except BaseException as error:
            self.error = error

    def prepare_new(self) -> None:
        assert self.config.policy is not None
        for path in sorted(self.directory.glob(TREE_PATTERN)):
            if self.cancelled.is_set():
                return
            if path not in self.parts:
                record = read_tree(path)
                self.parts[path] = prepare_policy_tree(record, self.config, self.tokenizer, self.config.policy.data)

    def finish(self) -> list[PolicyDataParts]:
        """Every tree of the directory now, in file order (the order the per-phase job reads them in)."""
        self.finishing.set()
        self.thread.join()
        if self.error is not None:
            raise self.error
        return [self.parts[path] for path in sorted(self.parts)]

    def cancel(self) -> None:
        self.cancelled.set()
        self.finishing.set()
        self.thread.join()


class TrainerRank:
    def __init__(
        self,
        channel: TrainerChannel,
        host: HostDirectories,
        inputs: ResidentInputs,
        device: torch.device,
        ranks: Ranks,
        loop_process: LoopProcess,
        log: Callable[[str], None],
        load_tokenizer: TokenizerLoader = transformers.AutoTokenizer.from_pretrained,
    ) -> None:
        self.channel = channel
        self.host = host
        self.inputs = inputs
        self.device = device
        self.ranks = ranks
        self.loop_process = loop_process
        self.log = log
        self.load_tokenizer = load_tokenizer
        self.models: dict[ModelKind, ResidentModel] = {}
        self.tokenizers: dict[ModelKind, transformers.PreTrainedTokenizerBase] = {}
        self.preparation: PhasePreparation | None = None

    def serve(self) -> None:
        handled = 0
        try:
            while True:
                command = self.channel.command_after(handled)
                if command is None:
                    if not self.loop_process.alive():
                        self.log(f"The loop (process {self.loop_process.process_id}) is gone; stopping")
                        return
                    time.sleep(POLL_SECONDS)
                    continue
                handled = command.sequence
                match command.kind:
                    case TrainerCommandKind.PREPARE:
                        self.prepare(command)
                    case TrainerCommandKind.TRAIN:
                        self.train(command)
                    case TrainerCommandKind.STOP:
                        self.log("Stopping on the loop's request")
                        return
        finally:
            if self.preparation is not None:
                self.preparation.cancel()

    def ensure_models(self, config: TrainingPhaseConfig) -> None:
        """Builds the resident models the phase needs that this job has not built yet (every rank together)."""
        parked = self.host.parked
        if config.policy is not None and ModelKind.POLICY not in self.models:
            policy = config.policy
            started = time.perf_counter()
            self.tokenizers[ModelKind.POLICY] = self.load_tokenizer(policy.model)
            self.models[ModelKind.POLICY] = build_resident_model(
                policy.model,
                policy.optimization,
                policy.lora,
                policy.initial_adapter,
                parked / f"{ModelKind.POLICY}.bin",
                self.device,
                self.ranks,
            )
            self.log(f"Policy {policy.model} resident after {time.perf_counter() - started:.0f} s")
        if config.value is not None and ModelKind.VALUE not in self.models:
            value = config.value
            started = time.perf_counter()
            self.tokenizers[ModelKind.VALUE] = self.load_tokenizer(value.model)
            self.models[ModelKind.VALUE] = build_resident_model(
                value.model,
                value.optimization,
                value.lora,
                value_initial_adapter(value),
                parked / f"{ModelKind.VALUE}.bin",
                self.device,
                self.ranks,
            )
            self.log(f"Value model {value.model} resident after {time.perf_counter() - started:.0f} s")

    def start_preparation(self, trees: Path, config_text: str) -> PhasePreparation:
        """The phase's preparation, kept if it is this phase's with this config, else started afresh."""
        if self.preparation is not None and self.preparation.matches(trees, config_text):
            return self.preparation
        if self.preparation is not None:
            self.preparation.cancel()
        self.preparation = PhasePreparation(trees, config_text, self.tokenizers[ModelKind.POLICY])
        return self.preparation

    def prepare(self, command: TrainerCommand) -> None:
        config_text = Path(command.config).read_text(encoding="utf-8")
        self.ensure_models(parse_phase_config(config_text))
        if self.ranks.is_main:
            self.start_preparation(Path(command.trees), config_text)
            self.log(f"Preparing phase {command.phase} from {command.trees}")

    def value_window(
        self, command: TrainerCommand, config: TrainingPhaseConfig
    ) -> tuple[list[LabelledTree], list[LabelledTree]]:
        """The window's trees labelled (without texts), and those of the phase itself among them."""
        window: list[LabelledTree] = []
        phase_trees: list[LabelledTree] = []
        for directory in command.value_trees or (command.trees,):
            records = [read_tree(path, texts=False) for path in sorted(Path(directory).glob(TREE_PATTERN))]
            labelled = list(label_value_trees(records, config))
            window += labelled
            if directory == command.trees:
                phase_trees = labelled
        return window, phase_trees

    def merge(self, merges: Sequence[Merge]) -> tuple[float, float]:
        """Each new adapter merged on one rank's GPU (in turn) into host memory; the slowest rank's merging and
        writing seconds."""
        merge_seconds = handoff_seconds = 0.0
        for index, merge in enumerate(merges):
            if index % self.ranks.world_size == self.ranks.rank:
                directory = handoff_directory(self.host.handoff, merge.weights.adapter)
                merging, writing = self.models[merge.kind].write_merged(merge.weights, directory)
                merge_seconds += merging
                handoff_seconds += writing
        return largest(merge_seconds, self.device, self.ranks), largest(handoff_seconds, self.device, self.ranks)

    def train(self, command: TrainerCommand) -> None:
        started = time.perf_counter()
        graphs_before = compiled_graphs()
        config_text = Path(command.config).read_text(encoding="utf-8")
        config = parse_phase_config(config_text)
        assert config.policy is not None
        self.ensure_models(config)
        built = time.perf_counter()
        for model in self.models.values():
            model.reset_seconds()
        parts = None
        if self.ranks.is_main:
            parts = self.start_preparation(Path(command.trees), config_text).finish()
            self.preparation = None
        parts = broadcast_from_main(parts, self.ranks)
        assert parts is not None
        data = combined_policy_data(parts)
        preparation_seconds = time.perf_counter() - built
        output = Path(command.output_directory)
        output.mkdir(parents=True, exist_ok=True)
        memory = [released_memory(TrainingStage.LABELLING, self.device, self.ranks)]
        inputs = PhaseInputs(
            records=(),
            lean_replay=self.inputs.lean_replay,
            math_replay=self.inputs.math_replay,
            value_replay=self.inputs.value_replay,
        )
        policy_model = self.models[ModelKind.POLICY]
        directory = output / "policy"
        policy = train_policy_data(
            config,
            config.policy,
            data,
            0.0,
            inputs,
            self.tokenizers[ModelKind.POLICY],
            self.device,
            directory,
            lambda record: append_json_line(directory / "steps.jsonl", record),
            self.ranks,
            policy_model.trainable,
        )
        policy_model.park()
        memory.append(released_memory(TrainingStage.POLICY, self.device, self.ranks))
        merges = [Merge(ModelKind.POLICY, PremergedWeights(config.policy.model, policy.adapter))]
        value = None
        if config.value is not None:
            value, window_seconds = self.train_value(command, config, inputs, output / "value")
            preparation_seconds += window_seconds
            if broadcast_from_main(value.accepted, self.ranks):
                merges.append(Merge(ModelKind.VALUE, PremergedWeights(config.value.model, value.adapter)))
            memory.append(released_memory(TrainingStage.VALUE, self.device, self.ranks))
        merge_seconds, handoff_seconds = self.merge(merges)
        memory.append(released_memory(TrainingStage.MERGE, self.device, self.ranks))
        timings = trainer_timings(preparation_seconds, policy, value, MergeSeconds(), time.perf_counter() - started)
        unpark_seconds = sum(model.unpark_seconds for model in self.models.values())
        park_seconds = sum(model.park_seconds for model in self.models.values())
        timings = dataclasses.replace(
            timings,
            merge_seconds=merge_seconds,
            build_seconds=built - started,
            unpark_seconds=largest(unpark_seconds, self.device, self.ranks),
            park_seconds=largest(park_seconds, self.device, self.ranks),
            handoff_seconds=handoff_seconds,
            compiled_graphs=compiled_graphs() - graphs_before,
        )
        groups = sum(len(part.groups) for part in parts)
        outcome = PhaseOutcome(len(parts), groups, policy, value, timings, tuple(memory))
        if self.ranks.is_main:
            (output / "phase.json").write_text(to_json(outcome), encoding="utf-8")
            self.channel.answer(TrainerReply(command.sequence, command.phase))
            self.log(
                f"Phase {command.phase}: {outcome.trees} trees, {outcome.groups} groups, "
                f"{timings.total_seconds:.0f} s, {timings.compiled_graphs} graphs compiled"
            )

    def train_value(
        self, command: TrainerCommand, config: TrainingPhaseConfig, inputs: PhaseInputs, directory: Path
    ) -> tuple[ValueOutcome, float]:
        """The value model on the window (read and labelled by the main rank now: it spans finished phases' trees
        without texts); the outcome and the seconds the window took."""
        assert config.value is not None
        started = time.perf_counter()
        window: Sequence[LabelledTree] = ()
        phase_trees: Sequence[LabelledTree] = ()
        if self.ranks.is_main:
            window, phase_trees = self.value_window(command, config)
            benchmark = self.inputs.value_benchmark
            inputs = dataclasses.replace(inputs, value_benchmark=read_benchmark(benchmark) if benchmark else None)
        window_seconds = time.perf_counter() - started
        tokenizer = self.tokenizers[ModelKind.VALUE]
        value_model = self.models[ModelKind.VALUE]
        value = train_value_phase(
            config,
            config.value,
            window,
            phase_trees,
            inputs,
            tokenizer,
            tokenizer.pad_token_id,
            self.device,
            directory,
            lambda record: append_json_line(directory / "steps.jsonl", record),
            self.ranks,
            value_model.trainable,
        )
        value_model.park()
        return value, window_seconds
