"""Fine-tuning the retriever on competition steps: used premises are positives, in-batch and mined hard negatives."""

import dataclasses
import json
import random
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import torch
import torch.nn.functional as functional
import transformers

from lean_search.corpora.records import TacticExample, TracedStep
from lean_search.retrieval.config import DEFAULT_RETRIEVER
from lean_search.retrieval.encoder import MAX_LENGTH, byte_token_ids, length_batches, padded_batch, pooled_embeddings
from lean_search.retrieval.premises import (
    MINIF2F_OPEN_NAMESPACES,
    serialize_goals,
    step_premises,
    strip_leandojo_goal_count,
)
from lean_search.retrieval.sft_data import stable_fraction
from lean_search.training.sft import DistributedContext, learning_rate_factor

COMPETITION = "competition"
LEANDOJO = "leandojo"


@dataclass(frozen=True)
class RetrieverExample:
    key: str
    origin: str
    query: str
    gold: tuple[str, ...]
    # The current retriever's top candidates that are not gold, best first.
    hard_negatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrieverTrainingConfig:
    learning_rate: float = 3e-5
    warmup_fraction: float = 0.05
    minimum_learning_rate_ratio: float = 0.1
    weight_decay: float = 0.0
    max_gradient_norm: float = 1.0
    # Queries per batch on one GPU; each brings one positive and `hard_negatives` mined negatives.
    batch_examples: int = 16
    hard_negatives: int = 3
    max_steps: int = 3000
    # The step count is fixed after `probe_steps` so that training ends within this budget (0: no budget).
    max_training_seconds: float = 1200.0
    probe_steps: int = 20
    max_chunk_tokens: int = 16_384
    evaluation_interval_steps: int = 250
    validation_examples: int = 1024
    gradient_checkpointing: bool = True
    seed: int = 0


@dataclass(frozen=True)
class RetrieverDataConfig:
    # Taken in a fixed pseudo-random order; the training budget usually ends before one epoch.
    max_competition_examples: int = 48_000
    # LeanDojo novel-premises train states (disjoint from the guard's validation and test theorems).
    max_leandojo_examples: int = 12_000
    mined_candidates: int = 32
    seed: str = "phase4-retriever"


@dataclass(frozen=True)
class RetrieverFinetuneConfig:
    base_model: str = DEFAULT_RETRIEVER
    data: RetrieverDataConfig = field(default_factory=RetrieverDataConfig)
    training: RetrieverTrainingConfig = field(default_factory=RetrieverTrainingConfig)


@dataclass(frozen=True)
class TrainingBatch:
    queries: tuple[str, ...]
    premise_names: tuple[str, ...]
    # labels[i][j] is 1 when premise j is a gold premise of query i (ReProver's in-batch labels).
    labels: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class RetrieverStepRecord:
    step: int
    learning_rate: float
    loss: float
    gradient_norm: float
    seconds: float


@dataclass(frozen=True)
class RetrieverEvaluation:
    step: int
    loss: float
    # Within the validation batches: mean reciprocal rank of the first gold premise and top-1 accuracy.
    mean_reciprocal_rank: float
    top_one: float


@dataclass(frozen=True)
class RetrieverTrainingResult:
    # After the probe steps, the steps that fit the time budget.
    planned_steps: int
    steps: int
    examples: int
    training_seconds: float
    peak_memory_gib: float
    evaluations: tuple[RetrieverEvaluation, ...]


def competition_examples(steps: Iterable[TracedStep], known_names: Collection[str]) -> list[RetrieverExample]:
    """Steps that name a known premise, each (goals, gold) pair once."""
    seen: set[tuple[str, tuple[str, ...]]] = set()
    examples = []
    for step in steps:
        gold = step_premises(step.step, known_names, MINIF2F_OPEN_NAMESPACES)
        query = serialize_goals(step.goals_before)
        if gold and (query, gold) not in seen:
            seen.add((query, gold))
            examples.append(RetrieverExample(f"{step.proof_identifier}#{step.step_index}", COMPETITION, query, gold))
    return examples


def leandojo_examples(tactics: Iterable[TacticExample], known_names: Collection[str]) -> list[RetrieverExample]:
    examples = []
    for tactic in tactics:
        gold = tuple(
            dict.fromkeys(premise.full_name for premise in tactic.premises if premise.full_name in known_names)
        )
        if gold:
            query = strip_leandojo_goal_count(tactic.state_before)
            examples.append(RetrieverExample(tactic.identifier, LEANDOJO, query, gold))
    return examples


