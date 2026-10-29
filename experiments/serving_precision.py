"""Serving precision (DESIGN.md "Precision"; deployment/README.md "Serving precision"): the same sampled tokens scored
by bf16-merged, fp16-merged and runtime-LoRA vLLM servers against an fp32 transformers reference, each mode's generation
throughput, and whether small adapter updates survive serving.

    python experiments/serving_precision.py run --config experiments/configs/grpo/serving_precision.toml \
        [--name <run>] [--adapter <adapter>] [--gpus 1 2 3] [--prompts 200] [--samples-per-prompt 4]
    python experiments/serving_precision.py summary --run-directory $LEAN_SEARCH_RUNS/serving_precision/<run>

Everything goes to $LEAN_SEARCH_RUNS/serving_precision/<run>/ (summary/ holds summary.json and README.md); a rerun
keeps every score already written.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import datetime
import functools
import itertools
import json
import os
import random
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import peft
import safetensors.torch
import torch
import transformers

from lean_search.evaluation.serving_precision import (
    Agreement,
    Perturbation,
    PerturbationSize,
    ReferencePrecision,
    SampleSequence,
    ServingMode,
    TokenScores,
    UpdateVisibility,
    agreement,
    exact_fp32_compute,
    perturbation_size,
    reference_scores,
    sequence_lengths,
    served_completion_scores,
    sign_perturbation,
    update_visibility,
)
from lean_search.policy.adapters import (
    ADAPTER_CONFIG_FILE,
    ADAPTER_WEIGHTS_FILE,
    copy_tokenizer_and_processor_files,
    load_adapter_weights,
    load_base_model,
    lora_rank,
    lora_scale,
    merge_adapter,
    saved_adapter_weights,
)
from lean_search.policy.client import PolicyClient
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import MINIMUM_GENERATED_TOKENS
from lean_search.policy.prompts import render_prompt, stop_sequences
from lean_search.policy.server_control import publish_weights, replace_adapter
from lean_search.reasoning.records import read_records, write_records
from lean_search.reasoning.states import ReasoningState
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
SERVE_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "serve_model.sh"
STOP_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "stop_model.sh"
BASE_ADAPTER = "base"
REPEAT = "repeat"
REQUEST_TIMEOUT_SECONDS = 1800.0
SAMPLES_POLL_SECONDS = 10.0
# Relative cost of a reference pass, for spreading them over the GPUs.
REFERENCE_COST = {ReferencePrecision.FP32: 4, ReferencePrecision.TRAINER_BF16: 1}


@dataclass(frozen=True)
class ServingPrecisionConfig:
    name: str
    # The policy's LoRA adapter on base_model (fp32 weights), as the loop continues it.
    adapter: str
    base_model: str = "Qwen/Qwen3.5-4B"
    # ReasoningState lines under $LEAN_SEARCH_RUNS; prompts are their goals in the search's visible-mode prompt.
    states: str = "phase5_eval_visible_student_v2_visible/states.jsonl"
    # Its [policy] gives the prompt format, temperature, top-p and max_tokens.
    search_config: str = "experiments/configs/grpo/search/visible_student_v2.toml"
    prompts: int = 200
    samples_per_prompt: int = 4
    seed: int = 0
    # One vLLM mode per GPU at a time; the reference passes are spread over the same GPUs afterwards.
    gpus: tuple[int, ...] = (1, 2, 3)
    first_port: int = 8950
    modes: tuple[ServingMode, ...] = tuple(ServingMode)
    references: tuple[ReferencePrecision, ...] = tuple(ReferencePrecision)
    # Top raw log-probabilities per position for the tempered estimate (the server's --max-logprobs).
    top_logprobs: int = 20
    scoring_concurrency: int = 32
    max_model_length: int = 8192
    gpu_memory_utilization: float = 0.90
    # Fixed generation workload per mode: the first prompts, n samples each, all in flight, ignore_eos.
    throughput_prompts: int = 64
    throughput_samples: int = 8
    throughput_max_tokens: int = 512
    reference_micro_batch_tokens: int = 4096
    # Merged weights, deleted after use.
    temporary_directory: str = "/dev/shm/serving_precision"
    merge_device: str = "cpu"
    perturbations: tuple[Perturbation, ...] = ()


@dataclass(frozen=True)
class PromptRecord:
    prompt_index: int
    state_identifier: str
    prompt: str
    prompt_token_ids: tuple[int, ...]
    max_tokens: int


@dataclass(frozen=True)
class Throughput:
    requests: int
    sequences: int
    completion_tokens: int
    seconds: float
    tokens_per_second: float


@dataclass(frozen=True)
class ReferenceJob:
    precision: ReferencePrecision
    adapter: str


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def prompts(self) -> Path:
        return self.root / "prompts.jsonl"

    @property
    def samples(self) -> Path:
        return self.root / "samples.jsonl"

    @property
    def summary(self) -> Path:
        return self.root / "summary"

    def scores(self, source: str, adapter: str) -> Path:
        return self.root / "scores" / f"{source}__{adapter}.npz"

    def throughput(self, mode: ServingMode) -> Path:
        return self.root / "throughput" / f"{mode.value}.json"

    def perturbation(self, name: str) -> Path:
        return self.root / "perturbations" / name

    def failure(self, source: str) -> Path:
        return self.root / "failures" / f"{source}.txt"


def log(message: str) -> None:
    print(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def policy_config(config: ServingPrecisionConfig) -> PolicyConfig:
    return load_run_config(REPOSITORY_DIRECTORY / config.search_config).policy


def adapter_names(config: ServingPrecisionConfig) -> list[str]:
    return [BASE_ADAPTER, *(perturbation.name for perturbation in config.perturbations)]


def adapter_directory(config: ServingPrecisionConfig, paths: RunPaths, adapter: str) -> Path:
    return Path(config.adapter) if adapter == BASE_ADAPTER else paths.perturbation(adapter)


def write_scores(path: Path, scores: TokenScores) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    arrays = {"raw": scores.raw, "tempered_top_k": scores.tempered_top_k}
    if scores.tempered is not None:
        arrays["tempered"] = scores.tempered
    with temporary.open("wb") as handle:
        np.savez(handle, **arrays)
    temporary.replace(path)


def read_scores(path: Path) -> TokenScores | None:
    if not path.exists():
        return None
    with np.load(path) as arrays:
        return TokenScores(arrays["raw"], arrays["tempered_top_k"], arrays.get("tempered"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(value), encoding="utf-8")


def record_failure(paths: RunPaths, source: str, error: BaseException) -> None:
    log(f"{source} failed: {error!r}")
    path = paths.failure(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repr(error), encoding="utf-8")


def prepare_prompts(config: ServingPrecisionConfig, paths: RunPaths) -> list[PromptRecord]:
    if paths.prompts.exists():
        return read_records(paths.prompts, PromptRecord)
    policy = policy_config(config)
    tokenizer = transformers.AutoTokenizer.from_pretrained(policy.tokenizer)
    states = read_records(RUNS_DIRECTORY / config.states, ReasoningState)
    chosen = random.Random(config.seed).sample(states, min(config.prompts, len(states)))
    records = []
    for state in chosen:
        prompt = render_prompt(
            tokenizer,
            state.goals,
            few_shot=policy.few_shot,
            thinking=policy.thinking,
            thinking_instruction=policy.thinking_instruction,
            visible=policy.visible_reasoning,
        )
        prompt_token_ids = tuple(tokenizer.encode(prompt, add_special_tokens=False))
        max_tokens = min(policy.max_tokens, config.max_model_length - len(prompt_token_ids))
        if max_tokens >= MINIMUM_GENERATED_TOKENS:
            records.append(PromptRecord(len(records), state.identifier, prompt, prompt_token_ids, max_tokens))
    write_records(paths.prompts, records)
    log(f"{len(records)} prompts from {len(states)} states")
    return records


def prepare_perturbations(config: ServingPrecisionConfig, paths: RunPaths) -> None:
    adapter = Path(config.adapter)
    weights = safetensors.torch.load_file(adapter / ADAPTER_WEIGHTS_FILE)
    for perturbation in config.perturbations:
        directory = paths.perturbation(perturbation.name)
        if (directory / "size.json").exists():
            continue
        perturbed = sign_perturbation(weights, perturbation)
        directory.mkdir(parents=True, exist_ok=True)
        safetensors.torch.save_file(perturbed, directory / ADAPTER_WEIGHTS_FILE)
        shutil.copyfile(adapter / ADAPTER_CONFIG_FILE, directory / ADAPTER_CONFIG_FILE)
        size = perturbation_size(weights, perturbed, lora_scale(adapter), perturbation.element_step)
        write_json(directory / "size.json", size)
        log(f"Perturbation {perturbation.name}: {size}")


def merge_fp16(base_model: str, adapter: Path, output: Path) -> None:
    """Merged in fp32, then cast: one rounding, to the fp16 grid."""
    model = load_base_model(base_model, "cpu").float()
    merged = peft.PeftModel.from_pretrained(model, adapter).merge_and_unload().to(torch.float16)
    merged.config.dtype = torch.float16
    merged.save_pretrained(output)
    copy_tokenizer_and_processor_files(base_model, output)


class ModeSession:
    """One vLLM mode on one GPU: its server, its weights per adapter, its scores."""

    def __init__(self, config: ServingPrecisionConfig, paths: RunPaths, mode: ServingMode, gpu: int, port: int) -> None:
        self.config = config
        self.paths = paths
        self.mode = mode
        self.gpu = gpu
        self.server_name = f"precision-{mode.value}"
        self.server_url = f"http://127.0.0.1:{port}/v1"
        self.port = port
        self.temporary = Path(config.temporary_directory) / config.name / mode.value
        self.started = False
        self.served_adapter = BASE_ADAPTER

    def pending(self) -> bool:
        scored = all(
            self.paths.scores(self.mode.value, adapter).exists()
            for adapter in [*adapter_names(self.config), f"{BASE_ADAPTER}_{REPEAT}"]
        )
        return not (scored and self.paths.throughput(self.mode).exists())

    @property
    def request_model(self) -> str:
        return self.served_adapter if self.mode == ServingMode.LORA_BF16 else self.server_name

    def merged_weights(self, adapter: str) -> Path:
        output = self.temporary / adapter
        shutil.rmtree(output, ignore_errors=True)
        source = adapter_directory(self.config, self.paths, adapter)
        started = time.monotonic()
        match self.mode:
            case ServingMode.BF16_MERGED:
                merge_adapter(self.config.base_model, source, output, self.config.merge_device)
            case ServingMode.FP16_MERGED:
                merge_fp16(self.config.base_model, source, output)
        log(f"{self.mode.value}: merged {adapter} in {time.monotonic() - started:.0f} s")
        return output

    def start(self) -> None:
        arguments = ["--logprobs-mode", "processed_logprobs", "--max-logprobs", str(self.config.top_logprobs)]
        match self.mode:
            case ServingMode.BF16_MERGED:
                weights = str(self.merged_weights(BASE_ADAPTER))
                arguments += ["--no-enable-lora"]
            case ServingMode.FP16_MERGED:
                weights = str(self.merged_weights(BASE_ADAPTER))
                arguments += ["--no-enable-lora", "--dtype", "float16"]
            case ServingMode.LORA_BF16:
                weights = self.config.base_model
        environment = os.environ | {
            "GPU_MEMORY_UTILIZATION": str(self.config.gpu_memory_utilization),
            "MAX_MODEL_LEN": str(self.config.max_model_length),
            "MAX_LORA_RANK": str(lora_rank(Path(self.config.adapter))),
        }
        # A server left by an interrupted run would make serve_model.sh refuse the name.
        subprocess.run([str(STOP_SCRIPT), self.server_name], check=False, stderr=subprocess.DEVNULL)
        command = [str(SERVE_SCRIPT), self.server_name, weights, str(self.gpu), str(self.port), *arguments]
        subprocess.run(command, check=True, env=environment)
        self.started = True
        if self.mode == ServingMode.LORA_BF16:
            asyncio.run(replace_adapter(self.server_url, BASE_ADAPTER, Path(self.config.adapter).resolve()))

    def stop(self) -> None:
        if self.started:
            subprocess.run([str(STOP_SCRIPT), self.server_name], check=False)
            self.started = False
        shutil.rmtree(self.temporary, ignore_errors=True)

    def serve_adapter(self, adapter: str) -> None:
        if adapter == self.served_adapter:
            return
        match self.mode:
            case ServingMode.LORA_BF16:
                directory = adapter_directory(self.config, self.paths, adapter).resolve()
                asyncio.run(replace_adapter(self.server_url, adapter, directory))
            case ServingMode.BF16_MERGED | ServingMode.FP16_MERGED:
                weights = self.merged_weights(adapter)
                asyncio.run(publish_weights(self.server_url, weights.resolve()))
                for other in self.temporary.iterdir():
                    if other.name != adapter:
                        shutil.rmtree(other, ignore_errors=True)
        self.served_adapter = adapter
        log(f"{self.mode.value}: serving {adapter}")

    def measure(self, prompts: Sequence[PromptRecord], samples: Sequence[SampleSequence]) -> None:
        temperature = policy_config(self.config).temperature
        if not self.paths.throughput(self.mode).exists():
            throughput = asyncio.run(measure_throughput(self.config, self.server_url, self.request_model, prompts))
            write_json(self.paths.throughput(self.mode), throughput)
            log(f"{self.mode.value}: {throughput}")
        for adapter, file_name in [
            (BASE_ADAPTER, BASE_ADAPTER),
            (BASE_ADAPTER, f"{BASE_ADAPTER}_{REPEAT}"),
            *((name, name) for name in adapter_names(self.config)[1:]),
        ]:
            path = self.paths.scores(self.mode.value, file_name)
            if path.exists():
                continue
            self.serve_adapter(adapter)
            started = time.monotonic()
            scores = asyncio.run(
                score_sequences(self.config, self.server_url, self.request_model, samples, temperature)
            )
            write_scores(path, scores)
            log(f"{self.mode.value}: scored {file_name} in {time.monotonic() - started:.0f} s")


async def generate_samples(
    config: ServingPrecisionConfig, server_url: str, model: str, prompts: Sequence[PromptRecord]
) -> list[SampleSequence]:
    policy = policy_config(config)

    async def generate(client: PolicyClient, record: PromptRecord) -> list[SampleSequence]:
        generation = await client.generate(
            record.prompt,
            sample_count=config.samples_per_prompt,
            max_tokens=record.max_tokens,
            temperature=policy.temperature,
            top_p=policy.top_p,
            stop=stop_sequences(policy.thinking, policy.visible_reasoning),
            seed=config.seed + record.prompt_index,
        )
        if generation.prompt_token_count != len(record.prompt_token_ids):
            raise ValueError(f"Prompt {record.prompt_index}: the server tokenized the prompt differently")
        return [
            SampleSequence(
                record.prompt_index,
                index,
                record.prompt_token_ids,
                sample.tokens.token_ids,
                tuple(float(value) for value in sample.tokens.log_probabilities),
                sample.finish_reason,
            )
            for index, sample in enumerate(generation.samples)
        ]

    async with PolicyClient(server_url, model, timeout_seconds=REQUEST_TIMEOUT_SECONDS) as client:
        generated = await asyncio.gather(*(generate(client, record) for record in prompts))
    return [sequence for sequences in generated for sequence in sequences]


async def measure_throughput(
    config: ServingPrecisionConfig, server_url: str, model: str, prompts: Sequence[PromptRecord]
) -> Throughput:
    policy = policy_config(config)
    workload = prompts[: config.throughput_prompts]
    async with PolicyClient(server_url, model, timeout_seconds=REQUEST_TIMEOUT_SECONDS) as client:
        await client.generate(workload[0].prompt, sample_count=1, max_tokens=16, temperature=policy.temperature)
        started = time.monotonic()
        generations = await asyncio.gather(
            *(
                client.generate(
                    record.prompt,
                    sample_count=config.throughput_samples,
                    max_tokens=config.throughput_max_tokens,
                    temperature=policy.temperature,
                    top_p=policy.top_p,
                    seed=config.seed + record.prompt_index,
                    ignore_eos=True,
                )
                for record in workload
            )
        )
        seconds = time.monotonic() - started
    tokens = sum(generation.completion_token_count for generation in generations)
    return Throughput(len(workload), len(workload) * config.throughput_samples, tokens, seconds, tokens / seconds)


async def score_sequences(
    config: ServingPrecisionConfig,
    server_url: str,
    model: str,
    sequences: Sequence[SampleSequence],
    temperature: float,
) -> TokenScores:
    limit = asyncio.Semaphore(config.scoring_concurrency)
    failures = 0

    async def score(http: httpx.AsyncClient, sequence: SampleSequence) -> TokenScores:
        nonlocal failures
        body = {
            "model": model,
            "prompt": [*sequence.prompt_token_ids, *sequence.completion_token_ids],
            "max_tokens": 1,
            "temperature": 1.0,
            "prompt_logprobs": config.top_logprobs,
            "return_token_ids": True,
        }
        async with limit:
            response = await http.post("/completions", json=body)
        if response.status_code >= 500:
            # An fp16 overflow makes vLLM fail the request (NaN is not JSON); the tokens count as non-finite.
            failures += 1
            missing = np.full(len(sequence.completion_token_ids), np.nan)
            return TokenScores(missing, missing)
        response.raise_for_status()
        (choice,) = response.json()["choices"]
        return served_completion_scores(
            choice["prompt_logprobs"], choice["prompt_token_ids"], sequence, config.top_logprobs, temperature
        )

    async with httpx.AsyncClient(base_url=server_url, timeout=REQUEST_TIMEOUT_SECONDS) as http:
        scored = await asyncio.gather(*(score(http, sequence) for sequence in sequences))
    if failures:
        log(f"{model}: {failures} of {len(sequences)} scoring requests failed on the server")
    return TokenScores(
        np.concatenate([part.raw for part in scored]), np.concatenate([part.tempered_top_k for part in scored])
    )


def safely(paths: RunPaths, session: ModeSession, step: str, action: Callable[[], None]) -> bool:
    try:
        action()
        return True
    except Exception as error:  # noqa: BLE001 - one failing mode must not end the others
        record_failure(paths, session.mode.value, RuntimeError(f"{step}: {error!r}"))
        session.stop()
        return False


def start_session(paths: RunPaths, session: ModeSession) -> bool:
    return safely(paths, session, "start", session.start)


def measure_session(
    paths: RunPaths, prompts: Sequence[PromptRecord], samples: Sequence[SampleSequence], session: ModeSession
) -> bool:
    return safely(paths, session, "measure", functools.partial(session.measure, prompts, samples))


def run_modes(config: ServingPrecisionConfig, paths: RunPaths, prompts: Sequence[PromptRecord]) -> None:
    assert config.modes[0] == ServingMode.BF16_MERGED, "the bf16-merged server generates the sample set"
    sessions = [
        ModeSession(config, paths, mode, config.gpus[index % len(config.gpus)], config.first_port + index)
        for index, mode in enumerate(config.modes)
    ]
    pending = [session for session in sessions if session.pending() or not paths.samples.exists()]
    with ThreadPoolExecutor(len(config.gpus)) as pool:
        for wave_start in range(0, len(pending), len(config.gpus)):
            wave = pending[wave_start : wave_start + len(config.gpus)]
            try:
                started = list(pool.map(functools.partial(start_session, paths), wave))
                running = [session for session, ok in zip(wave, started, strict=True) if ok]
                if not paths.samples.exists():
                    generators = [session for session in running if session.mode == ServingMode.BF16_MERGED]
                    if not generators:
                        raise RuntimeError(f"The bf16-merged server did not start (see {paths.failure('bf16_merged')})")
                    (generator,) = generators
                    log(f"Generating {config.samples_per_prompt} samples for each of {len(prompts)} prompts")
                    samples = asyncio.run(
                        generate_samples(config, generator.server_url, generator.request_model, prompts)
                    )
                    write_records(paths.samples, samples)
                    log(f"{len(samples)} samples, {sum(sequence_lengths(samples))} completion tokens")
                samples = read_records(paths.samples, SampleSequence)
                list(pool.map(functools.partial(measure_session, paths, prompts, samples), running))
            finally:
                for session in wave:
                    session.stop()


def reference_assignments(jobs: Sequence[ReferenceJob], gpu_count: int) -> list[list[ReferenceJob]]:
    """Costliest first onto the least loaded GPU; each GPU's jobs grouped by precision (one model load each)."""
    bins: list[list[ReferenceJob]] = [[] for _ in range(gpu_count)]
    loads = [0] * gpu_count
    for job in sorted(jobs, key=lambda job: -REFERENCE_COST[job.precision]):
        target = loads.index(min(loads))
        bins[target].append(job)
        loads[target] += REFERENCE_COST[job.precision]
    return [sorted(jobs, key=lambda job: job.precision.value) for jobs in bins if jobs]


