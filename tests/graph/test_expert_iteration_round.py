"""An expert-iteration round in the persistent training job, on the CPU with a tiny model: on the resident policy it
trains what a freshly loaded model trains and what the hand-run round's trainer trains (one rank and two), it validates
and measures its step, it trains only when its data fills an optimizer step, and in a phase it continues the GRPO
update when one ran (arm D) or the published adapter (arm C), with one policy merge for the phase."""

import dataclasses
import functools
import math
import os
from pathlib import Path

import pytest
from test_data_parallel_trainers import Runs, adapter_difference, on_ranks
from test_resident_trainer import (
    CPU,
    LORA,
    OPTIMIZATION,
    adapter_weights,
    merged_weights,
    phase_config,
    phase_tree,
    same_tensors,
    without_none,
    write_trees,
)
from tiny_models import CharacterTokenizer, save_tiny_model

torch = pytest.importorskip("torch")

from lean_search.expert_iteration.toml_text import toml_text  # noqa: E402
from lean_search.policy.adapters import create_zero_adapter, handoff_directory, read_premerged  # noqa: E402
from lean_search.reasoning.dataset import ReasoningExample, ReasoningOrigin, write_examples  # noqa: E402
from lean_search.rl.expert_iteration_data import (  # noqa: E402
    ExpertIterationConfig,
    ExpertIterationDataConfig,
    ProofGraphCompletion,
    ReplayConfig,
    write_completions,
)
from lean_search.rl.expert_iteration_training import (  # noqa: E402
    ExpertIterationResult,
    adapter_change,
    round_training_data,
    train_expert_iteration,
)
from lean_search.rl.loop import read_phase_outcome  # noqa: E402
from lean_search.rl.loop_services import running_start_ticks  # noqa: E402
from lean_search.rl.resident_trainer import LoopProcess, ResidentInputs, TrainerRank  # noqa: E402
from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommand, TrainerCommandKind  # noqa: E402
from lean_search.rl.training_phase import (  # noqa: E402
    PhaseInputs,
    PhaseOutcome,
    TrainingPhaseConfig,
    run_training_phase,
)
from lean_search.training.data_parallel import SINGLE_PROCESS, Ranks  # noqa: E402
from lean_search.training.math_data import MathSolution, write_solutions  # noqa: E402
from lean_search.training.resident import HostDirectories, build_resident_model  # noqa: E402
from lean_search.training.sft import (  # noqa: E402
    DistributedContext,
    EvaluationConfig,
    SftConfig,
    StepRecord,
    load_trainable_model,
    plan_steps,
)
from lean_search.training.sft import train as sft_train  # noqa: E402
from lean_search.training.sft_data import SftExample, TokenizedExample  # noqa: E402

GOALS = ("⊢ p",)
# Four micro-batches of one or two examples: a few optimizer steps.
ROUND_OPTIMIZATION = dataclasses.replace(
    OPTIMIZATION, warmup_fraction=0.0, micro_batch_tokens=400, micro_batches_per_step=1, epochs=1
)


def completion(number: int, statement: str) -> ProofGraphCompletion:
    """A verified block as the build writes it: the recorded prompt's ids and the sampled completion's."""
    prompt = tuple(ord(character) for character in f"<|im_start|>user\n{statement}<|im_end|>\n<|im_start|>assistant\n")
    block = f"Idea {number}.\n\n```lean\nexact h{number}\n```<|im_end|>"
    example = SftExample("expert_iteration", f"{statement}#{number}", number, GOALS, f"exact h{number}")
    tokenized = TokenizedExample(example, prompt + tuple(ord(character) for character in block), len(prompt))
    return ProofGraphCompletion(
        problem_name=statement,
        goals=GOALS,
        block=f"exact h{number}",
        tokenized=tokenized,
        policy_version=1,
        tactics=1,
        explanation_characters=7,
        ended_turn=True,
        easy=False,
        on_root_route=True,
        prompt_like_replay=True,
        below_band=False,
    )


