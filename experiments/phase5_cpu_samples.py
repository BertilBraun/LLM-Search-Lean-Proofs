"""Sample a few reasoning states on the CPU with transformers, for a tiny estimate while the GPUs are busy.

    python experiments/phase5_cpu_samples.py --config experiments/configs/reasoning/phase5_pilot_sft_v2_thinking.toml \
        --run-name phase5_cpu_estimate --states 8 --adapter-path /workspace/checkpoints/phase2_sft_v1/adapter
    python experiments/phase5_reasoning_data.py run --config ... --run-name phase5_cpu_estimate --state-limit 8 \
        --pool-size 4

Writes the first chunk's samples ($LEAN_SEARCH_RUNS/<run>/chunks/00000.samples.jsonl) for the first N states of the
run's states.jsonl with the config's prompt, k, temperature, top-p and max_tokens, so `run` only executes them in
Lean. Log-probabilities are not computed (0.0). Without --adapter-path the base model samples.
"""

import argparse
import dataclasses
import os
import time
from pathlib import Path

import peft
import torch
import transformers

from lean_search.policy.adapters import load_base_model
from lean_search.policy.client import Sample
from lean_search.policy.prompts import END_OF_TURN, LENGTH_FINISH_REASON, render_prompt
from lean_search.reasoning.config import load_reasoning_run_config
from lean_search.reasoning.pipeline import sample_record
from lean_search.reasoning.records import RunDirectory, StateSamples, read_records, write_records
from lean_search.reasoning.states import ReasoningState

RUNS_DIRECTORY = Path(os.environ.get("LEAN_SEARCH_RUNS", "/workspace/runs"))
STOP_FINISH_REASON = "stop"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--states", type=int, default=8)
    parser.add_argument("--adapter-path")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--states-per-batch", type=int, default=4)
    parser.add_argument("--sample-count", type=int, help="overrides policy.sample_count")
    parser.add_argument("--max-tokens", type=int, help="overrides policy.max_tokens")
    return parser.parse_args()


def sample_of_row(row: list[int], end_of_turn: int, tokenizer: transformers.PreTrainedTokenizerBase) -> Sample:
    finished = end_of_turn in row
    generated = row[: row.index(end_of_turn)] if finished else row
    text = tokenizer.decode(generated, skip_special_tokens=False)
    finish_reason = STOP_FINISH_REASON if finished else LENGTH_FINISH_REASON
    return Sample(text, 0.0, len(generated) + finished, finish_reason)


def main() -> None:
    arguments = parse_arguments()
    torch.set_num_threads(arguments.threads)
    config = load_reasoning_run_config(arguments.config)
    policy = dataclasses.replace(
        config.policy,
        sample_count=arguments.sample_count or config.policy.sample_count,
        max_tokens=arguments.max_tokens or config.policy.max_tokens,
    )
    directory = RunDirectory(RUNS_DIRECTORY / arguments.run_name)
    states = read_records(directory.states, ReasoningState)[: arguments.states]
    tokenizer = transformers.AutoTokenizer.from_pretrained(policy.tokenizer)
    tokenizer.padding_side = "left"
    model = load_base_model(policy.tokenizer).to(torch.float32)
    if arguments.adapter_path:
        model = peft.PeftModel.from_pretrained(model, arguments.adapter_path)
    model.eval()
    end_of_turn = tokenizer.convert_tokens_to_ids(END_OF_TURN)
    generation_config = transformers.GenerationConfig(
        do_sample=True,
        temperature=policy.temperature,
        top_p=policy.top_p,
        top_k=0,
        max_new_tokens=policy.max_tokens,
        num_return_sequences=policy.sample_count,
        eos_token_id=end_of_turn,
        pad_token_id=tokenizer.pad_token_id,
    )
    results: list[StateSamples] = []
    for start in range(0, len(states), arguments.states_per_batch):
        batch = states[start : start + arguments.states_per_batch]
        prompts = [render_prompt(tokenizer, state.goals, thinking=policy.thinking) for state in batch]
        inputs = tokenizer(prompts, return_tensors="pt", padding=True, add_special_tokens=False)
        started = time.monotonic()
        with torch.no_grad():
            output = model.generate(**inputs, generation_config=generation_config)
        seconds = time.monotonic() - started
        rows = output[:, inputs["input_ids"].shape[1] :].tolist()
        for index, state in enumerate(batch):
            state_rows = rows[index * policy.sample_count : (index + 1) * policy.sample_count]
            samples = tuple(
                sample_record(number, sample_of_row(row, end_of_turn, tokenizer), policy.thinking, tokenizer)
                for number, row in enumerate(state_rows)
            )
            prompt_tokens = int(inputs["attention_mask"][index].sum())
            results.append(
                StateSamples(state, policy.thinking, prompt_tokens, 0, policy.max_tokens, seconds / len(batch), samples)
            )
        generated = sum(sample.generated_tokens for result in results[-len(batch) :] for sample in result.samples)
        print(f"{start + len(batch)}/{len(states)} states: {generated} tokens in {seconds:.0f} s", flush=True)
    write_records(directory.chunk_samples(0), results)
    print(f"Wrote {len(results)} states to {directory.chunk_samples(0)}", flush=True)


if __name__ == "__main__":
    main()