def run_references(config: ServingPrecisionConfig, paths: RunPaths) -> None:
    jobs = [
        ReferenceJob(precision, adapter)
        for precision in config.references
        for adapter in adapter_names(config)
        if not paths.scores(precision.value, adapter).exists()
    ]
    processes = []
    for gpu, assigned in zip(config.gpus, reference_assignments(jobs, len(config.gpus)), strict=False):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "reference",
            "--run-directory",
            str(paths.root),
            "--jobs",
            *(f"{job.precision.value}:{job.adapter}" for job in assigned),
        ]
        log(f"Reference on GPU {gpu}: {' '.join(command[5:])}")
        processes.append(subprocess.Popen(command, env=os.environ | {"CUDA_VISIBLE_DEVICES": str(gpu)}))
    for process in processes:
        if process.wait() != 0:
            log(f"A reference process exited with {process.returncode}")


def load_reference_model(base_model: str, adapter: Path, precision: ReferencePrecision) -> peft.PeftModel:
    model = load_base_model(base_model, "cpu")
    if precision == ReferencePrecision.FP32:
        model = model.float()
    # The vision tower is never used on text and would take ~2 GB of the fp32 model's room.
    if hasattr(model.model, "visual"):
        del model.model.visual
    # PEFT keeps the LoRA weights in fp32 on a bf16 base (autocast_adapter_dtype), as the trainer has them.
    reference = peft.PeftModel.from_pretrained(model.to("cuda"), adapter)
    reference.eval()
    return reference


