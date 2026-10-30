"""What the policy saw and wrote at an expansion, kept for training: prompts, generated texts and tokens, spans."""

from collections.abc import Sequence
from dataclasses import dataclass

from lean_search.lean.text import TacticPiece

# Enough for comparing vLLM's log-probabilities with the trainer's; keeps the token records small.
LOG_PROBABILITY_DECIMALS = 4


@dataclass(frozen=True)
class CharacterSpan:
    start: int
    end: int


@dataclass(frozen=True)
class TokenSpan:
    start: int
    end: int


@dataclass(frozen=True)
class InsertedSpan:
    """Text the harness inserted into a sample instead of the model sampling it (masked in training)."""

    characters: CharacterSpan
    # The inserted tokens' indices in the sample's token ids; empty when the inserted text has no tokens.
    tokens: TokenSpan


@dataclass(frozen=True)
class SampledTokens:
    """A sample's tokens in the order the model saw them, sampled and inserted, with vLLM's log-probabilities."""

    # Decoded: the text without token-less inserted spans, maybe followed by an end of turn or a stop string it omits.
    token_ids: tuple[int, ...] = ()
    # Per token: vLLM's log-probability of the sampled token (rounded); None for a token the harness inserted.
    log_probabilities: tuple[float | None, ...] = ()
    inserted: tuple[InsertedSpan, ...] = ()

    def rounded(self) -> "SampledTokens":
        return SampledTokens(
            self.token_ids,
            tuple(
                None if value is None else round(value, LOG_PROBABILITY_DECIMALS) for value in self.log_probabilities
            ),
            self.inserted,
        )


@dataclass(frozen=True)
class SampledCompletion:
    """One policy sample as generated: its edge in the tree and the executed tactics' characters in its text."""

    edge_id: int
    # Everything the model generated after the prompt: explanation, fenced block, anything after it.
    text: str
    # Per executed top-level tactic after flattening, in execution order, its characters in `text`.
    tactic_spans: tuple[CharacterSpan, ...]
    # Generation stopped at the end of turn, which the text itself does not contain.
    ended_turn: bool = True
    # Empty in records written before tokens were kept.
    tokens: SampledTokens = SampledTokens()


@dataclass(frozen=True)
class ExpansionTexts:
    problem_name: str
    node_id: int
    # The exact prompt the samples were drawn from.
    prompt: str
    completions: tuple[SampledCompletion, ...]
    # The sampling settings behind the log-probabilities; None in records written before they were kept.
    temperature: float | None = None
    top_p: float | None = None
    # The published policy version that sampled them; None outside the GRPO loop and in older records.
    policy_version: int | None = None
    # The node's feedback round (policy.feedback): a second prompt, its samples a GRPO group of their own.
    feedback: bool = False


@dataclass(frozen=True)
class GeneratedText:
    """A sample behind a candidate: its text and where each character of the candidate's block came from."""

    text: str
    ended_turn: bool
    # For every character of the normalized block, and its end, the position in `text`.
    block_positions: tuple[int, ...]
    tokens: SampledTokens = SampledTokens()

    def span(self, tactic: TacticPiece) -> CharacterSpan:
        return CharacterSpan(self.block_positions[tactic.start], self.block_positions[tactic.end - 1] + 1)


@dataclass(frozen=True)
class UnparsedSample:
    """A sample without a usable block (none, cut off at the token cap, empty or forbidden)."""

    text: str
    ended_turn: bool
    reason: str
    tokens: SampledTokens = SampledTokens()


def tactic_spans(generated: GeneratedText, tactics: Sequence[TacticPiece]) -> tuple[CharacterSpan, ...]:
    return tuple(generated.span(tactic) for tactic in tactics)
