from dataclasses import dataclass, field

DEFAULT_RETRIEVER = "kaiyuy/leandojo-lean4-retriever-byt5-small"
DEFAULT_CHECK_TACTICS = ("exact {name}", "apply {name}", "rw [{name}]")


@dataclass(frozen=True)
class ApplicabilityConfig:
    # Tried in order on the first goal until one closes it; an empty tuple skips the check.
    tactics: tuple[str, ...] = DEFAULT_CHECK_TACTICS
    # Lean's maxHeartbeats units (the search default is 200000).
    heartbeats: int = 10_000
    # A wall-clock kill restarts the process, so this backstop stays well above what the heartbeats allow.
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class RetrievalConfig:
    # Lemmas shown in the prompt; 0 disables retrieval and leaves the prompt unchanged.
    lemma_count: int = 0
    # Retrieved and checked per expansion; the shown lemmas are the best of them by applicability, then score.
    candidate_count: int = 32
    retriever: str = DEFAULT_RETRIEVER
    # Holds signatures.jsonl and embeddings/; empty means $LEAN_SEARCH_DATA/retrieval.
    data_directory: str = ""
    device: str = "cpu"
    # Torch threads for encoding on the CPU; the Lean processes share the cores.
    cpu_threads: int = 8
    # Goals encoded per forward pass at most; concurrent expansions share one pass.
    max_batch_goals: int = 8
    max_signature_characters: int = 256
    applicability: ApplicabilityConfig = field(default_factory=ApplicabilityConfig)

    def __post_init__(self) -> None:
        if self.lemma_count < 0 or (self.enabled and self.candidate_count < self.lemma_count):
            raise ValueError("policy.retrieval needs 0 <= lemma_count <= candidate_count.")

    @property
    def enabled(self) -> bool:
        return self.lemma_count > 0