def reference_jobs(paths: RunPaths, jobs: Sequence[ReferenceJob]) -> None:
    config = read_config(paths)
    samples = read_records(paths.samples, SampleSequence)
    temperature = policy_config(config).temperature
    pad_token_id = transformers.AutoTokenizer.from_pretrained(config.base_model).pad_token_id
    device = torch.device("cuda")
    for precision, group in itertools.groupby(jobs, key=lambda job: job.precision):
        reference = load_reference_model(config.base_model, Path(config.adapter), precision)
        for job in group:
            weights = saved_adapter_weights(adapter_directory(config, paths, job.adapter), device)
            load_adapter_weights(reference, weights)
            started = time.monotonic()
            compute = exact_fp32_compute() if precision == ReferencePrecision.FP32 else contextlib.nullcontext()
            with compute:
                scores = reference_scores(
                    reference.get_base_model(),
                    samples,
                    precision,
                    temperature,
                    config.top_logprobs,
                    config.reference_micro_batch_tokens,
                    pad_token_id,
                    device,
                )
            write_scores(paths.scores(precision.value, job.adapter), scores)
            log(f"{precision.value}: scored {job.adapter} in {time.monotonic() - started:.0f} s")
        del reference
        torch.cuda.empty_cache()


@dataclass(frozen=True)
class SampleSetReport:
    prompts: int
    sequences: int
    completion_tokens: int
    mean_completion_tokens: float
    # Cut off at max_tokens; the search would force their answers, here they stay as sampled.
    cut_off_sequences: int


