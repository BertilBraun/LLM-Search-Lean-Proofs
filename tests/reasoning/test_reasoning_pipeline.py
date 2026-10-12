from collections.abc import Sequence
from pathlib import Path

from reasoning_records import execution, proof_steps, sample_record, state_record

from lean_search.reasoning.pipeline import ChunkProgress, distinct_blocks, run_chunks, with_value_drops
from lean_search.reasoning.records import (
    BlockExecution,
    RunDirectory,
    StateRecord,
    StateSamples,
    read_records,
    write_records,
)
from lean_search.reasoning.reward import StepOutcome
from lean_search.reasoning.states import ReasoningState, proof_states


def test_records_survive_a_json_round_trip(tmp_path: Path) -> None:
    record = state_record(
        [sample_record(0, "omega"), sample_record(1, None, parse_failure=StepOutcome.TRUNCATED)],
        [execution("omega", StepOutcome.CLOSED)],
    )
    write_records(tmp_path / "records.jsonl", [record])
    assert read_records(tmp_path / "records.jsonl", StateRecord) == [record]


def test_distinct_blocks_keep_the_first_occurrence_order() -> None:
    record = state_record([sample_record(0, "simp"), sample_record(1, "omega"), sample_record(2, "simp")], [])
    assert distinct_blocks(record.sampled) == ["simp", "omega"]


class CountingSampler:
    def __init__(self) -> None:
        self.calls = 0

    async def sample(self, state: ReasoningState) -> StateSamples:
        self.calls += 1
        return state_record([sample_record(0, "omega")], [], state).sampled


async def execute_without_lean(sampled: Sequence[StateSamples]) -> list[StateRecord]:
    return [StateRecord(entry, "", (execution("omega", StepOutcome.CLOSED),)) for entry in sampled]


def states(count: int) -> list[ReasoningState]:
    return [state for number in range(count) for state in proof_states(proof_steps(proof=f"test/{number}"))][:count]


async def run(directory: RunDirectory, sampler: CountingSampler, state_count: int) -> list[ChunkProgress]:
    progress: list[ChunkProgress] = []
    await run_chunks(directory, states(state_count), 2, sampler.sample, execute_without_lean, progress.append)
    return progress


async def test_every_state_gets_a_record_in_its_chunk(tmp_path: Path) -> None:
    directory = RunDirectory(tmp_path)
    await run(directory, CountingSampler(), 5)
    assert [len(read_records(directory.chunk_records(chunk), StateRecord)) for chunk in range(3)] == [2, 2, 1]


async def test_a_finished_run_samples_nothing_again(tmp_path: Path) -> None:
    directory = RunDirectory(tmp_path)
    await run(directory, CountingSampler(), 5)
    sampler = CountingSampler()
    await run(directory, sampler, 5)
    assert sampler.calls == 0


async def test_a_chunk_with_samples_but_no_records_is_executed_without_resampling(tmp_path: Path) -> None:
    directory = RunDirectory(tmp_path)
    await run(directory, CountingSampler(), 4)
    directory.chunk_records(1).unlink()
    sampler = CountingSampler()
    progress = await run(directory, sampler, 4)
    assert (sampler.calls, [entry.chunk for entry in progress]) == (0, [1])


async def test_run_records_cover_the_states_in_order(tmp_path: Path) -> None:
    directory = RunDirectory(tmp_path)
    await run(directory, CountingSampler(), 3)
    identifiers = [record.sampled.state.identifier for record in directory.read_all_records()]
    assert identifiers == [state.identifier for state in states(3)]


async def goal_count_steps(goals: Sequence[str]) -> float:
    return float(len(goals) * 3)


async def test_value_drops_are_set_on_executions_that_changed_the_goals() -> None:
    progress = BlockExecution("subst h₁", StepOutcome.PROGRESS, 0, 1, 1, (), 0.1, "")
    record = state_record([sample_record(0, "subst h₁")], [progress])
    scored = await with_value_drops(record, goal_count_steps)
    assert [execution.value_drop for execution in scored.executions] == [3.0]


async def test_failed_executions_get_no_value_drop() -> None:
    record = state_record([sample_record(0, "simp")], [execution("simp", StepOutcome.ERROR)])
    scored = await with_value_drops(record, goal_count_steps)
    assert [execution.value_drop for execution in scored.executions] == [None]
