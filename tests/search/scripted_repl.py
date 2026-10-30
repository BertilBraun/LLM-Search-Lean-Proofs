"""A REPL without Lean for searches from a given state: blocks reach scripted goals or fail with a scripted error."""

import gzip
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.lean import LeanError, LeanReplConfig, ProofState
from lean_search.lean.identifiers import environment_names_path
from lean_search.lean.plans import TacticPlan
from lean_search.lean.repl import BlockResult, VerificationResult
from lean_search.lean.text import split_header

HEADER = "import Mathlib\n"
STATEMENT = "theorem t (a : ℕ) : a + 0 = a := by\n"
ROOT_GOALS = ("a : ℕ\n⊢ a + 0 = a",)


def write_environment_names(project_directory: Path, constants: list[str]) -> Path:
    """The names cache the identifier check reads for HEADER, under `project_directory`'s pins."""
    directory = project_directory / "names"
    path = environment_names_path(split_header(HEADER).imports, project_directory, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"constant\ttheorem\t{name}" for name in constants] + ["leading\ttactic\trw", "leading\ttactic\tsimp"]
    with gzip.open(path, "wt", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return directory


@dataclass
class ScriptedRepl:
    project_directory: Path
    # Block text to the goals it reaches; any other block fails with `error`.
    outcomes: Mapping[str, tuple[str, ...]]
    error: str = "linarith failed"
    blocks: list[str] = field(default_factory=list)

    @property
    def config(self) -> LeanReplConfig:
        return LeanReplConfig(project_directory=self.project_directory)

    async def apply_block(
        self, state: ProofState, plan: TacticPlan, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> BlockResult:
        self.blocks.append(plan.block)
        if plan.rejection is not None:
            return BlockResult(state, (), len(plan.tactics), plan.rejection, 0.0, plan.tactics)
        goals = self.outcomes.get(plan.block)
        if goals is None:
            return BlockResult(state, (), len(plan.tactics), LeanError(self.error), 0.0, plan.tactics)
        reached = ProofState(state.header, state.statement, (*state.tactics, plan.block), goals, 0, 0)
        applied = tuple(tactic.text for tactic in plan.tactics)
        return BlockResult(reached, applied, len(applied), None, 0.0, plan.tactics, False, (reached,) * len(applied))

    async def verify_state(self, state: ProofState) -> VerificationResult:
        return VerificationResult(True, (), (), 0.0)


def root_state() -> ProofState:
    return ProofState(HEADER, STATEMENT, (), ROOT_GOALS, 0, 0)
