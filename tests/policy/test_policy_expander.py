import pytest

from lean_search.policy import Sample
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import search_candidates
from lean_search.policy.prompts import parse_samples
from lean_search.search import ExpanderKind
from lean_search.search.config import parse_run_config

POLICY_SECTION = """
[expander]
kind = "automation_then_policy"

[policy]
model = "qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
"""
TWO_SERVERS = 'server_urls = ["http://127.0.0.1:8000/v1", "http://127.0.0.1:8001/v1"]\n'


def parsed_samples() -> list[Sample]:
    return [
        Sample("simp", cumulative_logprob=-2.0, token_count=3, finish_reason="stop"),
        Sample("sorry", cumulative_logprob=-1.0, token_count=4, finish_reason="stop"),
        Sample("omega", cumulative_logprob=-1.5, token_count=2, finish_reason="stop"),
    ]


def test_first_candidate_carries_the_prompt_and_the_failed_samples() -> None:
    candidates = search_candidates(parse_samples(parsed_samples(), thinking=False), prompt_tokens=100)
    assert [(candidate.text, candidate.prompt_tokens, candidate.generated_tokens) for candidate in candidates] == [
        ("omega", 100, 2 + 4),
        ("simp", 0, 3),
    ]


def test_candidates_carry_their_log_probability() -> None:
    candidates = search_candidates(parse_samples(parsed_samples(), thinking=False), prompt_tokens=100)
    assert [candidate.log_probability for candidate in candidates] == [-1.5, -2.0]


def test_policy_section_is_parsed() -> None:
    config = parse_run_config(POLICY_SECTION + TWO_SERVERS)
    assert (config.expander.kind, config.policy.server_urls, config.policy.adapter) == (
        ExpanderKind.AUTOMATION_THEN_POLICY,
        ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8001/v1"),
        None,
    )


def test_policy_defaults_to_non_thinking_few_shot() -> None:
    assert (PolicyConfig().thinking, PolicyConfig().few_shot) == (False, True)


@pytest.mark.parametrize("kind", [ExpanderKind.POLICY, ExpanderKind.AUTOMATION_THEN_POLICY])
def test_policy_kinds_need_a_model(kind: ExpanderKind) -> None:
    with pytest.raises(ValueError):
        parse_run_config(f'[expander]\nkind = "{kind}"\n')


@pytest.mark.parametrize("policy", ["sample_count = 0\n", "server_urls = []\n", 'temperature = "hot"\n'])
def test_invalid_policy_section_is_rejected(policy: str) -> None:
    with pytest.raises(ValueError):
        parse_run_config(POLICY_SECTION + policy)
