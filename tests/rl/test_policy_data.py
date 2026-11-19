from collections.abc import Mapping, Sequence

import pytest
from rl_samples import (
    FAILING,
    MASKED,
    NO_PROGRESS,
    NODE_STEPS,
    OFF_GRAPH,
    PROOF_GRAPH,
    REDUNDANT,
    UNKNOWN,
    UNPROVED_CLAIM,
    group,
    sample,
)

from lean_search.policy.prompts import END_OF_TURN
from lean_search.rl.advantages import CreditMode
from lean_search.rl.grpo_groups import PolicyGroup
from lean_search.rl.policy_data import (
    ExpansionTexts,
    PolicyData,
    PolicyDataConfig,
    PolicyDataMetrics,
    PolicySequence,
    PolicyTree,
    SampledCompletion,
    build_policy_data,
)
from lean_search.rl.token_credit import CharacterSpan, TokenSegment
from lean_search.search.tactic_labels import TacticLabel
from lean_search.search.texts import InsertedSpan, SampledTokens, TokenSpan


class CharacterTokenizer:
    pad_token_id = 0

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        return "".join(f"<{turn['role']}>{turn['content']}" for turn in conversation) + "<assistant>"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [ord(character) for character in text]

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(chr(token) for token in token_ids)

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]:
        return {
            "input_ids": [ord(character) for character in text],
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


def completion(edge_id: int, block: str, *, recorded: bool = True, explanation: str = "Idea.") -> SampledCompletion:
    """With `recorded` the sample's token ids and log-probabilities, one token per character, as the search keeps."""
    text = f"{explanation}\n\n```lean\n{block}\n```"
    tactics = []
    position = text.index(block)
    for line in block.split("\n"):
        tactics.append(CharacterSpan(position, position + len(line)))
        position += len(line) + 1
    if not recorded:
        return SampledCompletion(edge_id, text, tuple(tactics))
    sampled = text + END_OF_TURN
    tokens = SampledTokens(tuple(ord(character) for character in sampled), tuple(-0.5 for _ in sampled))
    return SampledCompletion(edge_id, text, tuple(tactics), tokens=tokens)


def forced_completion(edge_id: int, block: str) -> SampledCompletion:
    """The opening inserted after the cut-off explanation, as budget forcing records it."""
    base = completion(edge_id, block)
    opening = base.text.index("\n\n```lean\n")
    span = InsertedSpan(CharacterSpan(opening, opening + 10), TokenSpan(opening, opening + 10))
    log_probabilities = tuple(
        None if opening <= index < opening + 10 else value for index, value in enumerate(base.tokens.log_probabilities)
    )
    return SampledCompletion(
        edge_id, base.text, base.tactic_spans, tokens=SampledTokens(base.tokens.token_ids, log_probabilities, (span,))
    )


def policy_data(
    *, recorded: bool = True, credit: CreditMode = CreditMode.PER_TACTIC, explanation: str = "Idea."
) -> PolicyData:
    trained = group(sample("good", PROOF_GRAPH, edge_id=0), sample("bad\nworse", FAILING, MASKED, edge_id=1), node_id=0)
    identical = group(sample("a", PROOF_GRAPH, edge_id=2), sample("b", PROOF_GRAPH, edge_id=3), node_id=1)
    texts = [
        ExpansionTexts(
            "p",
            0,
            "prompt",
            (
                completion(0, "good", recorded=recorded, explanation=explanation),
                completion(0, "good", recorded=recorded),
                completion(1, "bad\nworse", recorded=recorded),
            ),
            temperature=0.7,
            policy_version=3,
        ),
        ExpansionTexts("p", 1, "prompt", (completion(2, "a"), completion(3, "b"))),
    ]
    return single_tree_data([trained, identical], texts, PolicyDataConfig(credit))


def single_tree_data(
    groups: Sequence[PolicyGroup], texts: Sequence[ExpansionTexts], config: PolicyDataConfig
) -> PolicyData:
    return build_policy_data([PolicyTree(tuple(groups), tuple(texts))], CharacterTokenizer(), config)


def completion_text(sequence: PolicySequence) -> str:
    return "".join(map(chr, sequence.tokenized.input_ids[sequence.tokenized.prompt_token_count :]))


def test_every_recorded_completion_of_a_trained_group_is_a_sequence() -> None:
    assert [sequence.edge_id for sequence in policy_data().sequences] == [0, 0, 1]


@pytest.mark.parametrize("credit", list(CreditMode))
def test_groups_without_a_non_zero_advantage_are_dropped(credit: CreditMode) -> None:
    assert {sequence.node_id for sequence in policy_data(credit=credit).sequences} == {0}


def test_sequences_train_on_the_recorded_token_ids() -> None:
    sequence = policy_data().sequences[2]
    completion_ids = sequence.tokenized.input_ids[sequence.tokenized.prompt_token_count :]
    assert completion_ids == completion(1, "bad\nworse").tokens.token_ids


def test_prompt_is_the_recorded_prompt() -> None:
    sequence = policy_data().sequences[0]
    assert sequence.tokenized.input_ids[: sequence.tokenized.prompt_token_count] == tuple(map(ord, "prompt"))


def test_temperature_comes_from_the_expansion() -> None:
    assert policy_data().sequences[0].temperature == 0.7


def test_policy_version_comes_from_the_expansion() -> None:
    assert policy_data().sequences[0].policy_version == 3


def test_trees_of_the_same_problem_keep_their_own_texts() -> None:
    first = group(sample("win", PROOF_GRAPH, edge_id=0), sample("oops", FAILING, edge_id=1))
    second = group(sample("oops", FAILING, edge_id=0), sample("win", PROOF_GRAPH, edge_id=1))
    trees = [
        PolicyTree((first,), (ExpansionTexts("p", 0, "prompt", (completion(0, "win"), completion(1, "oops"))),)),
        PolicyTree((second,), (ExpansionTexts("p", 0, "prompt", (completion(0, "oops"), completion(1, "win"))),)),
    ]
    data = build_policy_data(trees, CharacterTokenizer(), PolicyDataConfig())
    signs = {(completion_text(sequence).count("win"), sum(sequence.advantages) > 0) for sequence in data.sequences}
    assert signs == {(1, True), (0, False)}


def test_sampler_log_probabilities_are_kept() -> None:
    assert set(policy_data().sequences[0].sampler_log_probabilities) == {-0.5}


def test_one_advantage_and_mask_entry_per_completion_token() -> None:
    sequence = policy_data().sequences[2]
    assert {len(sequence.advantages), len(sequence.trained)} == {sequence.tokenized.completion_token_count}


def test_tokens_after_the_failing_tactic_are_not_trained() -> None:
    sequence = policy_data().sequences[2]
    assert sum(not trained for trained in sequence.trained) == len("\nworse\n```" + END_OF_TURN)


def test_long_completions_are_kept() -> None:
    assert len(policy_data(explanation="Thinking. " * 400).sequences) == 3


def test_records_without_tokens_are_tokenized_again() -> None:
    assert policy_data(recorded=False).metrics.retokenized_sequences == 3


def test_sequence_credit_trains_every_token_of_a_failed_sample() -> None:
    assert all(policy_data(credit=CreditMode.SEQUENCE).sequences[2].trained)


@pytest.mark.parametrize("credit", [CreditMode.SEQUENCE, CreditMode.PROOF_SUCCESS])
def test_explanation_tokens_mean_the_same_in_every_credit_mode(credit: CreditMode) -> None:
    expected = policy_data().metrics.mean_explanation_tokens
    assert policy_data(credit=credit).metrics.mean_explanation_tokens == expected


def test_proof_success_credit_gives_every_token_of_a_failed_sample_minus_the_mean_r() -> None:
    sequence = policy_data(credit=CreditMode.PROOF_SUCCESS).sequences[2]
    assert (set(sequence.advantages), all(sequence.trained)) == ({-0.5}, True)


def test_tactic_counts_of_the_trained_groups() -> None:
    tactics = policy_data().metrics.tactics
    assert (tactics.proof_graph, tactics.failing, tactics.masked) == (1, 1, 1)


def test_forced_answers_are_kept_with_the_inserted_opening_untrained() -> None:
    group_with_forced = group(sample("good", PROOF_GRAPH, edge_id=0), sample("other", FAILING, edge_id=1))
    texts = [ExpansionTexts("p", 0, "prompt", (forced_completion(0, "good"), completion(1, "other")))]
    data = single_tree_data([group_with_forced], texts, PolicyDataConfig())
    forced = data.sequences[0]
    assert (data.metrics.forced_sequences, sum(not trained for trained in forced.trained)) == (1, 10)


def test_tokens_that_do_not_decode_to_the_text_fall_back_to_sequence_credit() -> None:
    broken = completion(0, "good")
    broken = SampledCompletion(0, broken.text, broken.tactic_spans, tokens=SampledTokens((ord("x"),), (-0.5,)))
    texts = [ExpansionTexts("p", 0, "prompt", (broken, completion(1, "bad")))]
    data = single_tree_data(
        [group(sample("good", PROOF_GRAPH, edge_id=0), sample("bad", FAILING, edge_id=1))], texts, PolicyDataConfig()
    )
    assert data.metrics.token_mismatch_sequences == 1


def test_unknown_only_sample_trains_its_explanation_and_tactic_tokens() -> None:
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "a"), completion(1, "b"), completion(2, "c")))]
    groups = [
        group(sample("a", PROOF_GRAPH, edge_id=0), sample("b", FAILING, edge_id=1), sample("c", UNKNOWN, edge_id=2))
    ]
    sequence = single_tree_data(groups, texts, PolicyDataConfig()).sequences[2]
    assert all(sequence.trained)


