"""The offline arm's build from walks (rl/offline_arm.split_examples and its neighbours), the walk's fingerprint, the
flattened held-out success, and the claim that an example is what the search's no-reasoning policy sees and emits."""

import dataclasses
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from test_policy_data import CharacterTokenizer  # noqa: E402

import lean_search  # noqa: E402
from lean_search.data import Problem, Split  # noqa: E402
from lean_search.lean import ProofState  # noqa: E402
from lean_search.lean.text import FORBIDDEN_TOKENS  # noqa: E402
from lean_search.policy.client import Sample  # noqa: E402
from lean_search.policy.prompts import FENCE, parse_sample, render_prompt  # noqa: E402
from lean_search.rl.offline_arm import (  # noqa: E402
    WALK_SOURCES,
    ExampleTokens,
    OfflineArmConfig,
    SplitExamples,
    WalkFingerprint,
    band_sizes,
    band_walks,
    fingerprint_differences,
    load_offline_arm_config,
    matched_sample,
    ranks_fit,
    split_examples,
    steady_tokens_per_second,
    usable_blocks,
    walk_fingerprint,
    walk_settings_text,
)
from lean_search.rl.offline_held_out import FlatReference, flattened_keys  # noqa: E402
from lean_search.rl.offline_walk import ProofWalk, WalkBlock, WalkedProof, WalkSettings, WalkStatus  # noqa: E402
from lean_search.rl.single_step import StateProblem  # noqa: E402
from lean_search.search import load_run_config  # noqa: E402
from lean_search.training.sft import StepRecord  # noqa: E402
from lean_search.training.sft_data import SftExample, tokenize_example  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY / "experiments/configs/grpo/followup/offline/offline_arm.toml"
PROBE_SEARCH = REPOSITORY / "experiments/configs/grpo/followup/offline/search_no_reasoning_16.toml"
PACKAGE = Path(lean_search.__file__).resolve().parent


def config(validation_fraction: float = 0.0, max_prompt_tokens: int = 7168) -> OfflineArmConfig:
    loaded = load_offline_arm_config(CONFIG_PATH)
    return dataclasses.replace(
        loaded,
        data=dataclasses.replace(loaded.data, validation_fraction=validation_fraction),
        walk=dataclasses.replace(loaded.walk, max_prompt_tokens=max_prompt_tokens),
    )


def block(goal: str, text: str = "simp", tactics: int = 1) -> WalkBlock:
    return WalkBlock((goal,), text, tactics)


def walked(name: str, status: WalkStatus, blocks: tuple[WalkBlock, ...]) -> WalkedProof:
    return WalkedProof(name, 0 if status == WalkStatus.COMPLETE else None, (status,), ProofWalk(status, blocks), 1.0)


def tokens(example: SftExample) -> ExampleTokens:
    return ExampleTokens(len(example.goals[0]), len(example.tactic_block))


def split(walks: list[WalkedProof], near: frozenset[tuple[str, ...]] = frozenset(), **settings: float) -> SplitExamples:
    characters = {walk.name: 1000 for walk in walks}
    return split_examples(walks, characters, tokens, near, config(**settings), 64)


def complete(name: str, blocks: int = 3) -> WalkedProof:
    return walked(name, WalkStatus.COMPLETE, tuple(block(f"⊢ {name} {index}") for index in range(blocks)))


def test_a_complete_walk_gives_every_block() -> None:
    assert len(usable_blocks(complete("p", 3))) == 3


@pytest.mark.parametrize("status", [WalkStatus.BLOCK_FAILED, WalkStatus.FORBIDDEN])
def test_a_walk_failing_at_a_block_keeps_its_valid_prefix(status: WalkStatus) -> None:
    assert len(usable_blocks(walked("p", status, (block("⊢ a"), block("⊢ b"))))) == 2


@pytest.mark.parametrize("status", [WalkStatus.REVISITED_STATE, WalkStatus.GOALS_REMAIN, WalkStatus.START_FAILED])
def test_other_failed_walks_give_nothing(status: WalkStatus) -> None:
    assert usable_blocks(walked("p", status, (block("⊢ a"),))) == ()


def test_no_validation_statement_reaches_training() -> None:
    found = split([complete(f"p{number}") for number in range(40)], validation_fraction=0.5)
    train = {proof.name for proof in found.train}
    assert train and found.validation and not train & {proof.name for proof in found.validation}


