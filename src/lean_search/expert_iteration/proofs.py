"""Found proofs in search trees: the verified path, one shortest proof per statement, and policy SFT examples."""

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.search import NodeRecord, NodeStatus, StepSource, TreeRecord
from lean_search.training.sft_data import SftExample, sft_example

EXPERT_ITERATION_SOURCE = "expert_iteration"


@dataclass(frozen=True)
class ProofStep:
    goals: tuple[str, ...]
    # The step as the search executed it: the longest valid prefix of the candidate block.
    step: str
    source: StepSource
    log_probability: float | None
    node_id: int
    child_id: int


@dataclass(frozen=True)
class FoundProof:
    run: str
    problem_name: str
    steps: tuple[ProofStep, ...]

    @property
    def identifier(self) -> str:
        return f"{self.run}/{self.problem_name}"


def proof_path(record: TreeRecord) -> list[NodeRecord]:
    """Root to the verified proof; mark_proof_path labels exactly these nodes proved, failed verifications fail."""
    (proved,) = (node for node in record.nodes if node.status == NodeStatus.PROVED and not node.goals)
    path = [proved]
    while path[-1].parent_id is not None:
        path.append(record.nodes[path[-1].parent_id])
    return path[::-1]


def found_proof(run: str, record: TreeRecord) -> FoundProof | None:
    if not record.result.proved:
        return None
    path = proof_path(record)
    steps = []
    for parent, child in itertools.pairwise(path):
        assert child.step is not None and child.source is not None, (record.problem_name, child.node_id)
        steps.append(
            ProofStep(parent.goals, child.step, child.source, child.log_probability, parent.node_id, child.node_id)
        )
    return FoundProof(run, record.problem_name, tuple(steps))


def shortest_proofs(proofs: Iterable[FoundProof]) -> list[FoundProof]:
    """One proof per statement (problem name): the fewest steps, ties broken by run and step text."""
    best: dict[str, FoundProof] = {}
    for proof in proofs:
        current = best.get(proof.problem_name)
        if current is None or proof_rank(proof) < proof_rank(current):
            best[proof.problem_name] = proof
    return [best[name] for name in sorted(best)]


def proof_rank(proof: FoundProof) -> tuple[int, str, tuple[str, ...]]:
    return len(proof.steps), proof.run, tuple(step.step for step in proof.steps)


def policy_sft_examples(proofs: Iterable[FoundProof], policy_steps_only: bool) -> list[SftExample]:
    """(goals before, executed step) of each proof step; automation steps can be left out, the sweep tries them."""
    return [
        sft_example(EXPERT_ITERATION_SOURCE, proof.identifier, index, step.goals, step.step)
        for proof in proofs
        for index, step in enumerate(proof.steps)
        if not policy_steps_only or step.source == StepSource.POLICY
    ]


def proof_length_histogram(proofs: Sequence[FoundProof], buckets: int) -> tuple[int, ...]:
    """Proofs with 1, 2, ..., buckets - 1 and at least `buckets` steps."""
    counts = [0] * buckets
    for proof in proofs:
        counts[min(len(proof.steps), buckets) - 1] += 1
    return tuple(counts)