def round_files(root: Path, validation_examples: int = 2) -> Path:
    """A build directory of six training and some validation examples, and the replay files under `root`."""
    directory = root / "round"
    write_completions(directory / "train.jsonl", [completion(number, f"s{number % 3}") for number in range(6)])
    write_completions(
        directory / "validation.jsonl", [completion(number, "v") for number in range(validation_examples)]
    )
    reasoning = [
        ReasoningExample("replay", f"proof{number}", 0, GOALS, "simp", "Idea.", "", ReasoningOrigin.SAMPLED, True)
        for number in range(8)
    ]
    write_examples(root / "lean.jsonl", reasoning)
    write_examples(root / "lean_validation.jsonl", reasoning[:3])
    write_solutions(root / "math.jsonl", [MathSolution("math", str(number), "1 + 1?", "2") for number in range(8)])
    return directory


def round_config(model: Path, directory: Path, initial_adapter: str) -> ExpertIterationConfig:
    return ExpertIterationConfig(
        run_name="round",
        data=ExpertIterationDataConfig(loop="loop", last_phase=1, window_phases=1),
        replay=ReplayConfig("lean.jsonl", "math.jsonl", validation="lean_validation.jsonl", validation_examples=3),
        sft=SftConfig(
            model=str(model),
            data=str(directory),
            lora=LORA,
            optimization=ROUND_OPTIMIZATION,
            evaluation=EvaluationConfig(micro_batch_tokens=65536, generation_examples=0),
            merge=False,
            initial_adapter=initial_adapter,
        ),
    )


@dataclasses.dataclass(frozen=True)
class Rounds:
    root: Path
    model: Path
    start: Path
    config: ExpertIterationConfig
    fresh: ExpertIterationResult
    resident: ExpertIterationResult
    steps: list[StepRecord]


def train_round(config: ExpertIterationConfig, root: Path, output: Path) -> ExpertIterationResult:
    """The round on a freshly loaded model."""
    data = round_training_data(CharacterTokenizer(), config, root)
    return train_expert_iteration(config.sft, data, 0, CPU, output, lambda record: None)


@pytest.fixture(scope="module")
def rounds(tmp_path_factory: pytest.TempPathFactory) -> Rounds:
    """The same round on a freshly loaded model and on a resident one."""
    root = tmp_path_factory.mktemp("rounds")
    model = save_tiny_model(root / "model")
    start = root / "start"
    create_zero_adapter(str(model), start, LORA.rank)
    config = round_config(model, round_files(root), str(start))
    steps: list[StepRecord] = []
    data = round_training_data(CharacterTokenizer(), config, root)
    fresh = train_expert_iteration(
        config.sft, data, 0, CPU, root / "fresh", steps.append, SINGLE_PROCESS, load_trainable_model
    )
    resident_model = build_resident_model(
        str(model), ROUND_OPTIMIZATION, LORA, str(start), root / "host" / "policy.bin", CPU, SINGLE_PROCESS
    )
    resident = train_expert_iteration(
        config.sft, data, 0, CPU, root / "resident", lambda record: None, SINGLE_PROCESS, resident_model.trainable
    )
    return Rounds(root, model, start, config, fresh, resident, steps)


def test_a_round_on_the_resident_policy_trains_the_adapter_a_freshly_loaded_model_trains(rounds: Rounds) -> None:
    assert same_tensors(adapter_weights(str(rounds.root / "fresh")), adapter_weights(str(rounds.root / "resident")))


def test_a_round_takes_several_optimizer_steps(rounds: Rounds) -> None:
    assert rounds.fresh.steps > 2


def test_a_round_reports_each_step(rounds: Rounds) -> None:
    assert [record.step for record in rounds.steps] == list(range(1, rounds.fresh.steps + 1))


def test_a_round_validates_at_the_start_halfway_and_the_end(rounds: Rounds) -> None:
    steps = rounds.fresh.steps
    assert [point.step for point in rounds.fresh.curve] == [0, math.ceil(steps / 2), steps]


def test_a_rounds_parameter_change_is_the_change_between_its_adapters(rounds: Rounds) -> None:
    change = adapter_change(rounds.start, rounds.root / "fresh")
    assert rounds.fresh.parameter_change is not None
    assert rounds.fresh.parameter_change.norm == pytest.approx(change.norm, rel=1e-5)


def test_a_round_moves_the_adapter(rounds: Rounds) -> None:
    assert rounds.fresh.parameter_change is not None and rounds.fresh.parameter_change.norm > 0


def test_a_round_reports_the_replay_losss_change(rounds: Rounds) -> None:
    first, last = rounds.fresh.curve[0].replay_loss, rounds.fresh.curve[-1].replay_loss
    assert first is not None and last is not None
    assert rounds.fresh.replay_loss_change == pytest.approx(last / first - 1)


