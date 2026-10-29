"""The GRPO loop's persistent training job: one process per training GPU (torchrun), alive across phases.

    [torchrun --standalone --nproc-per-node 4] experiments/grpo_trainer.py --channel runs/<loop>/training/trainer \
        --host-directory /dev/shm/lean_search/<loop> --loop-process-id <pid> --loop-start-ticks <ticks> \
        [--lean-replay ...] [--math-replay ...] [--value-replay ...]

Started by the loop with `[training] persistent = true` (loop_services.PersistentTrainer), which sends its commands
through the channel directory (rl/trainer_channel.py). The ranks build the policy and value models once, keep them
parked in host memory between phases and train each phase the loop asks for (rl/resident_trainer.py); a phase's
adapters, steps and phase.json go where grpo_phase.py writes them, its merged weights to <host-directory>/handoff for
the servers. The ranks stop on the loop's `stop` command or, between commands, once the loop's process is gone.
"""

import argparse
import os
import time
from pathlib import Path

import torch

from lean_search.reasoning.dataset import read_examples as read_reasoning_examples
from lean_search.rl.resident_trainer import LoopProcess, ResidentInputs, TrainerRank
from lean_search.rl.trainer_channel import TrainerChannel, TrainerReady
from lean_search.training.data_parallel import barrier, start_process_group, stop_process_group
from lean_search.training.math_data import read_solutions
from lean_search.training.resident import HostDirectories
from lean_search.value.labels import read_examples as read_value_examples


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", type=Path, required=True)
    parser.add_argument("--host-directory", type=Path, required=True, help="parked weights and the handoff (a tmpfs)")
    parser.add_argument("--loop-process-id", type=int, required=True)
    parser.add_argument("--loop-start-ticks", type=int, required=True)
    parser.add_argument("--lean-replay", type=Path, help="reasoning data set JSON lines (Lean SFT replay)")
    parser.add_argument("--math-replay", type=Path, help="math solutions JSON lines")
    parser.add_argument("--value-replay", type=Path, help="v0 value examples JSON lines")
    return parser.parse_args()


def main() -> None:
    started = time.perf_counter()
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = parse_arguments()
    device = torch.device("cuda", int(os.environ.get("LOCAL_RANK", "0")))
    torch.cuda.set_device(device)
    ranks = start_process_group("nccl")
    inputs = ResidentInputs(
        lean_replay=list(read_reasoning_examples(arguments.lean_replay)) if arguments.lean_replay else [],
        math_replay=list(read_solutions(arguments.math_replay)) if arguments.math_replay else [],
        value_replay=list(read_value_examples(arguments.value_replay))
        if arguments.value_replay and ranks.is_main
        else [],
    )
    channel = TrainerChannel(arguments.channel)
    barrier(ranks)
    if ranks.is_main:
        channel.announce(TrainerReady(time.perf_counter() - started))

    def log(message: str) -> None:
        print(f"rank {ranks.rank}: {message}", flush=True)

    loop_process = LoopProcess(arguments.loop_process_id, arguments.loop_start_ticks)
    rank = TrainerRank(channel, HostDirectories(arguments.host_directory), inputs, device, ranks, loop_process, log)
    rank.serve()
    stop_process_group(ranks)


if __name__ == "__main__":
    main()
