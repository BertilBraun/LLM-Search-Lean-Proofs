import contextlib
import dataclasses
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from loop_fakes import LOOP_TOML, LoopWorld, loop_world, record_version_zero, run_until, statement

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_search import PauseGate
from lean_search.lean import ProofState, TacticResult
from lean_search.monitoring.families import OptionsVerdict, RatioInterval
from lean_search.policy.config import FeedbackConfig
from lean_search.rl.loop import GrpoLoop
from lean_search.rl.loop_config import parse_loop_config
from lean_search.rl.loop_services import LeanTreeSearcher, OptionsArmSearch
from lean_search.rl.options_ab import (
    arm_outcomes,
    arm_outcomes_text,
    options_arm_finished,
    options_look,
    options_look_text,
    options_verdict,
)
from lean_search.rl.search_models import SearchModels, options_run_config
from lean_search.rl.search_options import (
    CONTROL_ARM,
    OptionsArmConfig,
    SearchOptions,
    search_arm,
    with_search_options,
    without_search_options,
)
from lean_search.rl.statement_sources import FixedStatements
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
    paused_seconds: float = 0.0,
    phase: int = 1,
    difficulty: float | None = None,
    root_valid_blocks: int = 0,
    sampling_versions: tuple[int, ...] = (),
) -> TreeEntry:
    """A tree of `arm`; with feedback groups its feedback round drew 4 samples against 8 per first-round expansion."""
    summary = TreeSummary(
        32,
        1 if proved else None,
        None,
        groups,
        policy_expansions=1,
        policy_samples=8,
        arm=arm,
        generated_tokens=tokens,
        generated_tokens_to_first_proof=tokens_to_first_proof,
        feedback_trainable_groups=feedback_groups,
        lean_seconds=lean_seconds,
        feedback_expansions=1 if feedback_groups else 0,
        feedback_samples=4 if feedback_groups else 0,
        root_blocks=8,
        root_judged_blocks=8,
        root_valid_blocks=root_valid_blocks,
        sampling_versions=sampling_versions,
    )
    entry = TreeEntry(0, "p", phase, "f", proved, int(proved), 1, 0, difficulty, wall_seconds, 0.0, summary)
    return dataclasses.replace(entry, paused_seconds=paused_seconds)


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


def test_the_tree_hours_leave_out_the_pauses_a_search_waited_through() -> None:
    entries = [arm_entry("fb", True, wall_seconds=5400.0, paused_seconds=1800.0)]
    assert arm_outcomes(entries)["fb"].solved_per_tree_hour == 1.0


def test_a_feedback_group_weighs_its_samples_against_a_first_rounds() -> None:
    entries = [arm_entry("fb", True, groups=3, feedback_groups=2)]
    assert arm_outcomes(entries)["fb"].weighted_trainable_groups == 2.0


def test_arm_outcomes_count_weighted_groups_per_thousand_tokens() -> None:
    entries = [arm_entry("fb", True, groups=3, feedback_groups=2, tokens=500)]
    assert arm_outcomes(entries)["fb"].trainable_groups_per_thousand_tokens == 4.0


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


def test_the_options_arm_reports_its_difference_in_groups_per_thousand_tokens() -> None:
    entries = [arm_entry(CONTROL_ARM, True, groups=1) for _ in range(20)]
    entries += [arm_entry("fb", True, groups=2) for _ in range(20)]
    difference = arm_outcomes(entries)["fb"].trainable_groups_per_thousand_tokens_difference
    assert difference is not None and difference.difference == pytest.approx(1.0)


def balance_entries(control_difficulty: float, arm_difficulty: float) -> list[TreeEntry]:
    return [
        arm_entry(CONTROL_ARM, index % 2 == 0, difficulty=control_difficulty + index % 3, root_valid_blocks=4)
        for index in range(60)
    ] + [
        arm_entry("fb", index % 2 == 0, difficulty=arm_difficulty + index % 3, root_valid_blocks=4)
        for index in range(60)
    ]


@pytest.mark.parametrize(("arm_difficulty", "balanced"), [(2.0, True), (4.0, False)])
def test_the_balance_check_flags_arms_that_differ_in_difficulty(arm_difficulty: float, balanced: bool) -> None:
    balance = arm_outcomes(balance_entries(2.0, arm_difficulty))["fb"].balance
    assert balance is not None and balance.balanced == balanced


