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


def identifier_problem(identifier: str) -> str:
    """The problem name in a FoundProof identifier (run/problem)."""
    return identifier.split("/", 1)[1]


def proof_paths(record: TreeRecord) -> list[list[NodeRecord]]:
    """Root to each verified proof, the search's first proof first; failed verifications are not proved."""
    paths = []
    for proved in (node for node in record.nodes if node.status == NodeStatus.PROVED and not node.goals):
        path = [proved]
        while path[-1].parent_id is not None:
            path.append(record.nodes[path[-1].parent_id])
        paths.append(path[::-1])
    return paths


def path_proof(run: str, record: TreeRecord, path: list[NodeRecord]) -> FoundProof:
    steps = []
    for parent, child in itertools.pairwise(path):
        assert child.step is not None and child.source is not None, (record.problem_name, child.node_id)
        steps.append(
            ProofStep(parent.goals, child.step, child.source, child.log_probability, parent.node_id, child.node_id)
        )
    return FoundProof(run, record.problem_name, tuple(steps))


def found_proofs(run: str, record: TreeRecord) -> list[FoundProof]:
    """Every verified proof in the tree (the first and harvested ones), each step sequence once."""
    proofs: dict[tuple[str, ...], FoundProof] = {}
    for path in proof_paths(record):
        proof = path_proof(run, record, path)
        proofs.setdefault(tuple(step.step for step in proof.steps), proof)
    return list(proofs.values())


def found_proof(run: str, record: TreeRecord) -> FoundProof | None:
    """The search's first proof."""
    proofs = found_proofs(run, record)
    return proofs[0] if proofs else None


def uses_policy(proof: FoundProof) -> bool:
    """Automation-only proofs teach the policy nothing: the sweep finds them anyway."""
    return any(step.source == StepSource.POLICY for step in proof.steps)


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
