import contextlib
import dataclasses
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from loop_fakes import LOOP_TOML, loop_world, record_version_zero, run_until

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_search import PauseGate
from lean_search.lean import ProofState, TacticResult
from lean_search.policy.config import FeedbackConfig
from lean_search.rl.budget_signals import arm_outcomes, arm_outcomes_text
from lean_search.rl.loop_config import parse_loop_config
from lean_search.rl.loop_services import LeanTreeSearcher, OptionsArmSearch
from lean_search.rl.search_models import SearchModels, options_run_config
from lean_search.rl.search_options import (
    CONTROL_ARM,
    OptionsArmConfig,
    SearchOptions,
    search_arm,
    with_search_options,
    without_search_options,
)
from lean_search.rl.tree_store import TreeEntry, TreeStore
from lean_search.rl.tree_summary import TreeSummary
from lean_search.search import (
    CandidateBatches,
    DepthPlusGoals,
    Node,
    RunConfig,
    SearchConfig,
    SearchContext,
    load_run_config,
)

REPOSITORY = Path(__file__).resolve().parents[2]
FEEDBACK = SearchOptions(feedback=FeedbackConfig(enabled=True))
ARM = OptionsArmConfig("feedback", FEEDBACK)


def template() -> RunConfig:
    return load_run_config(REPOSITORY / "experiments" / "configs" / "grpo" / "search" / "visible_student_v2.toml")


def test_evaluation_template_turns_every_option_off() -> None:
    enabled = with_search_options(template(), dataclasses.replace(FEEDBACK, failed_automation_in_prompt=True))
    assert without_search_options(enabled).policy == without_search_options(template()).policy


def test_failed_automation_in_the_prompt_turns_overlap_off() -> None:
    options = SearchOptions(failed_automation_in_prompt=True)
    assert options_run_config(template(), options).expander.overlap is False


def test_options_arm_config_is_the_template_with_its_options() -> None:
    assert options_run_config(template(), FEEDBACK).policy.feedback.enabled


def test_statements_split_into_both_arms() -> None:
    assert {search_arm(ARM, f"statement_{index}") for index in range(64)} == {CONTROL_ARM, "feedback"}


def test_a_statement_keeps_its_arm() -> None:
    assert search_arm(ARM, "mathd_algebra_10") == search_arm(ARM, "mathd_algebra_10")


def test_without_the_a_b_a_statement_has_no_arm() -> None:
    assert search_arm(OptionsArmConfig(), "mathd_algebra_10") == ""


def test_options_arm_may_not_be_called_control() -> None:
    with pytest.raises(ValueError):
        parse_loop_config(LOOP_TOML + '\n[sampling.options_arm]\nname = "control"\n')


def test_options_arm_is_read_from_the_loop_config() -> None:
    text = LOOP_TOML.replace("status_seconds = 0.01\n", 'status_seconds = 0.01\n[sampling.options_arm]\nname = "fb"\n')
    assert parse_loop_config(text).sampling.options_arm.name == "fb"


def arm_entry(
    arm: str,
    proved: bool,
    groups: int = 0,
    tokens: int = 1000,
    feedback_groups: int = 0,
    tokens_to_first_proof: int = 0,
    wall_seconds: float = 1800.0,
    lean_seconds: float = 0.0,
) -> TreeEntry:
    summary = TreeSummary(
        32,
        1 if proved else None,
        None,
        groups,
        arm=arm,
        generated_tokens=tokens,
        generated_tokens_to_first_proof=tokens_to_first_proof,
        feedback_trainable_groups=feedback_groups,
        lean_seconds=lean_seconds,
    )
    return TreeEntry(0, "p", 1, "f", proved, int(proved), 1, 0, None, wall_seconds, 0.0, summary)


def test_arm_outcomes_sum_each_arm_s_trees() -> None:
    entries = [arm_entry("control", True, 2, 1000), arm_entry("fb", False, 0, 3000), arm_entry("fb", True, 1, 1000)]
    outcomes = arm_outcomes(entries)
    assert (outcomes["fb"].trees, outcomes["fb"].solved, outcomes["fb"].solved_per_thousand_tokens) == (2, 1, 0.25)


def test_without_the_a_b_there_are_no_arm_outcomes() -> None:
    assert arm_outcomes([arm_entry("", True, 1, 100)]) == {}


def test_arm_outcomes_count_the_feedback_rounds_groups_apart() -> None:
    entries = [arm_entry("fb", True, groups=3, feedback_groups=1), arm_entry("fb", True, groups=2, feedback_groups=2)]
    assert arm_outcomes(entries)["fb"].feedback_trainable_groups == 3