def test_the_matched_subset_draws_from_training_only() -> None:
    found = split([complete(f"p{number}") for number in range(40)], validation_fraction=0.5)
    matched = matched_sample(list(found.train), config().matched)
    assert {proof.name for proof in matched} <= {proof.name for proof in found.train}


def test_a_state_and_block_repeated_by_another_proof_is_counted_once() -> None:
    first = walked("first", WalkStatus.COMPLETE, (block("⊢ shared"), block("⊢ first")))
    second = walked("second", WalkStatus.COMPLETE, (block("⊢ shared"), block("⊢ second")))
    found = split([first, second])
    assert (sum(len(proof.examples) for proof in found.train), found.counts.duplicates) == (3, 1)


def test_a_prompt_over_the_cap_is_dropped_and_its_proofs_other_examples_stay() -> None:
    proof = walked("p", WalkStatus.COMPLETE, (block("⊢ " + "x" * 50), block("⊢ short")))
    found = split([proof], max_prompt_tokens=20)
    assert ([example.goals for example in found.train[0].examples], found.counts.over_prompt_cap) == (
        [("⊢ short",)],
        1,
    )


def test_a_state_near_a_held_out_one_is_dropped_and_counted() -> None:
    proof = walked("p", WalkStatus.COMPLETE, (block("⊢ near"), block("⊢ far")))
    found = split([proof], near=frozenset({("⊢ near",)}))
    assert (len(found.train[0].examples), found.counts.near_held_out_state) == (1, 1)


def test_prefix_examples_are_counted() -> None:
    failed = walked("p", WalkStatus.BLOCK_FAILED, (block("⊢ a"), block("⊢ b")))
    found = split([failed, complete("q")])
    assert (found.counts.prefix_examples, found.counts.prefix_proofs) == (2, 1)


def test_the_block_tactics_count_only_kept_examples() -> None:
    first = walked("first", WalkStatus.COMPLETE, (block("⊢ shared", tactics=3), block("⊢ first", tactics=2)))
    second = walked("second", WalkStatus.COMPLETE, (block("⊢ shared", tactics=3),))
    assert split([first, second]).block_tactics == {2: 1, 3: 1}


def test_examples_deeper_than_the_search_reaches_are_counted() -> None:
    assert split([complete("p", 70)]).counts.beyond_search_depth == 6


def test_band_walks_count_statuses_per_band() -> None:
    walks = [complete("short"), walked("long", WalkStatus.BLOCK_FAILED, ())]
    bands = band_walks(walks, {"short": 100, "long": 5000}, (500, 1000, 1500, 2000, 3000, 4500))
    assert (bands[0].statuses, bands[-1].statuses) == ({"complete": 1}, {"block failed": 1})


SETTINGS = WalkSettings(50_000, 60.0, True, True, True, "", ("exact?",), FORBIDDEN_TOKENS, 5)


def fingerprint(settings: WalkSettings = SETTINGS, proofs: str = "proofs") -> WalkFingerprint:
    text = walk_settings_text(settings, load_offline_arm_config(CONFIG_PATH).walk, "Qwen/Qwen3.5-4B", 1024)
    return walk_fingerprint(PACKAGE, text, proofs)


def test_the_same_code_settings_and_proofs_give_no_difference() -> None:
    assert fingerprint_differences(fingerprint(), fingerprint()) == []


def test_other_walk_settings_are_a_difference() -> None:
    other = dataclasses.replace(SETTINGS, heartbeats=200_000)
    assert fingerprint_differences(fingerprint(), fingerprint(other)) == ["the walk settings"]


def test_other_proofs_are_a_difference() -> None:
    assert fingerprint_differences(fingerprint(), fingerprint(proofs="other")) == ["proofs.jsonl"]


def test_a_changed_source_is_named() -> None:
    recorded = fingerprint()
    changed = dataclasses.replace(recorded, sources={**recorded.sources, "lean/plans.py": "0" * 64})
    assert fingerprint_differences(changed, recorded) == ["lean/plans.py"]


def test_the_fingerprint_covers_the_walk_and_the_search_code_it_runs() -> None:
    assert {"rl/offline_walk.py", "search/search.py", "lean/repl.py"} <= set(WALK_SOURCES)


def test_ranks_whose_data_fit_the_host_pass() -> None:
    assert ranks_fit(10 * 2**30, 4, 100 * 2**30)


