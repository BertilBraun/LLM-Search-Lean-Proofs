"""Data parallelism of the LoRA trainers over torchrun ranks: each optimizer step's batch split across the ranks by
tokens, the LoRA gradients and the step's metrics summed, so that a step equals the single-process step."""

import datetime
import os
import typing
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import torch
import torch.distributed

# Ranks wait at collectives while the main rank prepares the data or merges the adapters.
COLLECTIVE_TIMEOUT = datetime.timedelta(hours=1)
# 256 MiB of fp32 gradients per all-reduce.
GRADIENT_BUCKET_ELEMENTS = 2**26


@dataclass(frozen=True)
class Ranks:
    rank: int = 0
    world_size: int = 1

    @property
    def is_main(self) -> bool:
        return self.rank == 0


SINGLE_PROCESS = Ranks()


def start_process_group(backend: str) -> Ranks:
    """torchrun's ranks; a single process starts no group."""
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    if world_size == 1:
        return SINGLE_PROCESS
    torch.distributed.init_process_group(backend, timeout=COLLECTIVE_TIMEOUT)
    return Ranks(torch.distributed.get_rank(), world_size)


def stop_process_group(ranks: Ranks) -> None:
    if ranks.world_size > 1:
        torch.distributed.destroy_process_group()


def balanced_shards(indices: Sequence[int], costs: Sequence[int], world_size: int) -> list[tuple[int, ...]]:
    """Costliest first, each index (costs[index]) to the least loaded shard; every shard keeps the input order."""
    loads = [0] * world_size
    owners: dict[int, int] = {}
    for index in sorted(indices, key=lambda index: -costs[index]):
        shard = loads.index(min(loads))
        owners[index] = shard
        loads[shard] += costs[index]
    return [tuple(index for index in indices if owners[index] == shard) for shard in range(world_size)]


def local_shard(indices: Sequence[int], costs: Sequence[int], ranks: Ranks) -> tuple[int, ...]:
    return balanced_shards(indices, costs, ranks.world_size)[ranks.rank]


def summed(tensor: torch.Tensor, ranks: Ranks) -> torch.Tensor:
    """The tensor summed over the ranks, in place."""
    if ranks.world_size > 1:
        torch.distributed.all_reduce(tensor)
    return tensor


def largest(value: float, device: torch.device, ranks: Ranks) -> float:
    if ranks.world_size == 1:
        return value
    tensor = torch.tensor(value, dtype=torch.float64, device=device)
    torch.distributed.all_reduce(tensor, op=torch.distributed.ReduceOp.MAX)
    return tensor.item()


def buckets(tensors: Sequence[torch.Tensor]) -> Iterator[list[torch.Tensor]]:
    bucket: list[torch.Tensor] = []
    elements = 0
    for tensor in tensors:
        if bucket and elements + tensor.numel() > GRADIENT_BUCKET_ELEMENTS:
            yield bucket
            bucket, elements = [], 0
        bucket.append(tensor)
        elements += tensor.numel()
    if bucket:
        yield bucket


def sum_gradients(parameters: Sequence[torch.nn.Parameter], ranks: Ranks) -> None:
    """Each rank's gradients become their sum over the ranks; a rank without micro-batches in the step adds zeros."""
    if ranks.world_size == 1:
        return
    gradients = []
    for parameter in parameters:
        if parameter.grad is None:
            parameter.grad = torch.zeros_like(parameter)
        gradients.append(parameter.grad)
    for bucket in buckets(gradients):
        flat = torch.cat([gradient.reshape(-1) for gradient in bucket])
        torch.distributed.all_reduce(flat)
        for gradient, part in zip(bucket, flat.split([gradient.numel() for gradient in bucket]), strict=True):
            gradient.copy_(part.view_as(gradient))


def gathered[T](local: Sequence[tuple[int, T]], count: int, ranks: Ranks) -> list[T]:
    """Items computed on the ranks, each under its index in 0..count-1, all of them on every rank."""
    parts: list[list[tuple[int, T]]] = [list(local)]
    if ranks.world_size > 1:
        parts = typing.cast(list[list[tuple[int, T]]], [None] * ranks.world_size)
        torch.distributed.all_gather_object(parts, list(local))
    by_index = {index: item for part in parts for index, item in part}
    return [by_index[index] for index in range(count)]


def broadcast_from_main[T](value: T, ranks: Ranks) -> T:
    if ranks.world_size == 1:
        return value
    holder = [value]
    torch.distributed.broadcast_object_list(holder, src=0)
    return holder[0]


def barrier(ranks: Ranks) -> None:
    if ranks.world_size > 1:
        torch.distributed.barrier()
