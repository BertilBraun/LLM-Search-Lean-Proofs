# Deployment

All heavy work runs on one rented Vast.ai node. The local machine only edits code and drives the node over SSH.
Changes reach the node through GitHub: commit locally, then `deployment/deploy.sh` pushes and fast-forwards the
node's checkout.

| Script | Runs on | Purpose |
|---|---|---|
| `remote_command.sh` | local | Run one command on a node over SSH (key, port, banner filtering). |
| `on_node.sh` | local | Run a command inside the node's checkout with `environment.sh` loaded. |
| `deploy.sh` | local | Push the current branch and fast-forward the node to it. |
| `fetch_results.sh` | local | Copy `$LEAN_SEARCH_RUNS/<run>/summary/` from the node into `results/<run>/`. |
| `setup_remote.sh` | node | Provision a node: clone the repo, then `setup_python.sh` and `setup_lean.sh`. |
| `environment.sh` | node | Paths, mirrors and `PATH`; sourced by everything else. |
| `setup_python.sh` | node | Create the virtual environment from `uv.lock`. |
| `serve_model.sh` | node | Start a detached vLLM server for one model on one GPU (prefix caching, runtime LoRA). |
| `stop_model.sh` | node | Stop servers started by `serve_model.sh` (by name or `--all`). |
| `setup_lean.sh` | node | Install elan, the pinned Lean toolchain, Mathlib (from cache) and the REPL. |

## First-time setup

```bash
echo "HOST:PORT" > deployment/.node_address
deployment/remote_command.sh "$(cat deployment/.node_address)" 'bash -s' < deployment/setup_remote.sh
```

## Lean environment

| Component | Pin |
|---|---|
| Lean | `leanprover/lean4:v4.9.0-rc1` (`lean/lean-toolchain`) |
| Mathlib | `leanprover-community/mathlib4` `d1d1e4b72c6e009edd97cabe1d661b021fe8eeae` (2024-06-12) |
| REPL | `leanprover-community/repl` tag `v4.9.0-rc1` (`7df77c0a1c9188ab58c76d4138a06ae5e0c32282`) |
| Other packages | as in Mathlib's manifest; all revisions in `lean/lake-manifest.json` |
| elan | v4.2.4 |

DeepSeek-Prover-V1.5 (and the Goedel/STP proofs verified in its environment) pins `xinhjBrant/mathlib4@2f65ba7f`,
which is this Mathlib commit with only `lakefile.lean`/`lake-manifest.json` changed: batteries one commit newer (a
linter fix), `lean4-cli` bumped, and a REPL fork (`xinhjBrant/repl@3334a97b` = REPL `v4.9.0-rc1` plus AST
extraction) added. Those files enter Mathlib's cache hashes, so the fork has no prebuilt cache; its upstream parent
has one (4650 files). The Mathlib sources are identical.

`setup_lean.sh` takes about 4 minutes on a fresh node (3 of them downloading the Mathlib cache from Azure) and under
a minute when `~/.cache/mathlib` is warm. GitHub release downloads (elan, the toolchain) are throttled to a few KB/s
on the current node, so they go through `$LEAN_SEARCH_GITHUB_PROXY` (default `https://ghfast.top/`) and are checked
against pinned SHA-256 sums; `git fetch` from GitHub is fast and used directly.