def test_closing_tokens_of_a_complete_block_train_with_zero_advantage() -> None:
    sequence = policy_data().sequences[0]
    closing = [
        (trained, advantage)
        for trained, advantage, segment in zip(sequence.trained, sequence.advantages, sequence.segments, strict=True)
        if segment == TokenSegment.CLOSING
    ]
    assert set(closing) == {(True, 0.0)}


@pytest.mark.parametrize("credit", list(CreditMode))
def test_inserted_tokens_are_untrained_in_every_credit_mode(credit: CreditMode) -> None:
    group_with_forced = group(sample("good", PROOF_GRAPH, edge_id=0), sample("other", FAILING, edge_id=1))
    texts = [ExpansionTexts("p", 0, "prompt", (forced_completion(0, "good"), completion(1, "other")))]
    data = single_tree_data([group_with_forced], texts, PolicyDataConfig(credit))
    opening = data.sequences[0].sampler_log_probabilities.index(None)
    assert not any(data.sequences[0].trained[opening : opening + 10])


def proof_success_metrics() -> PolicyDataMetrics:
    """A group whose samples reaching the proof graph are one with a failing tail and one no closer than the node."""
    mixed = group(
        sample("tail", PROOF_GRAPH, FAILING, MASKED, edge_id=0),
        sample("sideways", PROOF_GRAPH, steps=(NODE_STEPS,), edge_id=1),
        sample("error", FAILING, edge_id=2),
    )
    return single_tree_data([mixed], [], PolicyDataConfig(CreditMode.PROOF_SUCCESS)).metrics


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mean_proof_success", 2 / 3),
        ("trained_mean_proof_success", 2 / 3),
        ("proof_success_failing_tail_share", 0.5),
        ("proof_success_no_closer_share", 0.5),
    ],
)
def test_proof_success_metrics_of_a_phase(field: str, value: float) -> None:
    assert getattr(proof_success_metrics(), field) == pytest.approx(value)


