"""The command channel between the GRPO loop and its persistent training job: three JSON files in a directory.

The loop writes `command.json` (one command at a time, numbered from 1 per job), every rank polls it and runs each
newer command; the main rank answers a `train` with `reply.json` carrying the command's number once phase.json is
written, and announces itself in `ready.json` once its ranks are up. Every file is written to a temporary name and
renamed, so a reader sees a whole file or the previous one. Only the latest command counts: a `prepare` overwritten by
the `train` of the same phase before a rank saw it is done within the `train`.
"""

import json
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.search.records import from_json_object


class TrainerCommandKind(StrEnum):
    # Sampling of the phase began: build the models it needs and read and label its trees as they arrive.
    PREPARE = "prepare"
    TRAIN = "train"
    STOP = "stop"


@dataclass(frozen=True)
class TrainerCommand:
    sequence: int
    kind: TrainerCommandKind
    phase: int = 0
    # The phase's training config (a file written by the loop), its tree directory and the value model's window.
    config: str = ""
    trees: str = ""
    value_trees: tuple[str, ...] = ()
    # Where the adapters and phase.json go.
    output_directory: str = ""


@dataclass(frozen=True)
class TrainerReply:
    sequence: int
    phase: int


@dataclass(frozen=True)
class TrainerReady:
    # From the job's start until its ranks joined their process group and loaded the tokenizers and replay data.
    start_seconds: float


@dataclass(frozen=True)
class TrainerChannel:
    directory: Path

    @property
    def command_path(self) -> Path:
        return self.directory / "command.json"

    @property
    def reply_path(self) -> Path:
        return self.directory / "reply.json"

    @property
    def ready_path(self) -> Path:
        return self.directory / "ready.json"

    def clear(self) -> None:
        """Before a job starts: nothing of an earlier job may be taken for its answers."""
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory.mkdir(parents=True)

    def send(self, command: TrainerCommand) -> None:
        write_json_atomically(self.command_path, command)

    def command_after(self, sequence: int) -> TrainerCommand | None:
        """The current command if it is newer than `sequence`."""
        if not self.command_path.exists():
            return None
        command = from_json_object(TrainerCommand, json.loads(self.command_path.read_text(encoding="utf-8")))
        return command if command.sequence > sequence else None

    def answer(self, reply: TrainerReply) -> None:
        write_json_atomically(self.reply_path, reply)

    def reply_to(self, sequence: int) -> TrainerReply | None:
        if not self.reply_path.exists():
            return None
        reply = from_json_object(TrainerReply, json.loads(self.reply_path.read_text(encoding="utf-8")))
        return reply if reply.sequence == sequence else None

    def announce(self, ready: TrainerReady) -> None:
        write_json_atomically(self.ready_path, ready)

    def ready(self) -> TrainerReady | None:
        if not self.ready_path.exists():
            return None
        return from_json_object(TrainerReady, json.loads(self.ready_path.read_text(encoding="utf-8")))