@dataclass(frozen=True)
class UpdateReport:
    perturbation: str
    raw: UpdateVisibility
    tempered_top_k: UpdateVisibility


@dataclass(frozen=True)
class SourceReport:
    # A vLLM mode, or trainer_bf16 (the trainer's own compute precision).
    source: str
    raw: Agreement | None
    tempered_top_k: Agreement | None
    # Exact tempered log-probabilities against the reference's; only trainer_bf16 has them.
    tempered: Agreement | None
    # The base scored twice by the same server: its run-to-run noise at temperature 1.
    repeat: Agreement | None
    throughput: Throughput | None
    updates: tuple[UpdateReport, ...]
    failure: str | None


@dataclass(frozen=True)
class PerturbationReport:
    perturbation: Perturbation
    size: PerturbationSize


@dataclass(frozen=True)
class SamplerReport:
    """The generating server's processed log-probabilities of its own samples, as the loop records them."""

    against_fp32: Agreement
    against_trainer_bf16: Agreement | None
    # Alignment check: the same tokens rescored by the same weights through prompt_logprobs (top-k estimate).
    against_bf16_merged_scoring: Agreement | None


@dataclass(frozen=True)
class ServingPrecisionReport:
    name: str
    base_model: str
    adapter: str
    temperature: float
    top_logprobs: int
    sample_set: SampleSetReport
    # The fp32 reference's top-k estimate against its exact tempered log-probabilities.
    estimator_floor: Agreement
    sampler: SamplerReport
    perturbations: tuple[PerturbationReport, ...]
    sources: tuple[SourceReport, ...]