PROGRESS_THEN_FAIL = "step\nbad\nworse"


def failing_block_sequences(*, cap: bool, credit: CreditMode = CreditMode.PER_TACTIC) -> list[PolicySequence]:
    """A group of a block that progresses and then fails, one that fails at once and a clean one: edges 0, 1, 2."""
    mixed = group(
        sample("step\nbad\nworse", PROOF_GRAPH, FAILING, MASKED, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("clean", PROOF_GRAPH, edge_id=2),
    )
    texts = [
        ExpansionTexts(
            "p", 0, "prompt", (completion(0, "step\nbad\nworse"), completion(1, "error"), completion(2, "clean"))
        )
    ]
    config = PolicyDataConfig(credit, cap_wasted_block_explanation=cap)
    return list(single_tree_data([mixed], texts, config).sequences)


def segment_advantages(sequence: PolicySequence, segment: TokenSegment) -> list[float]:
    return [
        advantage for advantage, kind in zip(sequence.advantages, sequence.segments, strict=True) if kind == segment
    ]


def test_a_block_that_progresses_and_then_fails_has_a_positive_explanation_without_the_cap() -> None:
    assert min(segment_advantages(failing_block_sequences(cap=False)[0], TokenSegment.EXPLANATION)) > 0


def test_the_cap_gives_a_block_that_progresses_and_then_fails_a_zero_explanation() -> None:
    assert set(segment_advantages(failing_block_sequences(cap=True)[0], TokenSegment.EXPLANATION)) == {0.0}


def test_the_capped_explanation_stays_trained() -> None:
    sequence = failing_block_sequences(cap=True)[0]
    explanation = [
        trained
        for trained, kind in zip(sequence.trained, sequence.segments, strict=True)
        if kind == TokenSegment.EXPLANATION
    ]
    assert all(explanation)


def test_the_cap_keeps_the_tactic_credit_of_a_failing_block() -> None:
    capped, uncapped = failing_block_sequences(cap=True)[0], failing_block_sequences(cap=False)[0]
    assert segment_advantages(capped, TokenSegment.TACTIC) == segment_advantages(uncapped, TokenSegment.TACTIC)


@pytest.mark.parametrize("edge_id", [1, 2], ids=["a negative explanation", "a block without a failing tactic"])
def test_the_cap_leaves_the_sequence_unchanged(edge_id: int) -> None:
    assert failing_block_sequences(cap=True)[edge_id] == failing_block_sequences(cap=False)[edge_id]


@pytest.mark.parametrize("credit", [CreditMode.SEQUENCE, CreditMode.PROOF_SUCCESS])
def test_the_cap_is_refused_without_per_tactic_credit(credit: CreditMode) -> None:
    with pytest.raises(ValueError, match="per-tactic"):
        PolicyDataConfig(credit, cap_wasted_block_explanation=True)


def progress_then_fail_group() -> PolicyGroup:
    return group(
        sample(PROGRESS_THEN_FAIL, PROOF_GRAPH, FAILING, MASKED, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("clean", PROOF_GRAPH, edge_id=2),
    )


def test_the_cap_records_the_samples_it_capped() -> None:
    config = PolicyDataConfig(cap_wasted_block_explanation=True)
    assert single_tree_data([progress_then_fail_group()], [], config).metrics.capped_explanation_samples == 1


def test_the_cap_records_the_credit_it_removed() -> None:
    removed = segment_advantages(failing_block_sequences(cap=False)[0], TokenSegment.EXPLANATION)[0]
    config = PolicyDataConfig(cap_wasted_block_explanation=True)
    metrics = single_tree_data([progress_then_fail_group()], [], config).metrics
    assert metrics.capped_explanation_credit == pytest.approx(removed)


def test_the_cap_reaches_a_failing_block_off_the_proof_graph_above_its_baseline() -> None:
    weak = group(
        sample(PROGRESS_THEN_FAIL, UNKNOWN, FAILING, MASKED, edge_id=0), sample("claim", UNPROVED_CLAIM, edge_id=1)
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, PROGRESS_THEN_FAIL), completion(1, "claim")))]
    capped = single_tree_data([weak], texts, PolicyDataConfig(cap_wasted_block_explanation=True)).sequences[0]
    assert set(segment_advantages(capped, TokenSegment.EXPLANATION)) == {0.0}


