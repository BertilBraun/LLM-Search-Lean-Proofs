import random
from pathlib import Path

import pytest

from lean_search.expert_iteration.loop_config import BufferConfig
from lean_search.expert_iteration.replay_buffer import (
    FifoBuffer,
    SampleOrigin,
    ValueSample,
    adapted_capacity,
    phase_statistics,
    read_buffer_items,
    trained_count,
    updated_inflow,
    write_buffer,
)
from lean_search.value.labels import LabelKind, ValueExample


def sample(origin: SampleOrigin, number: int, phase: int = 1) -> ValueSample:
    return ValueSample(origin, phase, ValueExample((f"⊢ {number}",), LabelKind.EXACT, 1, 1.0, "s", f"p{number}", 0))


def search_samples(numbers: range, phase: int = 1) -> list[ValueSample]:
    return [sample(SampleOrigin.SEARCH, number, phase) for number in numbers]


def dataset_samples(count: int) -> list[ValueSample]:
    return [sample(SampleOrigin.DATASET, -number - 1, 0) for number in range(count)]


def test_search_samples_push_out_dataset_samples_first() -> None:
    buffer = FifoBuffer(10, dataset_samples(10))
    buffer.add(search_samples(range(4)))
    assert (len(buffer.dataset), len(buffer.search)) == (6, 4)


def test_old_search_samples_leave_once_the_dataset_is_gone() -> None:
    buffer = FifoBuffer(4, dataset_samples(2))
    buffer.add(search_samples(range(3)))
    buffer.add(search_samples(range(3, 5)))
    assert [item.example.identifier for item in buffer.search] == ["p1", "p2", "p3", "p4"]


def test_add_reports_what_it_evicted() -> None:
    buffer = FifoBuffer(4, dataset_samples(3))
    assert buffer.add(search_samples(range(3))) == (2, 0)


@pytest.mark.parametrize(("count", "unique"), [(5, 5), (25, 10)])
def test_sampling_draws_every_item_before_repeating_one(count: int, unique: int) -> None:
    buffer = FifoBuffer(10, search_samples(range(10)))
    drawn = buffer.sample(count, random.Random(0))
    assert (len(drawn), len({item.example.identifier for item in drawn})) == (count, unique)


def test_a_phase_trains_reuse_times_its_new_samples() -> None:
    assert trained_count(1200, 1.0) == 1200


@pytest.mark.parametrize(("average", "added", "inflow"), [(None, 1000, 1000.0), (1000.0, 2000, 1500.0)])
def test_the_inflow_is_a_moving_average(average: float | None, added: int, inflow: float) -> None:
    assert updated_inflow(average, added) == inflow


@pytest.mark.parametrize(("inflow", "capacity"), [(None, 10000), (2000.0, 7000), (100.0, 2000)])
def test_the_capacity_follows_the_inflow(inflow: float | None, capacity: int) -> None:
    config = BufferConfig(initial_capacity=10000, minimum_capacity=2000, capacity_phases=3.5)
    assert adapted_capacity(config, inflow) == capacity


def test_statistics_report_the_actual_reuse_and_dataset_share() -> None:
    buffer = FifoBuffer(10, dataset_samples(6))
    new = search_samples(range(4))
    evicted = buffer.add(new)
    trained = [*new, *new]
    statistics = phase_statistics("value", buffer, 4.0, len(new), evicted, trained)
    assert (statistics.reuse, statistics.dataset_share, statistics.trained_dataset_share) == (2.0, 0.6, 0.0)


def test_a_buffer_reads_back_in_order(tmp_path: Path) -> None:
    buffer = FifoBuffer(10, [*dataset_samples(2), *search_samples(range(3))])
    write_buffer(tmp_path / "value.jsonl", buffer)
    assert list(read_buffer_items(tmp_path / "value.jsonl", ValueSample)) == buffer.items()