def test_the_control_arm_has_no_balance_of_its_own() -> None:
    assert arm_outcomes(balance_entries(2.0, 2.0))[CONTROL_ARM].balance is None


def interval(ratio: float, low: float, high: float) -> RatioInterval:
    return RatioInterval(ratio, low, high, 0.99)


@pytest.mark.parametrize(
    ("look", "solves", "solves_95", "guard_holds", "verdict"),
    [
        (2, interval(1.10, 1.02, 1.20), interval(1.10, 1.04, 1.18), True, OptionsVerdict.ADOPT),
        (2, interval(1.10, 1.02, 1.20), interval(1.10, 1.04, 1.18), False, OptionsVerdict.CONTINUE),
        (2, interval(1.04, 1.01, 1.08), interval(1.04, 1.02, 1.07), True, OptionsVerdict.CONTINUE),
        (2, interval(0.90, 0.85, 0.98), interval(0.90, 0.86, 0.96), True, OptionsVerdict.DROP_HARMFUL),
        (2, interval(1.00, 0.95, 1.04), interval(1.00, 0.96, 1.03), True, OptionsVerdict.CONTINUE),
        (4, interval(1.00, 0.95, 1.06), interval(1.00, 0.96, 1.04), True, OptionsVerdict.DROP_FUTILE),
        (4, interval(1.02, 0.95, 1.10), interval(1.02, 0.97, 1.07), True, OptionsVerdict.CONTINUE),
        (6, interval(1.02, 0.98, 1.06), interval(1.02, 0.98, 1.06), True, OptionsVerdict.DROP_NOT_ADOPTED),
    ],
    ids=[
        "adopt",
        "guard fails",
        "too small to adopt",
        "harmful",
        "inconclusive at 2",
        "futile at 4",
        "inconclusive at 4",
        "not adopted at 6",
    ],
)
def test_the_a_b_decision_rule(
    look: int, solves: RatioInterval, solves_95: RatioInterval, guard_holds: bool, verdict: OptionsVerdict
) -> None:
    assert options_verdict(look, solves, solves_95, guard_holds) == verdict


def phases_of_trees(arm_solved: int, control_solved: int, phases: range, trees: int = 100) -> list[TreeEntry]:
    """Per phase `trees` trees per arm, the first `..._solved` of each solved."""
    return [
        arm_entry(arm, index < solved, groups=1 if index < solved else 0, phase=phase)
        for phase in phases
        for arm, solved in ((CONTROL_ARM, control_solved), ("fb", arm_solved))
        for index in range(trees)
    ]


def test_a_look_is_due_after_the_a_bs_second_phase() -> None:
    look = options_look(phases_of_trees(50, 40, range(3, 5)), "fb", 5, ())
    assert look is not None and (look.look, look.phases) == (2, (3, 4))


def test_no_look_is_due_after_the_a_bs_third_phase() -> None:
    assert options_look(phases_of_trees(50, 40, range(3, 6)), "fb", 6, ()) is None


def test_a_look_pools_the_trees_by_the_phase_their_search_started() -> None:
    entries = phases_of_trees(50, 40, range(1, 3))
    straddling = dataclasses.replace(arm_entry("fb", True), phase=3, started_phase=2)
    look = options_look([*entries, straddling], "fb", 3, ())
    assert look is not None and look.arm_trees == 201


def test_a_look_leaves_out_the_trees_a_rejected_version_sampled() -> None:
    entries = [*phases_of_trees(50, 40, range(1, 3)), arm_entry("fb", True, phase=2, sampling_versions=(4,))]
    look = options_look(entries, "fb", 3, (4,))
    assert look is not None and look.arm_trees == 200


def test_a_clearly_better_arm_is_adopted_at_the_first_look() -> None:
    look = options_look(phases_of_trees(70, 30, range(1, 3)), "fb", 3, ())
    assert look is not None and look.verdict == OptionsVerdict.ADOPT


def test_a_clearly_worse_arm_is_dropped_as_harmful() -> None:
    look = options_look(phases_of_trees(30, 70, range(1, 3)), "fb", 3, ())
    assert look is not None and look.verdict == OptionsVerdict.DROP_HARMFUL


def test_the_look_estimates_r_as_the_ratio_of_solves_per_token() -> None:
    look = options_look(phases_of_trees(60, 40, range(1, 3)), "fb", 3, ())
    assert look is not None and look.solves_per_token.ratio == pytest.approx(1.5)