def test_a_round_counts_its_trained_tokens_as_the_completion_tokens(rounds: Rounds) -> None:
    data = round_training_data(CharacterTokenizer(), rounds.config, rounds.root)
    planned = sum(example.completion_token_count for example in data.train)
    assert 0 < rounds.fresh.trained_tokens <= planned


def test_a_round_without_validation_examples_records_no_round_loss(tmp_path: Path) -> None:
    model = save_tiny_model(tmp_path / "model")
    create_zero_adapter(str(model), tmp_path / "start", LORA.rank)
    config = round_config(model, round_files(tmp_path, validation_examples=0), str(tmp_path / "start"))
    result = train_round(config, tmp_path, tmp_path / "adapter")
    assert {point.expert_iteration_loss for point in result.curve} == {None}


class RoundJob:
    """One rank of the persistent job on the CPU, sent phases with and without a GRPO section and a round."""

    def __init__(self, root: Path, trees: Path, data_root: Path) -> None:
        self.root = root
        self.trees = trees
        self.sequence = 0
        channel = TrainerChannel(root / "channel")
        channel.clear()
        start_ticks = running_start_ticks(os.getpid())
        assert start_ticks is not None
        self.host = HostDirectories(root / "host")
        self.rank = TrainerRank(
            channel,
            self.host,
            ResidentInputs(data_root=data_root),
            CPU,
            SINGLE_PROCESS,
            LoopProcess(os.getpid(), start_ticks),
            print,
            lambda model: CharacterTokenizer(),
        )

    def train(self, phase: int, config: TrainingPhaseConfig, round_path: Path | None) -> PhaseOutcome:
        self.sequence += 1
        config_path = self.root / f"phase_{phase}.toml"
        config_path.write_text(toml_text(without_none(dataclasses.asdict(config))), encoding="utf-8")
        output = self.root / f"phase_{phase}"
        command = TrainerCommand(
            self.sequence,
            TrainerCommandKind.TRAIN,
            phase,
            str(config_path),
            str(self.trees),
            (),
            str(output),
            "" if round_path is None else str(round_path),
        )
        self.rank.train(command)
        return read_phase_outcome(output / "phase.json")


def write_round(path: Path, config: ExpertIterationConfig) -> Path:
    path.write_text(toml_text(dataclasses.asdict(config)), encoding="utf-8")
    return path


@dataclasses.dataclass(frozen=True)
class InterleavedPhase:
    """Arm D's round phase in the persistent job, and the same updates by a fresh GRPO job and a fresh round."""

    root: Path
    model: Path
    start: Path
    outcome: PhaseOutcome
    fresh_grpo: PhaseOutcome
    fresh_round: ExpertIterationResult


@pytest.fixture(scope="module")
def interleaved(tmp_path_factory: pytest.TempPathFactory) -> InterleavedPhase:
    root = tmp_path_factory.mktemp("interleaved")
    model = save_tiny_model(root / "model")
    start = root / "start"
    create_zero_adapter(str(model), start, LORA.rank)
    record = phase_tree()
    trees = write_trees(root / "trees", [record])
    config = round_config(model, round_files(root), str(start))
    round_path = write_round(root / "round.toml", config)
    outcome = RoundJob(root / "job", trees, root).train(1, phase_config(model, str(start)), round_path)
    fresh_grpo = run_training_phase(
        phase_config(model, str(start)),
        PhaseInputs(records=[record]),
        CharacterTokenizer(),
        None,
        CPU,
        root / "fresh_grpo",
    )
    assert fresh_grpo.policy is not None
    continued = dataclasses.replace(
        config, sft=dataclasses.replace(config.sft, initial_adapter=fresh_grpo.policy.adapter)
    )
    fresh_round = train_round(continued, root, root / "fresh_round")
    return InterleavedPhase(root, model, start, outcome, fresh_grpo, fresh_round)


def test_the_interleaved_phases_grpo_update_is_a_grpo_phases(interleaved: InterleavedPhase) -> None:
    resident, fresh = interleaved.outcome.policy, interleaved.fresh_grpo.policy
    assert resident is not None and fresh is not None
    assert same_tensors(adapter_weights(resident.adapter), adapter_weights(fresh.adapter))


