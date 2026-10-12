"""The policy's lemma list for a node: retrieve candidates, check them on the first goal, keep the best k."""

import asyncio
import os
import time
from pathlib import Path

import torch

from lean_search.lean import LeanRepl, ProofState
from lean_search.retrieval.annotation import Applicability, annotate, lemma_line, order_lemmas
from lean_search.retrieval.config import RetrievalConfig
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.index import load_premise_index
from lean_search.retrieval.retriever import BatchingRetriever, GoalRetriever
from lean_search.retrieval.statistics import LemmaStatistics


def data_directory(config: RetrievalConfig) -> Path:
    return Path(config.data_directory or Path(os.environ["LEAN_SEARCH_DATA"]) / "retrieval")


class LemmaProvider:
    def __init__(self, config: RetrievalConfig, retriever: BatchingRetriever) -> None:
        self.config = config
        self.retriever = retriever
        self.statistics = LemmaStatistics(encoder=retriever.statistics)

    async def lemma_lines(self, state: ProofState, repl: LeanRepl) -> tuple[str, ...]:
        started = time.monotonic()
        premises = await self.retriever.retrieve(state.goals)
        self.statistics.retrieval_seconds += time.monotonic() - started
        annotation = await annotate(repl, state, premises, self.config.applicability)
        shown = order_lemmas(annotation.lemmas)[: self.config.lemma_count]
        statistics = self.statistics
        statistics.expansions += 1
        statistics.annotation_lean_seconds += annotation.lean_seconds
        statistics.annotation_tactic_calls += annotation.tactic_calls
        for lemma in annotation.lemmas:
            match lemma.check.applicability:
                case Applicability.CLOSES:
                    statistics.candidates_closing += 1
                case Applicability.LEAVES_GOALS:
                    statistics.candidates_leaving_goals += 1
                case Applicability.NO_MATCH:
                    statistics.candidates_without_match += 1
        statistics.shown_lemmas += len(shown)
        statistics.shown_closing += sum(lemma.check.applicability == Applicability.CLOSES for lemma in shown)
        statistics.shown_leaving_goals += sum(
            lemma.check.applicability == Applicability.LEAVES_GOALS for lemma in shown
        )
        return tuple(lemma_line(lemma, self.config.max_signature_characters) for lemma in shown)


def load_goal_retriever(config: RetrievalConfig) -> GoalRetriever:
    if config.device == "cpu":
        torch.set_num_threads(config.cpu_threads)
    # Beside a vLLM server only ~10% of the GPU is free: bfloat16 encoder and float16 index take about 1 GiB.
    dtype = torch.float32 if config.device == "cpu" else torch.bfloat16
    encoder = TextEncoder(config.retriever, config.device, dtype)
    index = load_premise_index(data_directory(config), config.retriever, config.device)
    return GoalRetriever(encoder, index)


async def load_lemma_provider(config: RetrievalConfig) -> LemmaProvider:
    retriever = await asyncio.to_thread(load_goal_retriever, config)
    return LemmaProvider(config, BatchingRetriever(retriever, config.candidate_count, config.max_batch_goals))