def update_report(
    perturbation: str,
    served_base: TokenScores,
    served: TokenScores,
    reference_base: TokenScores,
    reference: TokenScores,
    lengths: Sequence[int],
) -> UpdateReport:
    return UpdateReport(
        perturbation,
        update_visibility(served_base.raw, served.raw, reference_base.raw, reference.raw, lengths),
        update_visibility(
            served_base.tempered_top_k,
            served.tempered_top_k,
            reference_base.tempered_top_k,
            reference.tempered_top_k,
            lengths,
        ),
    )


def source_report(
    config: ServingPrecisionConfig, paths: RunPaths, source: str, lengths: Sequence[int], reference_base: TokenScores
) -> SourceReport:
    base = read_scores(paths.scores(source, BASE_ADAPTER))
    repeat = read_scores(paths.scores(source, f"{BASE_ADAPTER}_{REPEAT}"))
    failure = paths.failure(source).read_text(encoding="utf-8") if paths.failure(source).exists() else None
    throughput_path = paths.root / "throughput" / f"{source}.json"
    throughput = (
        from_json_object(Throughput, json.loads(throughput_path.read_text(encoding="utf-8")))
        if throughput_path.exists()
        else None
    )
    updates = []
    for perturbation in config.perturbations:
        served = read_scores(paths.scores(source, perturbation.name))
        reference = read_scores(paths.scores(ReferencePrecision.FP32.value, perturbation.name))
        if base is not None and served is not None and reference is not None:
            updates.append(update_report(perturbation.name, base, served, reference_base, reference, lengths))
    tempered = None
    if base is not None and base.tempered is not None:
        tempered = agreement(base.tempered, reference_base.tempered, lengths)
    return SourceReport(
        source=source,
        raw=None if base is None else agreement(base.raw, reference_base.raw, lengths),
        tempered_top_k=None if base is None else agreement(base.tempered_top_k, reference_base.tempered_top_k, lengths),
        tempered=tempered,
        repeat=None if base is None or repeat is None else agreement(repeat.raw, base.raw, lengths),
        throughput=throughput,
        updates=tuple(updates),
        failure=failure,
    )


