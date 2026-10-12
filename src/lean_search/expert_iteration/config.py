"""Configuration of the statement pool and of one expert-iteration round, loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.expert_iteration.pool import SourceQuota, SourceSlice
from lean_search.search.config import RunConfig
from lean_search.search.records import from_json_object
from lean_search.training.sft_data import SourceWeight
from lean_search.value.labels import TreeLabelConfig


@dataclass(frozen=True)
class PoolConfig:
    # Paths relative to $LEAN_SEARCH_DATA.
    statements: str
    # Proof files whose statements the policy was trained on; such statements are left out.
    excluded_proofs: tuple[str, ...]
    seed: str
    sources: tuple[SourceQuota, ...]
    # A run config (automation only) for the pre-filter search.
    prefilter_search: str


@dataclass(frozen=True)
class AdapterReference:
    # The served LoRA name, and the adapter directory on the node.
    name: str
    path: str


@dataclass(frozen=True)
class PolicyDataConfig:
    # Automation steps are left out: the sweep tries them anyway, so policy samples spent on them are wasted.
    policy_steps_only: bool = True
    # Share of the SFT mixture's tokens taken from traced human proofs, against forgetting.
    replay_fraction: float = 0.5
    replay_sources: tuple[SourceWeight, ...] = ()
    max_prompt_tokens: int = 2048
    max_completion_tokens: int = 256
    validation_examples: int = 2000
    # The SFT data's seed selects the same traced validation steps, so validation losses compare across runs.
    validation_seed: str = "sft-v2"
    reference_tokenizer: str = "Qwen/Qwen3.5-2B"


@dataclass(frozen=True)
class PreferenceConfig:
    max_pairs_per_node: int = 4
    # Chosen and rejected steps both from the policy: the policy never needs to rank the sweep's tactics.
    policy_steps_only: bool = True
    # Rejected candidates also include siblings whose subtree was expanded completely without a proof.
    dead_subtrees: bool = True


@dataclass(frozen=True)
class ValueDataConfig:
    labels: TreeLabelConfig = field(default_factory=TreeLabelConfig)
    # A value data set under $LEAN_SEARCH_DATA/value replayed next to the tree labels.
    replay_data: str = "v0"
    # Share of the training examples taken from the replay data.
    replay_fraction: float = 0.5
    # Automation-only pre-filter runs: only their exact labels (proofs found) are valid for the policy's search.
    prefilter_runs: tuple[str, ...] = ()
    # Their examples as a share of the round's tree labels.
    prefilter_fraction: float = 0.1
    # Caps the distinct tree states (0: no cap) by sampling censored ones; exact and dead states are all kept.
    max_tree_states: int = 0


@dataclass(frozen=True)
class RoundDataConfig:
    # Runs under $LEAN_SEARCH_RUNS whose trees feed this round's data, e.g. every round so far.
    tree_runs: tuple[str, ...]
    seed: str
    # Statements held out of every training set, by hash; their proofs and trees give validation data.
    held_out_fraction: float = 0.02
    policy: PolicyDataConfig = field(default_factory=PolicyDataConfig)
    preferences: PreferenceConfig = field(default_factory=PreferenceConfig)
    value: ValueDataConfig = field(default_factory=ValueDataConfig)


@dataclass(frozen=True)
class RoundConfig:
    index: int
    # A prepared pool under $LEAN_SEARCH_DATA (phase6_pool.py) and the slice of each source this round searches.
    pool: str
    statements: tuple[SourceSlice, ...]
    base_model: str
    # The adapters that serve this round's search, and the run config of that search.
    policy: AdapterReference
    value: AdapterReference
    search_config: str
    data: RoundDataConfig
    # Training configs (experiments/phase2_sft.py, phase6_dpo.py, phase3_value.py); an empty DPO config skips DPO.
    policy_sft_config: str
    value_config: str
    policy_dpo_config: str
    # The adapters this round trains, and the miniF2F-valid run config that evaluates them together.
    next_policy: AdapterReference
    next_value: AdapterReference
    evaluation_config: str

    @property
    def statement_count(self) -> int:
        return sum(piece.count for piece in self.statements)

    @property
    def run_name(self) -> str:
        return f"phase6_round_{self.index}"

    @property
    def data_name(self) -> str:
        return f"round_{self.index}"

    def stage_run_name(self, stage: str) -> str:
        return f"{self.run_name}_{stage}"


def load_pool_config(path: Path) -> PoolConfig:
    return from_json_object(PoolConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def load_round_config(path: Path) -> RoundConfig:
    config = from_json_object(RoundConfig, tomllib.loads(path.read_text(encoding="utf-8")))
    if not config.statements or any(piece.offset < 0 or piece.count < 1 for piece in config.statements):
        raise ValueError("A round needs source slices with offset >= 0 and count >= 1.")
    if not 0 <= config.data.policy.replay_fraction < 1 or not 0 <= config.data.value.replay_fraction < 1:
        raise ValueError("Replay fractions must lie in [0, 1).")
    return config


def adapter_mismatches(run_config: RunConfig, policy: AdapterReference, value: AdapterReference) -> list[str]:
    """Where a search run config does not request the adapters the round serves for it."""
    requested = (("policy", run_config.policy.adapter, policy.name), ("value", run_config.value.adapter, value.name))
    return [f"{role} adapter {name!r}, served {served!r}" for role, name, served in requested if name != served]
