"""An NCCL all-reduce on every GPU of the node, one rank each, as the GRPO trainer sums its LoRA gradients.

    python -m torch.distributed.run --standalone --nproc-per-node 4 experiments/nccl_check.py [--mebibytes 256]

Each rank fills an fp32 tensor (the gradients' type) with its rank + 1 and all-reduces it `--rounds` times; every
element must come back as the sum over the ranks. The main rank prints the bus bandwidth per round. A hang in the
first round on a PCIe node without peer-to-peer access is fixed with NCCL_P2P_DISABLE=1; an error creating a
shared-memory segment means /dev/shm is too small (Docker's 64 MB default; deployment/README.md, "GRPO loop").
"""

import argparse
import datetime
import os
import time

import torch
import torch.distributed as distributed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mebibytes", type=int, default=256, help="tensor size, the trainer's all-reduce bucket")
    parser.add_argument("--rounds", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    distributed.init_process_group("nccl", timeout=datetime.timedelta(minutes=5))
    rank = distributed.get_rank()
    world_size = distributed.get_world_size()
    elements = arguments.mebibytes * 2**20 // 4
    expected = world_size * (world_size + 1) / 2
    for round_number in range(arguments.rounds):
        tensor = torch.full((elements,), float(rank + 1), device="cuda")
        torch.cuda.synchronize()
        started = time.perf_counter()
        distributed.all_reduce(tensor)
        torch.cuda.synchronize()
        seconds = time.perf_counter() - started
        if not torch.all(tensor == expected):
            raise SystemExit(f"rank {rank}: the all-reduce returned wrong sums")
        if rank == 0:
            # Ring all-reduce moves 2 (n - 1) / n of the tensor over each rank's link.
            bus_gigabytes = 2 * (world_size - 1) / world_size * elements * 4 / seconds / 1e9
            print(
                f"round {round_number}: {arguments.mebibytes} MiB on {world_size} ranks in {seconds * 1000:.1f} ms, "
                f"bus {bus_gigabytes:.1f} GB/s",
                flush=True,
            )
    distributed.destroy_process_group()
    if rank == 0:
        print("NCCL all-reduce correct on every rank", flush=True)


if __name__ == "__main__":
    main()