def summarize(paths: RunPaths) -> ServingPrecisionReport:
    config = read_config(paths)
    prompts = read_records(paths.prompts, PromptRecord)
    samples = read_records(paths.samples, SampleSequence)
    lengths = sequence_lengths(samples)
    reference_base = read_scores(paths.scores(ReferencePrecision.FP32.value, BASE_ADAPTER))
    assert reference_base is not None and reference_base.tempered is not None, "the fp32 reference of the base"
    sampled = np.array([value for sample in samples for value in sample.sampled_log_probabilities])
    trainer_base = read_scores(paths.scores(ReferencePrecision.TRAINER_BF16.value, BASE_ADAPTER))
    bf16_base = read_scores(paths.scores(ServingMode.BF16_MERGED.value, BASE_ADAPTER))
    sampler = SamplerReport(
        against_fp32=agreement(sampled, reference_base.tempered, lengths),
        against_trainer_bf16=None
        if trainer_base is None or trainer_base.tempered is None
        else agreement(sampled, trainer_base.tempered, lengths),
        against_bf16_merged_scoring=None
        if bf16_base is None
        else agreement(sampled, bf16_base.tempered_top_k, lengths),
    )
    sources = [ReferencePrecision.TRAINER_BF16.value, *(mode.value for mode in config.modes)]
    perturbations = tuple(
        PerturbationReport(
            perturbation,
            from_json_object(
                PerturbationSize,
                json.loads((paths.perturbation(perturbation.name) / "size.json").read_text(encoding="utf-8")),
            ),
        )
        for perturbation in config.perturbations
    )
    return ServingPrecisionReport(
        name=config.name,
        base_model=config.base_model,
        adapter=config.adapter,
        temperature=policy_config(config).temperature,
        top_logprobs=config.top_logprobs,
        sample_set=SampleSetReport(
            prompts=len(prompts),
            sequences=len(samples),
            completion_tokens=sum(lengths),
            mean_completion_tokens=float(np.mean(lengths)),
            cut_off_sequences=sum(sample.finish_reason == "length" for sample in samples),
        ),
        estimator_floor=agreement(reference_base.tempered_top_k, reference_base.tempered, lengths),
        sampler=sampler,
        perturbations=perturbations,
        sources=tuple(source_report(config, paths, source, lengths, reference_base) for source in sources),
    )