def test_the_cap_caps_every_token_of_a_sequence_it_cannot_split_by_tactic() -> None:
    recorded = completion(0, PROGRESS_THEN_FAIL)
    broken = SampledCompletion(0, recorded.text, recorded.tactic_spans, tokens=SampledTokens((ord("x"),), (-0.5,)))
    texts = [ExpansionTexts("p", 0, "prompt", (broken, completion(1, "error"), completion(2, "clean")))]
    config = PolicyDataConfig(cap_wasted_block_explanation=True)
    capped = single_tree_data([progress_then_fail_group()], texts, config).sequences[0]
    assert set(capped.advantages) == {0.0}


@pytest.mark.parametrize(
    "ending", [NO_PROGRESS, REDUNDANT, UNPROVED_CLAIM, UNKNOWN, OFF_GRAPH], ids=lambda label: label.value
)
def test_the_cap_reaches_a_block_that_progresses_and_then_wastes_a_tactic(ending: TacticLabel) -> None:
    wasteful = group(
        sample("step\nidle", PROOF_GRAPH, ending, edge_id=0),
        sample("error", FAILING, edge_id=1),
        sample("clean", PROOF_GRAPH, edge_id=2),
    )
    texts = [
        ExpansionTexts("p", 0, "prompt", (completion(0, "step\nidle"), completion(1, "error"), completion(2, "clean")))
    ]
    capped = single_tree_data([wasteful], texts, PolicyDataConfig(cap_wasted_block_explanation=True)).sequences[0]
    assert set(segment_advantages(capped, TokenSegment.EXPLANATION)) == {0.0}


def test_the_cap_reaches_a_block_whose_first_tactic_is_a_no_op() -> None:
    idle = group(
        sample("idle", NO_PROGRESS, edge_id=0),
        sample("claim", UNPROVED_CLAIM, edge_id=1),
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, "idle"), completion(1, "claim")))]
    capped = single_tree_data([idle], texts, PolicyDataConfig(cap_wasted_block_explanation=True)).sequences[0]
    assert set(segment_advantages(capped, TokenSegment.EXPLANATION)) == {0.0}


DETOUR = "step\nback"


def test_the_cap_leaves_a_detour_on_the_proof_graph_alone() -> None:
    detour = group(
        sample(DETOUR, PROOF_GRAPH, PROOF_GRAPH, steps=(NODE_STEPS - 1, NODE_STEPS), edge_id=0),
        sample("error", FAILING, edge_id=1),
    )
    texts = [ExpansionTexts("p", 0, "prompt", (completion(0, DETOUR), completion(1, "error")))]
    capped = single_tree_data([detour], texts, PolicyDataConfig(cap_wasted_block_explanation=True)).sequences[0]
    uncapped = single_tree_data([detour], texts, PolicyDataConfig()).sequences[0]
    assert capped == uncapped