REPL facts for this version (handled in `src/lean_search/lean/`): it never flushes stdout (run it under
`stdbuf -oL`); tactic-level `set_option maxHeartbeats N in` does not change the heartbeat limit in Lean 4.9, so the
wrapper defines its own `lean_search_heartbeats N => tactics`; `autoImplicit` is on (Lean's default); proof states
are never freed, so processes are restarted by memory and proof-state thresholds.

## Python environment and model serving

`setup_python.sh` installs `uv.lock` (Python 3.12, extra `ml`) in about a minute. The lock records the Tsinghua PyPI
mirror, so `uv sync --locked` downloads from it (~50 MB/s on the node). vLLM 0.31.0 pins torch 2.13.0, whose PyPI
wheels bundle the CUDA 13.0 runtime; driver 595 supports it and sm_86 is in the arch list, so the system CUDA 12.8
toolkit is not used. Models are fetched with `hf download <repository>` into `$HF_HOME`; `environment.sh` disables
Xet, which hf-mirror.com does not proxy (401).

```bash
deployment/on_node.sh 'deployment/serve_model.sh qwen3.5-2b Qwen/Qwen3.5-2B 0 8000'   # returns once healthy
deployment/on_node.sh 'deployment/stop_model.sh --all'
```

| Model | Repository @ revision | Architecture | Context | Chat template thinking default |
|---|---|---|---|---|
| Qwen3.5-0.8B | `Qwen/Qwen3.5-0.8B` @ `2fc0636` | hybrid Gated DeltaNet + attention, vision-language | 262,144 | off |
| Qwen3.5-2B | `Qwen/Qwen3.5-2B` @ `15852e8` | same | 262,144 | off |
| Qwen3.5-2B-Base | `Qwen/Qwen3.5-2B-Base` @ `b1485b2` | same | 262,144 | off (same template) |
| Qwen3.5-4B | `Qwen/Qwen3.5-4B` @ `851bf6e` | same | 262,144 | on |
| Qwen3-1.7B | `Qwen/Qwen3-1.7B` @ `70d244c` | dense attention | 40,960 | on |
| Qwen2.5-Math-1.5B | `Qwen/Qwen2.5-Math-1.5B` @ `4a83ca6` | dense attention | 4,096 | none (adds a default system prompt) |
| Qwen2.5-Math-1.5B-Instruct | `Qwen/Qwen2.5-Math-1.5B-Instruct` @ `aafeb0f` | dense attention | 4,096 | none (adds a default system prompt) |

Thinking is switched with the chat-template argument `enable_thinking` (`chat_template_kwargs` in the chat API):
`False` pre-fills an empty `<think>\n\n</think>\n\n` block, `True` opens `<think>\n`. Qwen3.5-0.8B/2B default to off,
Qwen3.5-4B and Qwen3-1.7B to on, so always pass it explicitly. Qwen2.5-Math must be served with
`MAX_MODEL_LEN=4096`.

vLLM facts for these models:

- Qwen3.5 checkpoints are vision-language models (`Qwen3_5ForConditionalGeneration`); `serve_model.sh` adds
  `--language-model-only` so no memory goes to the vision tower.
- Prefix caching on Qwen3.5 runs in Mamba cache mode `align` (set automatically): the KV block grows to 544 tokens
  and the recurrent state is checkpointed once per block, so by default the n samples of a request recompute the
  prompt tail past the last block boundary. `--prefix-match-unit 16` (set by `serve_model.sh`) fixes that: for n=16
  the prompt-token cache hit rate rises from 0.69 to 0.89–0.92 and throughput by 14–22% on Qwen3.5-2B
  (`results/phase1_throughput/`).
- LoRA works for Qwen3.5, including the packed Gated DeltaNet projections (`in_proj_qkvz`, `in_proj_ba`); the
  vision tower is not adapted. Adapters load at runtime (`POST /v1/load_lora_adapter` with `lora_name` and
  `lora_path`, then request `"model": "<lora_name>"`); `lean_search.policy.adapters` writes adapters targeting
  exactly the language-model linear layers and merges them.
- Returned log-probabilities are raw (temperature 1, before top-p) and carry bf16 logit resolution: steps of
  0.125 nats when logits are around 16–32. vLLM rejects `n > 1` at temperature 0.
- LoRA cost (rank 64 on all language-model linear layers): requests through an adapter are 9–24% slower than the
  merged model on Qwen3.5-2B (most for short outputs) and 5–9% on Qwen3-1.7B; merely enabling LoRA costs
  Qwen3.5-2B up to 10% and Qwen3-1.7B nothing measurable. Loading or swapping an adapter at runtime takes 0.3 s;
  merging on the CPU takes 25–30 s and restarting the server 1.5–2.5 minutes. Merge for long evaluation runs, swap
  inside training loops.
- At n=16 the 3090 runs at 100% utilization at its 350 W cap. The defaults `max_num_seqs=256` and
  `max_num_batched_tokens=2048` are kept: 512 and 8192 give +15% for short outputs after 600-token prompts but -23%
  for 512-token outputs after 1500-token prompts, where the KV cache runs out and requests are preempted (each
  running Qwen3.5 sequence also holds a recurrent-state page as large as a 544-token block). Qwen3.5-4B leaves only
  9 GiB for the cache and is preempted even at 256 sequences. `MAX_NUM_SEQS` overrides the default.
- A start takes 1.5–2.5 minutes with warm caches (Qwen3.5-4B cold: 4.6 minutes): torch.compile and Triton
  autotuning results are cached under `~/.cache/vllm` and `~/.triton` (not persistent), and CUDA graphs are
  captured twice (memory profiling, then serving).

## Node layout

| Path | Contents | Persistent |
|---|---|---|
| `/workspace/LLM-Search-Lean-Proofs` | repository checkout, `.venv`, `lean/.lake` | no |
| `/workspace/data` | downloaded and traced datasets | no |
| `/workspace/runs` | search logs and per-theorem results | no |
| `/workspace/checkpoints` | LoRA adapters and value models | no |
| `/workspace/.hf_home` | Hugging Face cache (models via hf-mirror.com) | no |

`/workspace` is not a volume on the current node, so anything that must survive the rental is either committed
(summaries under `results/`) or copied back to the local machine (adapters under the untracked `artifacts/`).

## Current node

2× RTX 3090 (24 GB), AMD EPYC 7K62 with a 46-core cgroup quota, ~120 GB RAM cgroup limit, 300 GB disk,
Ubuntu 24.04, CUDA 12.8, driver 595. Network: GitHub reachable; huggingface.co blocked (use hf-mirror.com);
pypi.org slow (use a mirror).
