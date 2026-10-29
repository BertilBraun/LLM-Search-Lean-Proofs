"""A stand-in for experiments/grpo_trainer.py: follows the command channel like the persistent job's main rank, without
a GPU (test_persistent_trainer.py).

    python fake_trainer_job.py <channel directory> <behaviour directory>

The behaviour directory steers and records it: `deaths` holds how many more `train` commands end the process at once
(shared across its restarts); `trained` gets "<process id> <phase>" and `prepared` "<phase>" per command handled.
"""

import json
import os
import sys
import time
from pathlib import Path

from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommandKind, TrainerReady, TrainerReply


def append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main() -> None:
    channel = TrainerChannel(Path(sys.argv[1]))
    behaviour = Path(sys.argv[2])
    channel.announce(TrainerReady(0.0))
    handled = 0
    while True:
        command = channel.command_after(handled)
        if command is None:
            time.sleep(0.01)
            continue
        handled = command.sequence
        match command.kind:
            case TrainerCommandKind.PREPARE:
                append_line(behaviour / "prepared", str(command.phase))
            case TrainerCommandKind.TRAIN:
                deaths = behaviour / "deaths"
                if deaths.exists() and int(deaths.read_text()) > 0:
                    deaths.write_text(str(int(deaths.read_text()) - 1))
                    os._exit(1)
                append_line(behaviour / "trained", f"{os.getpid()} {command.phase}")
                output = Path(command.output_directory)
                output.mkdir(parents=True, exist_ok=True)
                # A PhaseOutcome as JSON: importing torch would slow every start of this stand-in.
                outcome = {"trees": command.phase, "groups": 0, "policy": None, "value": None}
                (output / "phase.json").write_text(json.dumps(outcome), encoding="utf-8")
                channel.answer(TrainerReply(command.sequence, command.phase))
            case TrainerCommandKind.STOP:
                return


if __name__ == "__main__":
    main()
