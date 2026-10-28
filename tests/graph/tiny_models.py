from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from lean_search.policy.prompts import END_OF_TURN, render_prompt
from lean_search.rl.policy_data import ExpansionTexts, SampledCompletion
from lean_search.rl.token_credit import CharacterSpan
from lean_search.search import StepSource, TreeRecord
from lean_search.search.texts import SampledTokens

# Every character of the prompts and completions in these tests has a code point under this.
VOCABULARY_SIZE = 9000
# The value model's "dead" bin needs a single token.
DEAD_TOKEN = VOCABULARY_SIZE - 1


class CharacterTokenizer:
    """One token per character, with offsets; "dead" is one token, as in the real tokenizers."""

    pad_token_id = 0

    def apply_chat_template(
        self, conversation: list[dict[str, str]], *, tokenize: bool, add_generation_prompt: bool, enable_thinking: bool
    ) -> str:
        turns = "".join(f"<|im_start|>{turn['role']}\n{turn['content']}<|im_end|>\n" for turn in conversation)
        return turns + "<|im_start|>assistant\n"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [DEAD_TOKEN] if text == "dead" else [ord(character) for character in text]

    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        return "".join(chr(token) for token in token_ids)

    def __call__(
        self, text: str, *, add_special_tokens: bool, return_offsets_mapping: bool
    ) -> Mapping[str, Sequence[object]]:
        return {
            "input_ids": [ord(character) for character in text],
            "offset_mapping": [(index, index + 1) for index in range(len(text))],
        }


def save_tiny_model(directory: Path) -> Path:
    """A two-layer random Qwen2, small enough to train on the CPU in seconds."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    config = transformers.Qwen2Config(
        vocab_size=VOCABULARY_SIZE,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=1024,
    )
    torch.manual_seed(0)
    transformers.Qwen2ForCausalLM(config).save_pretrained(directory)
    return directory


def sampled(edge_id: int, explanation: str, block: str) -> SampledCompletion:
    """One tactic per block, with token ids (one per character) and log-probabilities as the search records them."""
    text = f"{explanation}\n\n```lean\n{block}\n```"
    start = text.index("```lean\n") + len("```lean\n")
    token_ids = tuple(ord(character) for character in text + END_OF_TURN)
    tokens = SampledTokens(token_ids, tuple(-1.0 for _ in token_ids))
    return SampledCompletion(edge_id, text, (CharacterSpan(start, start + len(block)),), tokens=tokens)


def expansion_texts(record: TreeRecord) -> list[ExpansionTexts]:
    """Two recorded completions (different explanations) per policy edge, as the harness would write them."""
    tokenizer = CharacterTokenizer()
    texts = []
    for node in record.nodes:
        edges = [edge for edge in record.edges if edge.parent_id == node.node_id and edge.source == StepSource.POLICY]
        completions = tuple(
            sampled(edge.edge_id, explanation, edge.text) for edge in edges for explanation in ("First.", "Second.")
        )
        if completions:
            prompt = render_prompt(tokenizer, node.goals, visible=True)
            texts.append(ExpansionTexts(record.problem_name, node.node_id, prompt, completions, temperature=0.8))
    return texts