def test_ranks_whose_data_take_most_of_the_host_do_not() -> None:
    assert not ranks_fit(30 * 2**30, 4, 140 * 2**30)


def step(number: int, seconds: float, tokens: int = 1000) -> StepRecord:
    return StepRecord(number, 0.0, 1e-4, 1.0, 1.0, tokens, tokens, 10, seconds, 0.0)


def test_steady_throughput_leaves_out_the_warmup_steps() -> None:
    records = [step(1, 100.0), step(2, 101.0), step(3, 102.0)]
    assert steady_tokens_per_second(records, 1) == 1000.0


def test_steady_throughput_needs_a_step_after_the_warmup() -> None:
    assert steady_tokens_per_second([step(1, 100.0)], 1) is None


def problem_with_reference(keys: tuple[tuple[str, ...], ...]) -> StateProblem:
    state = ProofState("", "", (), ("⊢ start",), 0, 0)
    return StateProblem(Problem("p", Split.VALID, "", "", "", ""), state, {key: 0 for key in keys})


def test_the_flattened_success_also_accepts_states_inside_the_reference_next_step() -> None:
    problem = problem_with_reference((("⊢ after",), ()))
    reference = FlatReference("p", (("⊢ inside", "⊢ after"),))
    assert flattened_keys(problem, reference) == {("⊢ after",), (), ("⊢ inside", "⊢ after")}


def test_a_failed_flat_reference_leaves_the_standard_states() -> None:
    problem = problem_with_reference((("⊢ after",), ()))
    assert flattened_keys(problem, FlatReference("p", (), "failed")) == problem.reference_keys


def walk_settings_of(path: Path) -> tuple[object, ...]:
    run = load_run_config(path)
    search = run.search
    return (
        search.tactic_heartbeats,
        search.tactic_timeout_seconds,
        search.flatten_blocks,
        search.name_inaccessible_hypotheses,
        search.check_identifiers,
        tuple(search.forbidden_steps),
        run.policy.max_tokens,
        run.policy.tokenizer,
    )


def test_the_walk_runs_blocks_as_the_probe_search_does() -> None:
    walk_search = REPOSITORY / load_offline_arm_config(CONFIG_PATH).walk.search_config
    assert walk_settings_of(walk_search) == walk_settings_of(PROBE_SEARCH)


def test_the_probe_search_prompts_with_the_bare_state() -> None:
    policy = load_run_config(PROBE_SEARCH).policy
    found = (policy.few_shot, policy.thinking, policy.visible_reasoning, policy.failed_automation_in_prompt)
    assert (found, policy.retrieval.lemma_count) == ((False, False, False, False), 0)


def test_an_examples_prompt_is_the_one_the_expander_renders_under_the_probe_search() -> None:
    policy = load_run_config(PROBE_SEARCH).policy
    tokenizer = CharacterTokenizer()
    goals = ("x : ℕ\n⊢ x + 0 = x",)
    expander_prompt = render_prompt(
        tokenizer,
        goals,
        (),
        few_shot=policy.few_shot,
        thinking=policy.thinking,
        thinking_instruction=policy.thinking_instruction,
        visible=policy.visible_reasoning,
    )
    example = tokenize_example(tokenizer, SftExample("offline_arm", "p", 0, goals, "simp"))
    assert example.input_ids[: example.prompt_token_count] == tuple(
        tokenizer.encode(expander_prompt, add_special_tokens=False)
    )


def test_the_policy_emitting_an_examples_completion_yields_its_block() -> None:
    block_text = "have h : x = x\nrfl\nsimp"
    sample = Sample(f"{block_text}\n", 0.0, 10, "stop", stop_string=FENCE)
    assert parse_sample(sample, thinking=False, visible=False) == block_text


def test_a_state_without_a_flattened_reference_keeps_the_standard_states() -> None:
    problem = problem_with_reference((("⊢ after",), ()))
    assert flattened_keys(problem, None) == problem.reference_keys


def test_the_band_sizes_count_the_prefix_proofs() -> None:
    failed = walked("p", WalkStatus.BLOCK_FAILED, (block("⊢ a"), block("⊢ b")))
    sizes = band_sizes(list(split([failed, complete("q")]).train), (500, 1000, 1500, 2000, 3000, 4500))
    assert (sizes[2].proofs, sizes[2].prefix_proofs) == (2, 1)
