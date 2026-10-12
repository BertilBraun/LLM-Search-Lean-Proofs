import dataclasses
from pathlib import Path

import pytest

from lean_search.retrieval.config import DEFAULT_CHECK_TACTICS, RetrievalConfig
from lean_search.search.config import load_run_config, parse_run_config

POLICY_SECTION = """
[expander]
kind = "automation_then_policy"

[policy]
model = "qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
"""
RETRIEVAL_SECTION = """
[policy.retrieval]
lemma_count = 8
candidate_count = 16

[policy.retrieval.applicability]
tactics = ["apply {name}"]
"""


def test_retrieval_is_disabled_by_default() -> None:
    assert not parse_run_config(POLICY_SECTION).policy.retrieval.enabled


def test_retrieval_section_is_parsed() -> None:
    retrieval = parse_run_config(POLICY_SECTION + RETRIEVAL_SECTION).policy.retrieval
    assert (retrieval.lemma_count, retrieval.candidate_count, retrieval.applicability.tactics) == (
        8,
        16,
        ("apply {name}",),
    )


def test_default_check_tries_exact_apply_and_rewrite() -> None:
    assert [template.format(name="foo") for template in DEFAULT_CHECK_TACTICS] == ["exact foo", "apply foo", "rw [foo]"]


@pytest.mark.parametrize(("lemma_count", "candidate_count"), [(-1, 32), (16, 8)])
def test_invalid_lemma_counts_are_rejected(lemma_count: int, candidate_count: int) -> None:
    with pytest.raises(ValueError):
        RetrievalConfig(lemma_count=lemma_count, candidate_count=candidate_count)


ABLATION_CONFIGS = {
    count: Path(__file__).parents[2] / "experiments" / "configs" / "retrieval" / f"phase4_lemmas_{count:02d}.toml"
    for count in (0, 8, 32)
}


@pytest.mark.parametrize("count", list(ABLATION_CONFIGS))
def test_shipped_ablation_arms_list_their_lemma_count(count: int) -> None:
    assert load_run_config(ABLATION_CONFIGS[count]).policy.retrieval.lemma_count == count


def test_shipped_ablation_arms_differ_only_in_retrieval() -> None:
    configs = [load_run_config(path) for path in ABLATION_CONFIGS.values()]
    without_retrieval = {
        repr(dataclasses.replace(config, policy=dataclasses.replace(config.policy, retrieval=RetrievalConfig())))
        for config in configs
    }
    assert len(without_retrieval) == 1
