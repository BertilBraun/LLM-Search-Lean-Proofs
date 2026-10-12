"""Counters the search writes to policy.json for the lemma lists."""

from dataclasses import dataclass, field


@dataclass
class BatchStatistics:
    batches: int = 0
    goals: int = 0
    seconds: float = 0.0


@dataclass
class LemmaStatistics:
    expansions: int = 0
    # Time each expansion waited for its retrieval, including other expansions' goals in the same batch.
    retrieval_seconds: float = 0.0
    annotation_lean_seconds: float = 0.0
    annotation_tactic_calls: int = 0
    candidates_closing: int = 0
    candidates_closing_with_automation: int = 0
    candidates_leaving_goals: int = 0
    candidates_without_match: int = 0
    shown_lemmas: int = 0
    shown_closing: int = 0
    shown_closing_with_automation: int = 0
    shown_leaving_goals: int = 0
    encoder: BatchStatistics = field(default_factory=BatchStatistics)