def test_the_interleaved_phases_round_continues_its_grpo_update(interleaved: InterleavedPhase) -> None:
    round_outcome = interleaved.outcome.expert_iteration
    assert round_outcome is not None
    fresh = adapter_weights(str(interleaved.root / "fresh_round"))
    assert same_tensors(adapter_weights(round_outcome.adapter), fresh)


def test_the_interleaved_phase_publishes_the_rounds_adapter(interleaved: InterleavedPhase) -> None:
    round_outcome = interleaved.outcome.expert_iteration
    assert round_outcome is not None and interleaved.outcome.policy_adapter() == round_outcome.adapter


def test_the_interleaved_phase_hands_off_one_policy_merge_the_rounds(interleaved: InterleavedPhase) -> None:
    handoff = interleaved.root / "job" / "host" / "handoff"
    merged = [read_premerged(directory) for directory in sorted(handoff.iterdir())]
    round_outcome = interleaved.outcome.expert_iteration
    assert round_outcome is not None
    assert [weights.adapter for weights in merged if weights is not None] == [round_outcome.adapter]


def test_the_interleaved_phase_measures_both_updates_together(interleaved: InterleavedPhase) -> None:
    round_outcome = interleaved.outcome.expert_iteration
    assert round_outcome is not None and round_outcome.phase_parameter_change is not None
    expected = adapter_change(interleaved.start, Path(round_outcome.adapter))
    assert round_outcome.phase_parameter_change.norm == pytest.approx(expected.norm)


@pytest.fixture(scope="module")
def expert_iteration_phase(tmp_path_factory: pytest.TempPathFactory) -> InterleavedPhase:
    """Arm C's phase: no GRPO section, the round continues the published adapter."""
    root = tmp_path_factory.mktemp("expert_iteration_phase")
    model = save_tiny_model(root / "model")
    start = root / "start"
    create_zero_adapter(str(model), start, LORA.rank)
    trees = write_trees(root / "trees", [phase_tree()])
    config = round_config(model, round_files(root), str(start))
    without_grpo = TrainingPhaseConfig()
    outcome = RoundJob(root / "job", trees, root).train(1, without_grpo, write_round(root / "round.toml", config))
    fresh_round = train_round(config, root, root / "fresh_round")
    return InterleavedPhase(root, model, start, outcome, outcome, fresh_round)


def test_a_round_without_grpo_trains_what_a_fresh_round_trains(expert_iteration_phase: InterleavedPhase) -> None:
    round_outcome = expert_iteration_phase.outcome.expert_iteration
    assert round_outcome is not None
    fresh = adapter_weights(str(expert_iteration_phase.root / "fresh_round"))
    assert same_tensors(adapter_weights(round_outcome.adapter), fresh)


def test_a_round_without_grpo_records_no_grpo_update(expert_iteration_phase: InterleavedPhase) -> None:
    assert expert_iteration_phase.outcome.policy is None


def test_a_round_without_grpo_hands_off_its_merge(expert_iteration_phase: InterleavedPhase) -> None:
    round_outcome = expert_iteration_phase.outcome.expert_iteration
    assert round_outcome is not None
    handed_off = handoff_directory(expert_iteration_phase.root / "job" / "host" / "handoff", round_outcome.adapter)
    assert merged_weights(handed_off)


def test_a_phase_with_neither_update_trains_and_merges_nothing(tmp_path: Path) -> None:
    trees = write_trees(tmp_path / "trees", [phase_tree()])
    outcome = RoundJob(tmp_path / "job", trees, tmp_path).train(1, TrainingPhaseConfig(), None)
    assert (outcome.policy_adapter(), (tmp_path / "job" / "host" / "handoff").exists()) == (None, False)


def micro_batch_count(config: ExpertIterationConfig, root: Path) -> int:
    """The round's micro-batches, all of them in steps of one."""
    data = round_training_data(CharacterTokenizer(), config, root)
    optimization = dataclasses.replace(config.sft.optimization, micro_batches_per_step=1)
    return len(plan_steps(data.train, optimization, 1))


