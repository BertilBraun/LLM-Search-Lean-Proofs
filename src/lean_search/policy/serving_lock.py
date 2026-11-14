"""One lock for the node's model servers, at a fixed path ($LEAN_SEARCH_CHECKPOINTS/serving.lock): a probe evaluation
(experiments/probe_evaluate.py) holds it while it swaps its checkpoint into the servers, and a loop, grpo_evaluate.py
and run_search.py refuse to start while it is held. flock is released when its holder dies, so a crash leaves no stale
lock."""

import contextlib
import fcntl
import os
from collections.abc import Iterator
from pathlib import Path

SERVING_LOCK_FILE = "serving.lock"


class ServingBusyError(RuntimeError):
    pass


def serving_lock_path(checkpoints_root: Path) -> Path:
    return checkpoints_root / SERVING_LOCK_FILE


@contextlib.contextmanager
def serving_lock(path: Path) -> Iterator[None]:
    """Held for a whole probe evaluation, its PID in the file; raises ServingBusyError while another holds it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.seek(0)
            raise ServingBusyError(f"A probe evaluation (pid {handle.read().strip()}) holds {path}.") from error
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def lock_holder(path: Path) -> str | None:
    """The PID holding the lock, None when it is free (taken for an instant to find out)."""
    if not path.exists():
        return None
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            return handle.read().strip() or "unknown"
        fcntl.flock(handle, fcntl.LOCK_UN)
        return None


def refuse_while_served(path: Path, what: str) -> None:
    """Raises ServingBusyError while a probe evaluation holds the servers."""
    holder = lock_holder(path)
    if holder is not None:
        raise ServingBusyError(
            f"A probe evaluation (pid {holder}) holds the model servers ({path}): {what} waits until it ends."
        )