def test_arm_outcomes_split_the_tokens_at_the_first_proof() -> None:
    entries = [arm_entry("fb", True, tokens=900, tokens_to_first_proof=400), arm_entry("fb", False, tokens=500)]
    assert arm_outcomes(entries)["fb"].generated_tokens_to_first_proof == 400


@pytest.mark.parametrize(("field", "total"), [("wall_seconds", 3000.0), ("lean_seconds", 700.0)])
def test_arm_outcomes_sum_the_trees_seconds(field: str, total: float) -> None:
    entries = [
        arm_entry("fb", True, wall_seconds=1000.0, lean_seconds=200.0),
        arm_entry("fb", False, wall_seconds=2000.0, lean_seconds=500.0),
    ]
    assert getattr(arm_outcomes(entries)["fb"], field) == total


def test_arm_outcomes_count_solves_per_tree_hour() -> None:
    entries = [arm_entry("fb", True, wall_seconds=1800.0), arm_entry("fb", False, wall_seconds=5400.0)]
    assert arm_outcomes(entries)["fb"].solved_per_tree_hour == 0.5


def control_and_arm(control_solved: int, arm_solved: int, trees: int = 40) -> list[TreeEntry]:
    return [arm_entry(CONTROL_ARM, index < control_solved) for index in range(trees)] + [
        arm_entry("fb", index < arm_solved) for index in range(trees)
    ]


def test_the_options_arm_reports_its_difference_per_thousand_tokens_to_the_control() -> None:
    difference = arm_outcomes(control_and_arm(10, 20))["fb"].solved_per_thousand_tokens_difference
    assert difference is not None and difference.difference == pytest.approx(0.25)


def test_the_interval_of_a_clear_difference_excludes_zero() -> None:
    difference = arm_outcomes(control_and_arm(5, 30))["fb"].solved_per_tree_hour_difference
    assert difference is not None and difference.low > 0


def test_the_interval_of_equal_arms_holds_zero() -> None:
    difference = arm_outcomes(control_and_arm(20, 20))["fb"].solved_per_tree_hour_difference
    assert difference is not None and difference.low < 0 < difference.high


def test_the_control_arm_has_no_difference() -> None:
    assert arm_outcomes(control_and_arm(10, 20))[CONTROL_ARM].solved_per_thousand_tokens_difference is None


def test_the_a_b_line_reports_the_options_arms_interval() -> None:
    assert "minus control (95% bootstrap over trees)" in arm_outcomes_text(arm_outcomes(control_and_arm(10, 20)))


@dataclass
class StartingRepl:
    """Starts every proof at one goal; nothing else is asked of it by a search whose expanders propose nothing."""

    async def start_proof(self, statement: str, header: str) -> TacticResult:
        return TacticResult(ProofState(header, statement, (), ("⊢ True",), 0, 0), 0.0)


class OneReplPool:
    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[StartingRepl]:
        yield StartingRepl()


@dataclass
class RecordingExpander:
    """Proposes nothing; records the arm it stands for and the statement it expanded."""

    arm: str
    expanded: list[tuple[str, str]] = field(default_factory=list)

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        self.expanded.append((self.arm, context.problem.name))
        return
        yield


def recording_models(expander: RecordingExpander) -> SearchModels:
    return SearchModels(expander, DepthPlusGoals(), None)


async def test_the_searcher_routes_each_statement_to_its_arms_expander() -> None:
    search = SearchConfig(max_expansions=1, check_identifiers=False, name_inaccessible_hypotheses=False)
    config = dataclasses.replace(template(), search=search)
    expanded: list[tuple[str, str]] = []
    control, arm = RecordingExpander(CONTROL_ARM, expanded), RecordingExpander(ARM.name, expanded)
    options_arm = OptionsArmSearch(ARM, search, recording_models(arm))
    pool = OneReplPool()
    searcher = LeanTreeSearcher(config, pool, recording_models(control), PauseGate(), None, options_arm)
    names = [f"statement_{index}" for index in range(16)]
    for name in names:
        await searcher.search(Problem(name, Split.VALID, "", "theorem t : True := by", "", ""))
    assert expanded == [(search_arm(ARM, name), name) for name in names]


async def test_the_loop_records_each_tree_under_its_statements_arm(tmp_path: Path) -> None:
    text = LOOP_TOML.replace("status_seconds = 0.01\n", 'status_seconds = 0.01\n[sampling.options_arm]\nname = "fb"\n')
    world = loop_world(tmp_path, text)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    entries = TreeStore(world.paths.trees).entries
    arm = world.config.sampling.options_arm
    assert [entry.summary.arm for entry in entries] == [search_arm(arm, entry.problem_name) for entry in entries]
