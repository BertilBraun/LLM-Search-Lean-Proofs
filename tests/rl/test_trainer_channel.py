from pathlib import Path

import pytest

from lean_search.rl.trainer_channel import (
    TrainerChannel,
    TrainerCommand,
    TrainerCommandKind,
    TrainerReady,
    TrainerReply,
)

TRAIN = TrainerCommand(
    3, TrainerCommandKind.TRAIN, 7, "phase_0007.toml", "trees/phase_0007", ("trees/phase_0007",), "out"
)


def channel(root: Path) -> TrainerChannel:
    opened = TrainerChannel(root / "trainer")
    opened.clear()
    return opened


def test_a_rank_reads_the_command_as_the_loop_sent_it(tmp_path: Path) -> None:
    opened = channel(tmp_path)
    opened.send(TRAIN)
    assert opened.command_after(2) == TRAIN


@pytest.mark.parametrize("handled", [3, 4])
def test_a_command_already_handled_is_not_read_again(tmp_path: Path, handled: int) -> None:
    opened = channel(tmp_path)
    opened.send(TRAIN)
    assert opened.command_after(handled) is None


def test_a_newer_command_replaces_the_one_before(tmp_path: Path) -> None:
    opened = channel(tmp_path)
    opened.send(TrainerCommand(1, TrainerCommandKind.PREPARE, 7))
    opened.send(TRAIN)
    assert opened.command_after(0) == TRAIN


def test_no_command_before_the_loop_sent_one(tmp_path: Path) -> None:
    assert channel(tmp_path).command_after(0) is None


@pytest.mark.parametrize(("sequence", "answered"), [(3, True), (2, False), (4, False)])
def test_a_reply_answers_only_its_own_command(tmp_path: Path, sequence: int, answered: bool) -> None:
    opened = channel(tmp_path)
    opened.answer(TrainerReply(3, 7))
    assert (opened.reply_to(sequence) is not None) == answered


def test_clearing_forgets_an_earlier_jobs_readiness(tmp_path: Path) -> None:
    opened = channel(tmp_path)
    opened.announce(TrainerReady(12.0))
    opened.clear()
    assert opened.ready() is None


def test_clearing_forgets_an_earlier_jobs_reply(tmp_path: Path) -> None:
    opened = channel(tmp_path)
    opened.answer(TrainerReply(1, 7))
    opened.clear()
    assert opened.reply_to(1) is None
