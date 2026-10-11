"""The value model's classes: remaining proof steps 1..7, 8 or more, and dead; read out as expected steps."""

from collections.abc import Sequence
from dataclasses import dataclass

STEP_BIN_COUNT = 8
DEAD_BIN = STEP_BIN_COUNT
BIN_COUNT = STEP_BIN_COUNT + 1


def step_bin(steps: int) -> int:
    return min(steps, STEP_BIN_COUNT) - 1


@dataclass(frozen=True)
class Readout:
    """h = sum_k p_k * steps_k: bins 1..7 count their steps, the 8+ bin and a dead end count these fixed values."""

    eight_or_more_steps: float = 10.0
    dead_steps: float = 16.0

    @property
    def bin_steps(self) -> tuple[float, ...]:
        return (*(float(steps) for steps in range(1, STEP_BIN_COUNT)), self.eight_or_more_steps, self.dead_steps)

    def remaining_steps(self, probabilities: Sequence[float]) -> float:
        return sum(probability * steps for probability, steps in zip(probabilities, self.bin_steps, strict=True))

    def alive_remaining_steps(self, probabilities: Sequence[float]) -> float:
        """The expected steps given that the state is not a dead end."""
        alive = probabilities[:STEP_BIN_COUNT]
        return sum(probability * steps for probability, steps in zip(alive, self.bin_steps, strict=False)) / sum(alive)

    def label_steps(self, steps: int) -> float:
        return self.bin_steps[step_bin(steps)]