def test_the_first_looks_take_a_99_percent_interval() -> None:
    look = options_look(phases_of_trees(60, 40, range(1, 3)), "fb", 3, ())
    assert look is not None and look.solves_per_token.confidence == 0.99


def test_the_look_line_names_its_verdict() -> None:
    look = options_look(phases_of_trees(70, 30, range(1, 3)), "fb", 3, ())
    assert look is not None and options_look_text(look).endswith("verdict adopt")


@pytest.mark.parametrize(("collecting", "finished"), [(3, False), (4, True)])
def test_the_options_arm_finishes_after_its_phases(collecting: int, finished: bool) -> None:
    config = OptionsArmConfig("fb", FEEDBACK, max_phases=2)
    assert options_arm_finished(phases_of_trees(1, 1, range(2, 4), trees=2), config, collecting) == finished


def test_without_max_phases_the_options_arm_never_finishes() -> None:
    assert not options_arm_finished(phases_of_trees(1, 1, range(1, 9), trees=2), ARM, 20)


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
        await searcher.search(Problem(name, Split.VALID, "", "theorem t : True := by", "", ""), search_arm(ARM, name))
    assert expanded == [(search_arm(ARM, name), name) for name in names]


def options_arm_toml(max_phases: int = 0) -> str:
    arm = f'[sampling.options_arm]\nname = "fb"\nmax_phases = {max_phases}\n'
    return LOOP_TOML.replace("status_seconds = 0.01\n", "status_seconds = 0.01\n" + arm)


# Statements of both arms in turn: t7, t8 and t9 fall into "fb", t0-t3 into control.
MIXED_ARMS = (7, 0, 8, 1, 9, 2, 3)


def mixed_arms_loop(world: LoopWorld) -> GrpoLoop:
    loop = world.loop()
    loop.statements = FixedStatements([statement(number) for number in MIXED_ARMS])
    return loop


async def test_the_loop_records_each_tree_under_the_arm_it_searched_in(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml())
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    entries = TreeStore(world.paths.trees).entries
    assert {entry.problem_name: entry.summary.arm for entry in entries} == {
        entry.problem_name: world.searcher.arms[entry.problem_name] for entry in entries
    }


async def test_the_loop_searches_statements_in_both_arms(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml())
    record_version_zero(world)
    await run_until(world, mixed_arms_loop(world), phases=1)
    assert set(world.searcher.arms.values()) == {CONTROL_ARM, "fb"}


async def test_the_loop_records_the_phase_each_search_started_in(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=2)
    assert {entry.started_phase for entry in TreeStore(world.paths.trees).phase_entries(1)} == {1}


async def test_the_loop_records_the_seconds_each_search_waited_paused(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("concurrency = 2\n", "concurrency = 1\n", 1))
    world.searcher.paused_seconds_per_search = 7.0
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    assert {entry.paused_seconds for entry in TreeStore(world.paths.trees).entries} == {7.0}


async def test_the_options_arm_switches_off_after_its_phases(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml(max_phases=1))
    record_version_zero(world)
    await run_until(world, mixed_arms_loop(world), phases=3)
    later = [entry for entry in TreeStore(world.paths.trees).entries if entry.start_phase >= 2]
    assert {entry.summary.arm for entry in later} == {""}


async def test_the_options_arms_end_is_logged(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml(max_phases=1))
    record_version_zero(world)
    messages: list[str] = []
    loop = mixed_arms_loop(world)
    loop.log = messages.append
    await run_until(world, loop, phases=2)
    assert any(message.startswith("The search options A/B (fb) ran its 1 phases") for message in messages)


async def test_a_restart_after_the_options_arms_end_keeps_it_off(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml(max_phases=1))
    record_version_zero(world)
    await run_until(world, mixed_arms_loop(world), phases=2)
    assert not world.loop().options_arm_running


async def test_the_loop_logs_the_a_bs_look(tmp_path: Path) -> None:
    world = loop_world(tmp_path, options_arm_toml(max_phases=2))
    record_version_zero(world)
    messages: list[str] = []
    loop = mixed_arms_loop(world)
    loop.log = messages.append
    await run_until(world, loop, phases=3)
    assert any(message.startswith("Search options A/B (fb) look 2") for message in messages)