def number(value: float | None, digits: int = 4) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


AGREEMENT_HEADER = ("mean abs", "p95 abs", "max abs", "mean (served - ref)", "k3 KL", "seq mean abs")


def agreement_cells(value: Agreement | None) -> list[str]:
    if value is None:
        return ["-"] * len(AGREEMENT_HEADER)
    return [
        number(value.mean_absolute_difference),
        number(value.p95_absolute_difference),
        number(value.max_absolute_difference, 3),
        number(value.mean_difference),
        f"{value.k3_kl:.2e}",
        number(value.sequence_mean_absolute_difference, 3),
    ]


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join([*lines, *("| " + " | ".join(row) + " |" for row in rows)])


def render(report: ServingPrecisionReport) -> str:
    sample_set = report.sample_set
    floor = report.estimator_floor
    raw_rows = [
        [
            source.source,
            *agreement_cells(source.raw),
            number(source.repeat.mean_absolute_difference if source.repeat else None),
            "-" if source.throughput is None else f"{source.throughput.tokens_per_second:.0f}",
            "-" if source.raw is None else str(source.raw.non_finite_tokens),
        ]
        for source in report.sources
    ]
    tempered_rows = [[source.source, *agreement_cells(source.tempered_top_k)] for source in report.sources]
    tempered_rows += [
        [f"{source.source} (exact)", *agreement_cells(source.tempered)] for source in report.sources if source.tempered
    ]
    sampler = report.sampler
    sampler_rows = [
        ["fp32 reference (exact)", *agreement_cells(sampler.against_fp32)],
        ["trainer bf16 (exact)", *agreement_cells(sampler.against_trainer_bf16)],
        ["bf16-merged rescored (top-k estimate)", *agreement_cells(sampler.against_bf16_merged_scoring)],
    ]
    size_rows = [
        [
            item.perturbation.name,
            f"{item.size.element_step:.1e}",
            f"{item.size.relative_norm:.2e}",
            f"{item.size.merged_update_rms:.2e}",
            f"{item.size.adapter_merged_rms:.2e}",
        ]
        for item in report.perturbations
    ]
    update_rows = [
        [
            source.source,
            update.perturbation,
            f"{update.raw.reference_change_mean_absolute:.2e}",
            f"{update.raw.served_change_mean_absolute:.2e}",
            number(update.raw.slope, 3),
            number(update.raw.correlation, 3),
            number(update.raw.sequence_slope, 3),
            number(update.raw.sequence_correlation, 3),
            number(update.tempered_top_k.slope, 3),
        ]
        for source in report.sources
        for update in source.updates
    ]
    sections = [
        f"# Serving precision: {report.name}",
        f"Policy `{report.adapter}` on `{report.base_model}`. {sample_set.sequences} samples ({sample_set.prompts} "
        f"prompts, {sample_set.completion_tokens} completion tokens, mean {sample_set.mean_completion_tokens:.0f}, "
        f"{sample_set.cut_off_sequences} cut off) drawn once from the bf16-merged server at T = {report.temperature}; "
        "every source scores exactly these tokens. Reference: fp32 base + fp32 LoRA, unmerged, IEEE fp32 compute "
        "(transformers). Differences per completion token in nats, served minus reference; `seq` sums them per "
        "sequence; k3 KL is the mean of exp(r) - r - 1 with r = served - reference. `repeat`: the server scoring "
        "the base twice (its own run-to-run noise). tokens/s: the fixed generation workload.",
        "## Temperature 1 (raw log-probabilities)",
        table(["source", *AGREEMENT_HEADER, "repeat mean abs", "tokens/s", "non-finite"], raw_rows),
        f"## Temperature {report.temperature}",
        f"vLLM's prompt log-probabilities are raw whatever `--logprobs-mode` says, so the tempered value is estimated "
        f"from the top {report.top_logprobs} on both sides: lp_t/T - logsumexp over top k and target of lp/T. The "
        f"estimate's own error on the reference (estimate minus exact): mean "
        f"{number(floor.mean_absolute_difference)}, p95 {number(floor.p95_absolute_difference)}, max "
        f"{number(floor.max_absolute_difference, 3)}.",
        table(["source", *AGREEMENT_HEADER], tempered_rows),
        f"## Sampler: the generation's processed log-probabilities (T = {report.temperature}), as the loop records",
        table(["against", *AGREEMENT_HEADER], sampler_rows),
        "## Update visibility",
        "Perturbed adapter = adapter + element step * a random sign per LoRA parameter (Adam's bias-corrected first "
        "step is lr * sign(gradient); `steps` steps of one sign add up). Change = perturbed minus base on the same "
        "tokens; slope of the served change on the fp32 reference change (1: the update survives serving, 0: "
        "rounded away) and correlation, per token and over per-sequence sums.",
        table(["perturbation", "element step", "relative norm", "merged update RMS", "adapter merged RMS"], size_rows),
        table(
            [
                "source",
                "perturbation",
                "ref change mean abs",
                "served change mean abs",
                "slope",
                "correlation",
                "seq slope",
                "seq correlation",
                f"slope T={report.temperature}",
            ],
            update_rows,
        ),
    ]
    failures = [f"- {source.source}: {source.failure}" for source in report.sources if source.failure]
    if failures:
        sections += ["## Failures", "\n".join(failures)]
    return "\n\n".join(sections) + "\n"