def in_fixed_order(examples: Sequence[RetrieverExample], seed: str) -> list[RetrieverExample]:
    return sorted(examples, key=lambda example: stable_fraction(seed, "retriever order", example.key))


def with_hard_negatives(example: RetrieverExample, ranked: Sequence[str]) -> RetrieverExample:
    gold = set(example.gold)
    return dataclasses.replace(example, hard_negatives=tuple(name for name in ranked if name not in gold))


def training_batch(
    examples: Sequence[RetrieverExample], hard_negatives: int, generator: random.Random
) -> TrainingBatch:
    """One sampled positive and up to `hard_negatives` mined negatives per query; every premise scores every query."""
    names: dict[str, None] = {}
    for example in examples:
        names[generator.choice(example.gold)] = None
        for name in generator.sample(example.hard_negatives, min(hard_negatives, len(example.hard_negatives))):
            names[name] = None
    premise_names = tuple(names)
    gold_sets = [set(example.gold) for example in examples]
    labels = tuple(tuple(1.0 if name in gold else 0.0 for name in premise_names) for gold in gold_sets)
    return TrainingBatch(tuple(example.query for example in examples), premise_names, labels)


def planned_batches(example_count: int, batch_examples: int, batches: int, seed: int) -> list[list[int]]:
    """Batches of example indices, reshuffled every epoch; a final partial batch of an epoch is dropped."""
    generator = random.Random(seed)
    planned: list[list[int]] = []
    while len(planned) < batches:
        order = list(range(example_count))
        generator.shuffle(order)
        for start in range(0, example_count - batch_examples + 1, batch_examples):
            planned.append(order[start : start + batch_examples])
    return planned[:batches]