@pytest.mark.parametrize(("missing", "trains"), [(0, True), (1, False)], ids=["one full step", "short of one step"])
def test_a_round_trains_only_when_its_data_fills_an_optimizer_step(tmp_path: Path, missing: int, trains: bool) -> None:
    model = save_tiny_model(tmp_path / "model")
    create_zero_adapter(str(model), tmp_path / "start", LORA.rank)
    config = round_config(model, round_files(tmp_path), str(tmp_path / "start"))
    per_step = micro_batch_count(config, tmp_path) + missing
    optimization = dataclasses.replace(config.sft.optimization, micro_batches_per_step=per_step)
    config = dataclasses.replace(config, sft=dataclasses.replace(config.sft, optimization=optimization))
    trees = write_trees(tmp_path / "trees", [phase_tree()])
    job = RoundJob(tmp_path / "job", trees, tmp_path)
    outcome = job.train(1, TrainingPhaseConfig(), write_round(tmp_path / "round.toml", config))
    assert (outcome.expert_iteration is not None) == trains


@dataclasses.dataclass(frozen=True)
class AgainstHandRun:
    """The same round by the hand-run trainer (`training/sft.train`, as `grpo_expert_iteration.py train` runs it) and
    by the loop's (`train_expert_iteration`)."""

    root: Path
    hand_run_steps: list[StepRecord]
    loop_steps: list[StepRecord]


def hand_run_config(config: ExpertIterationConfig) -> SftConfig:
    """Without the hand-run's evaluations, whose greedy generation the character tokenizer cannot run."""
    return dataclasses.replace(config.sft, evaluation=dataclasses.replace(config.sft.evaluation, validation_examples=0))


@pytest.fixture(scope="module")
def against_hand_run(tmp_path_factory: pytest.TempPathFactory) -> AgainstHandRun:
    root = tmp_path_factory.mktemp("against_hand_run")
    model = save_tiny_model(root / "model")
    create_zero_adapter(str(model), root / "start", LORA.rank)
    config = round_config(model, round_files(root), str(root / "start"))
    data = round_training_data(CharacterTokenizer(), config, root)
    hand_run_steps: list[StepRecord] = []
    context = DistributedContext(0, 1, CPU)
    sft_train(
        hand_run_config(config),
        CharacterTokenizer(),
        data.train,
        data.expert_iteration_validation,
        context,
        root / "hand_run",
        hand_run_steps.append,
        lambda record: None,
    )
    loop_steps: list[StepRecord] = []
    train_expert_iteration(config.sft, data, 0, CPU, root / "loop", loop_steps.append)
    return AgainstHandRun(root, hand_run_steps, loop_steps)


def test_the_loops_round_trains_the_adapter_the_hand_run_trainer_trains(against_hand_run: AgainstHandRun) -> None:
    root = against_hand_run.root
    assert same_tensors(adapter_weights(str(root / "hand_run")), adapter_weights(str(root / "loop")))


@pytest.mark.parametrize("field", ["learning_rate", "loss", "gradient_norm", "tokens", "completion_tokens"])
def test_the_loops_round_takes_the_hand_run_trainers_steps(against_hand_run: AgainstHandRun, field: str) -> None:
    hand_run = [getattr(record, field) for record in against_hand_run.hand_run_steps]
    assert [getattr(record, field) for record in against_hand_run.loop_steps] == hand_run


def train_on_ranks(model: Path, root: Path, trainer: str, ranks: Ranks) -> None:
    """One rank of a two-rank round on the CPU: the hand-run trainer's DDP or the loop's gradient sums."""
    config = round_config(model, root / "round", str(root / "start"))
    data = round_training_data(CharacterTokenizer(), config, root)
    output = root / trainer
    if trainer == "hand_run":
        context = DistributedContext(ranks.rank, ranks.world_size, CPU)
        tokenizer = CharacterTokenizer()
        steps: list[StepRecord] = []
        sft_train(hand_run_config(config), tokenizer, data.train, (), context, output, steps.append, print)
    else:
        train_expert_iteration(config.sft, data, 0, CPU, output, lambda record: None, ranks)


@pytest.fixture(scope="module")
def on_two_ranks(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("on_two_ranks")
    model = save_tiny_model(root / "model")
    create_zero_adapter(str(model), root / "start", LORA.rank)
    round_files(root)
    for trainer in ("hand_run", "loop"):
        on_ranks(2, functools.partial(train_on_ranks, model, root, trainer), root / f"rendezvous_{trainer}")
    return root


def test_on_two_ranks_the_loops_round_trains_the_hand_run_trainers_adapter(on_two_ranks: Path) -> None:
    difference = adapter_difference(Runs(on_two_ranks / "hand_run", on_two_ranks / "loop"))
    assert difference < 1e-5
