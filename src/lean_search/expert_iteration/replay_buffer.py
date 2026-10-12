"""Rolling FIFO replay buffers for the training phases, one for the policy and one for the value model.

A buffer starts full of dataset samples (traced proof steps, the v0 value labels), a regularizer. Search samples push
out dataset samples first, then the oldest search samples. A phase trains on reuse x (samples added since the last
phase) samples drawn uniformly from the buffer, so a sample is trained on about `reuse` times on average whatever the
capacity; the capacity sets the age window and the dataset share. Dataset samples never fall below
`minimum_dataset_share` of the capacity (against format and skill drift): eviction stops taking them there, and the
trainer tops them up when a larger capacity leaves too few.
"""

import json
import math
import os
import random
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from lean_search.expert_iteration.loop_config import BufferConfig
from lean_search.search.records import from_json_object, to_json
from lean_search.training.dpo_data import PreferencePair
from lean_search.value.labels import ValueExample


class SampleOrigin(StrEnum):
    DATASET = "dataset"
    SEARCH = "search"


@dataclass(frozen=True)
class PolicySample:
    origin: SampleOrigin
    # The phase whose search produced it (0 for dataset samples).
    phase: int
    # A pair without a rejected step trains the chosen step's NLL only.
    pair: PreferencePair


@dataclass(frozen=True)
class ValueSample:
    origin: SampleOrigin
    phase: int
    example: ValueExample


class Buffered(Protocol):
    @property
    def origin(self) -> SampleOrigin: ...


@dataclass(frozen=True)
class BufferStatistics:
    name: str
    # Search samples added per phase, a moving average; the capacity follows it.
    inflow_average: float
    capacity: int
    size: int
    dataset_share: float
    added: int
    evicted_dataset: int
    evicted_search: int
    trained: int
    # Trained over added this phase: how often a new sample is used on average.
    reuse: float
    trained_dataset_share: float


class FifoBuffer[T: Buffered]:
    def __init__(self, capacity: int, items: Iterable[T] = (), minimum_dataset_share: float = 0.0) -> None:
        self.capacity = capacity
        self.minimum_dataset_share = minimum_dataset_share
        self.dataset: deque[T] = deque()
        self.search: deque[T] = deque()
        self.add(list(items))

    def __len__(self) -> int:
        return len(self.dataset) + len(self.search)

    def add(self, items: Sequence[T]) -> tuple[int, int]:
        """Appends and evicts beyond capacity, dataset samples first; returns the evicted (dataset, search) counts."""
        for item in items:
            (self.dataset if item.origin == SampleOrigin.DATASET else self.search).append(item)
        evicted_dataset = evicted_search = 0
        while len(self) > self.capacity:
            if self.dataset and (len(self.dataset) > self.dataset_floor() or not self.search):
                self.dataset.popleft()
                evicted_dataset += 1
            else:
                self.search.popleft()
                evicted_search += 1
        return evicted_dataset, evicted_search

    def dataset_floor(self) -> int:
        return math.ceil(self.minimum_dataset_share * self.capacity)

    def dataset_shortfall(self) -> int:
        return max(0, self.dataset_floor() - len(self.dataset))

    def items(self) -> list[T]:
        return [*self.dataset, *self.search]

    def dataset_share(self) -> float:
        return len(self.dataset) / len(self) if len(self) else 0.0

    def sample(self, count: int, generator: random.Random) -> list[T]:
        """Uniform; every item is drawn count // size or one more times."""
        items = self.items()
        if not count:
            return []
        passes, remainder = divmod(count, len(items))
        drawn = [item for _ in range(passes) for item in generator.sample(items, len(items))]
        return drawn + generator.sample(items, remainder)


def trained_count(added: int, reuse: float) -> int:
    return round(added * reuse)


def updated_inflow(average: float | None, added: int) -> float:
    return float(added) if average is None else (average + added) / 2


def adapted_capacity(config: BufferConfig, inflow_average: float | None) -> int:
    """`capacity_phases` phases of inflow once it is measured, so the buffer spans about that many phases."""
    if inflow_average is None:
        return config.initial_capacity
    return max(config.minimum_capacity, round(config.capacity_phases * inflow_average))


def phase_statistics[T: Buffered](
    name: str,
    buffer: FifoBuffer[T],
    inflow_average: float,
    added: int,
    evicted: tuple[int, int],
    trained: Sequence[T],
) -> BufferStatistics:
    return BufferStatistics(
        name=name,
        inflow_average=inflow_average,
        capacity=buffer.capacity,
        size=len(buffer),
        dataset_share=buffer.dataset_share(),
        added=added,
        evicted_dataset=evicted[0],
        evicted_search=evicted[1],
        trained=len(trained),
        reuse=len(trained) / added if added else 0.0,
        trained_dataset_share=(
            sum(item.origin == SampleOrigin.DATASET for item in trained) / len(trained) if trained else 0.0
        ),
    )


def write_buffer(path: Path, buffer: FifoBuffer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in buffer.items():
            handle.write(to_json(item) + "\n")
    os.replace(temporary, path)


def read_buffer_items[T](path: Path, item_type: type[T]) -> Iterator[T]:
    with path.open(encoding="utf-8") as lines:
        yield from (from_json_object(item_type, json.loads(line)) for line in lines if line.strip())