def reciprocal_ranks(similarity: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """Per query, 1 / rank of its best-scored gold premise among the batch's premises."""
    best_gold = similarity.masked_fill(labels == 0, float("-inf")).max(dim=1, keepdim=True).values
    return 1.0 / (1 + (similarity > best_gold).sum(dim=1).float())


def embed_in_chunks(
    model: torch.nn.Module, texts: Sequence[str], max_length: int, max_chunk_tokens: int, device: torch.device
) -> torch.Tensor:
    """Embeddings with gradients, encoded in length-sorted chunks so that short premises are not padded to long ones."""
    token_ids = [byte_token_ids(text, max_length) for text in texts]
    chunks = length_batches([len(ids) for ids in token_ids], max_chunk_tokens)
    embedded = [
        pooled_embeddings(model, *padded_batch([token_ids[index] for index in chunk], device)) for chunk in chunks
    ]
    order = torch.tensor([index for chunk in chunks for index in chunk], device=device)
    return torch.cat(embedded)[torch.argsort(order)]


class BatchScorer(torch.nn.Module):
    """Cosine similarities of a batch's queries and premises in one forward pass, as DDP requires."""

    def __init__(self, model: transformers.T5EncoderModel, max_chunk_tokens: int) -> None:
        super().__init__()
        self.model = model
        self.max_chunk_tokens = max_chunk_tokens

    def forward(self, queries: list[str], premises: list[str]) -> torch.Tensor:
        device = next(self.model.parameters()).device
        with torch.autocast(device.type, dtype=torch.bfloat16):
            query_embeddings = embed_in_chunks(self.model, queries, MAX_LENGTH, self.max_chunk_tokens, device)
            premise_embeddings = embed_in_chunks(self.model, premises, MAX_LENGTH, self.max_chunk_tokens, device)
        return query_embeddings @ premise_embeddings.T


def batch_inputs(batch: TrainingBatch, premise_texts: dict[str, str]) -> tuple[list[str], list[str]]:
    return list(batch.queries), [premise_texts[name] for name in batch.premise_names]


@torch.no_grad()
def evaluate(
    step: int,
    scorer: BatchScorer,
    batches: Sequence[TrainingBatch],
    premise_texts: dict[str, str],
    device: torch.device,
) -> RetrieverEvaluation:
    scorer.eval()
    losses, ranks = [], []
    for batch in batches:
        similarity = scorer(*batch_inputs(batch, premise_texts))
        labels = torch.tensor(batch.labels, device=device)
        losses.append(functional.mse_loss(similarity, labels).item())
        ranks.append(reciprocal_ranks(similarity, labels))
    scorer.train()
    ranks_tensor = torch.cat(ranks)
    return RetrieverEvaluation(
        step, sum(losses) / len(losses), ranks_tensor.mean().item(), (ranks_tensor == 1).float().mean().item()
    )


def train_retriever(
    model_name: str,
    examples: Sequence[RetrieverExample],
    validation: Sequence[RetrieverExample],
    premise_texts: dict[str, str],
    config: RetrieverTrainingConfig,
    context: DistributedContext,
    output_directory: Path,
    on_step: Callable[[RetrieverStepRecord], None],
    on_evaluation: Callable[[RetrieverEvaluation], None],
) -> RetrieverTrainingResult:
    torch.manual_seed(config.seed)
    model = transformers.T5EncoderModel.from_pretrained(model_name).to(context.device)
    if config.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    scorer = BatchScorer(model, config.max_chunk_tokens)
    scorer.train()
    trained: torch.nn.Module = scorer
    if context.world_size > 1:
        trained = torch.nn.parallel.DistributedDataParallel(scorer, device_ids=[context.device.index])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    generator = random.Random(config.seed + context.rank)
    validation_generator = random.Random(config.seed)
    validation_batches = [
        training_batch(validation[start : start + config.batch_examples], config.hard_negatives, validation_generator)
        for start in range(0, min(len(validation), config.validation_examples), config.batch_examples)
    ]
    plan = planned_batches(len(examples), config.batch_examples, config.max_steps * context.world_size, config.seed)
    total_steps = config.max_steps
    warmup_steps = max(1, round(config.warmup_fraction * total_steps))
    evaluations: list[RetrieverEvaluation] = []

    def evaluate_now(step: int) -> None:
        if context.is_main:
            evaluations.append(evaluate(step, scorer, validation_batches, premise_texts, context.device))
            on_evaluation(evaluations[-1])
        if context.world_size > 1:
            torch.distributed.barrier()

    evaluate_now(0)
    on_gpu = context.device.type == "cuda"
    if on_gpu:
        torch.cuda.reset_peak_memory_stats(context.device)
    started = time.perf_counter()
    step = 0
    while step < total_steps:
        step_started = time.perf_counter()
        indices = plan[step * context.world_size + context.rank]
        batch = training_batch([examples[index] for index in indices], config.hard_negatives, generator)
        for group in optimizer.param_groups:
            group["lr"] = config.learning_rate * learning_rate_factor(
                step, warmup_steps, total_steps, config.minimum_learning_rate_ratio
            )
        similarity = trained(*batch_inputs(batch, premise_texts))
        loss = functional.mse_loss(similarity, torch.tensor(batch.labels, device=context.device))
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), config.max_gradient_norm).item()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        step += 1
        if step == config.probe_steps and config.max_training_seconds > 0:
            # Every rank must agree on the step count, so the main rank's estimate is broadcast.
            budget = torch.tensor(
                [min(total_steps, int(config.max_training_seconds / ((time.perf_counter() - started) / step)))],
                device=context.device,
            )
            if context.world_size > 1:
                torch.distributed.broadcast(budget, 0)
            total_steps = max(step, int(budget.item()))
            warmup_steps = max(1, round(config.warmup_fraction * total_steps))
        if context.is_main:
            on_step(
                RetrieverStepRecord(
                    step,
                    optimizer.param_groups[0]["lr"],
                    loss.item(),
                    gradient_norm,
                    time.perf_counter() - step_started,
                )
            )
        if step % config.evaluation_interval_steps == 0 and step < total_steps:
            evaluate_now(step)
    training_seconds = time.perf_counter() - started
    evaluate_now(step)
    if context.is_main:
        model.save_pretrained(output_directory)
    return RetrieverTrainingResult(
        planned_steps=total_steps,
        steps=step,
        examples=step * config.batch_examples * context.world_size,
        training_seconds=training_seconds,
        peak_memory_gib=torch.cuda.max_memory_allocated(context.device) / 2**30 if on_gpu else 0.0,
        evaluations=tuple(evaluations),
    )


def write_retriever_examples(path: Path, examples: Iterable[RetrieverExample]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_retriever_examples(path: Path) -> Iterator[RetrieverExample]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            fields["gold"] = tuple(fields["gold"])
            fields["hard_negatives"] = tuple(fields["hard_negatives"])
            yield RetrieverExample(**fields)
