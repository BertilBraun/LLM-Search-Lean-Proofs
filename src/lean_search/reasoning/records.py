"""Per-state records of a reasoning run (samples, Lean executions) and their chunked, resumable storage."""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.reasoning.reward import RewardConfig, StepOutcome, is_success
from lean_search.reasoning.states import ReasoningState
from lean_search.search.records import from_json_object, to_json


@dataclass(frozen=True)
class SampleRecord:
    index: int
    text: str
    finish_reason: str
    generated_tokens: int
    cumulative_logprob: float
    reasoning: str
    reasoning_tokens: int
    tactic_block: str | None
    # TRUNCATED, NO_BLOCK, EMPTY or FORBIDDEN when the sample has no usable block.
    parse_failure: StepOutcome | None


@dataclass(frozen=True)
class StateSamples:
    state: ReasoningState
    thinking: bool
    # The addition to the system prompt in thinking mode (`render_prompt`'s `thinking_instruction`).
    thinking_instruction: str
    prompt_tokens: int
    cached_prompt_tokens: int
    max_tokens: int
    seconds: float
    # Empty when the prompt leaves too little of the context for a completion.
    samples: tuple[SampleRecord, ...]


@dataclass(frozen=True)
class BlockExecution:
    tactic_block: str
    outcome: StepOutcome
    reference_steps_advanced: int
    applied_tactics: int
    total_tactics: int
    goals_after: tuple[str, ...]
    lean_seconds: float
    message: str
    # h(before) - h(after) from the value model, only with RewardConfig.value_progress.
    value_drop: float | None = None


@dataclass(frozen=True)
class StateRecord:
    sampled: StateSamples
    # Why the state could not be rebuilt in Lean; its samples are then not scored.
    start_failure: str
    executions: tuple[BlockExecution, ...]

    @property
    def usable(self) -> bool:
        return not self.start_failure and bool(self.sampled.samples)


@dataclass(frozen=True)
class ScoredSample:
    sample: SampleRecord
    outcome: StepOutcome
    reference_steps_advanced: int
    success: bool


def scored_samples(record: StateRecord, config: RewardConfig) -> list[ScoredSample]:
    executions = {execution.tactic_block: execution for execution in record.executions}
    scored = []
    for sample in record.sampled.samples:
        if sample.parse_failure is not None:
            scored.append(ScoredSample(sample, sample.parse_failure, 0, False))
            continue
        assert sample.tactic_block is not None
        execution = executions[sample.tactic_block]
        success = is_success(execution.outcome, execution.reference_steps_advanced, execution.value_drop, config)
        scored.append(ScoredSample(sample, execution.outcome, execution.reference_steps_advanced, success))
    return scored


def write_records(path: Path, records: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(to_json(record) + "\n")
    temporary.replace(path)


def read_records[T](path: Path, record_type: type[T]) -> list[T]:
    with path.open(encoding="utf-8") as lines:
        return [from_json_object(record_type, json.loads(line)) for line in lines if line.strip()]


@dataclass(frozen=True)
class RunDirectory:
    path: Path

    @property
    def states(self) -> Path:
        return self.path / "states.jsonl"

    @property
    def summary(self) -> Path:
        return self.path / "summary"

    def chunk_samples(self, chunk: int) -> Path:
        return self.path / "chunks" / f"{chunk:05d}.samples.jsonl"

    def chunk_records(self, chunk: int) -> Path:
        return self.path / "chunks" / f"{chunk:05d}.records.jsonl"

    def completed_chunks(self) -> list[int]:
        return sorted(int(path.name.split(".")[0]) for path in (self.path / "chunks").glob("*.records.jsonl"))

    def read_all_records(self) -> list[StateRecord]:
        return [
            record
            for chunk in self.completed_chunks()
            for record in read_records(self.chunk_records(chunk), StateRecord)
        ]


def chunks[T](items: Sequence[T], chunk_size: int) -> list[Sequence[T]]:
    return [items[start : start + chunk_size] for start in range(0, len(items), chunk_size)]