def read_config(paths: RunPaths) -> ServingPrecisionConfig:
    return from_json_object(ServingPrecisionConfig, json.loads(paths.config.read_text(encoding="utf-8")))


def effective_config(arguments: argparse.Namespace) -> ServingPrecisionConfig:
    config = from_json_object(ServingPrecisionConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    overrides = {
        "name": arguments.name,
        "adapter": arguments.adapter,
        "gpus": None if arguments.gpus is None else tuple(arguments.gpus),
        "prompts": arguments.prompts,
        "samples_per_prompt": arguments.samples_per_prompt,
    }
    return dataclasses.replace(config, **{key: value for key, value in overrides.items() if value is not None})


def write_summary(paths: RunPaths) -> None:
    report = summarize(paths)
    paths.summary.mkdir(parents=True, exist_ok=True)
    (paths.summary / "summary.json").write_text(json.dumps(dataclasses.asdict(report), indent=2), encoding="utf-8")
    (paths.summary / "README.md").write_text(render(report), encoding="utf-8")
    log(f"Summary in {paths.summary}")


def run(config: ServingPrecisionConfig) -> None:
    paths = RunPaths(RUNS_DIRECTORY / "serving_precision" / config.name)
    paths.root.mkdir(parents=True, exist_ok=True)
    if paths.config.exists() and read_config(paths) != config:
        raise ValueError(f"{paths.config} holds another configuration; choose another --name")
    write_json(paths.config, config)
    prompts = prepare_prompts(config, paths)
    prepare_perturbations(config, paths)
    run_modes(config, paths, prompts)
    run_references(config, paths)
    write_summary(paths)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run_command = commands.add_parser("run")
    run_command.add_argument("--config", type=Path, required=True)
    run_command.add_argument("--name")
    run_command.add_argument("--adapter")
    run_command.add_argument("--gpus", type=int, nargs="+")
    run_command.add_argument("--prompts", type=int)
    run_command.add_argument("--samples-per-prompt", type=int)
    summary = commands.add_parser("summary")
    summary.add_argument("--run-directory", type=Path, required=True)
    reference = commands.add_parser("reference", help="internal: reference passes on CUDA_VISIBLE_DEVICES")
    reference.add_argument("--run-directory", type=Path, required=True)
    reference.add_argument("--jobs", nargs="+", required=True, help="precision:adapter")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "run":
            run(effective_config(arguments))
        case "summary":
            write_summary(RunPaths(arguments.run_directory))
        case "reference":
            jobs = [
                ReferenceJob(ReferencePrecision(precision), adapter)
                for precision, adapter in (job.split(":", 1) for job in arguments.jobs)
            ]
            reference_jobs(RunPaths(arguments.run_directory), jobs)


if __name__ == "__main__":
    main()
