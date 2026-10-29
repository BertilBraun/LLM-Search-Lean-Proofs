# Deployment

All heavy work runs on one rented Vast.ai node. The local machine edits code, runs tests (WSL, below) and drives the
node over SSH.
Changes reach the node through GitHub: commit locally, then `deployment/deploy.sh` pushes and fast-forwards the
node's checkout.

| Script | Runs on | Purpose |
|---|---|---|
| `remote_command.sh` | local | Run one command on a node over SSH (key, port, banner filtering). |
| `on_node.sh` | local | Run a command inside the node's checkout with `environment.sh` loaded. |
| `deploy.sh` | local | Push the current branch and fast-forward the node to it. |
| `fetch_results.sh` | local | Copy `$LEAN_SEARCH_RUNS/<run>/summary/` from the node into `results/<run>/`. |
| `setup_remote.sh` | node | Provision a node: clone the repo, then `setup_python.sh` and `setup_lean.sh`. |
| `environment.sh` | node | Paths, opt-in mirrors and `PATH`; sourced by everything else. |
| `setup_python.sh` | node | Create the virtual environment from `uv.lock`. |
| `serve_model.sh` | node | Start a detached vLLM server for one model on one GPU (prefix caching, runtime LoRA). |
| `stop_model.sh` | node | Stop servers started by `serve_model.sh` (by name or `--all`). |
| `background.sh` | node | Run a CPU-heavy job pinned to the last `BACKGROUND_CPUS` (32) CPUs at nice 19 (CPU budget). |
| `grpo_loop.sh` | node | The GRPO loop step by step: held-out sets, version 0, servers, checks, value benchmark, dashboard, loop, status, μ. |
| `setup_lean.sh` | node | Install elan, the pinned Lean toolchain, Mathlib (from cache) and the REPL. |

## First-time setup

```bash
echo "HOST:PORT" > deployment/.node_address
deployment/remote_command.sh "$(cat deployment/.node_address)" 'bash -s' < deployment/setup_remote.sh
```

## Local development (WSL)

Implementation and all tests that need no GPU or model server, Lean included, run in WSL2 (Ubuntu 24.04, no GPU).
The clone lives on the Linux filesystem at `~/lean-proofs` (Lean under `/mnt/c` is slow); the Windows repository is
its remote `local`, so commits made on Windows, worktree branches included, arrive without pushing to GitHub.

```bash
git clone https://github.com/BertilBraun/LLM-Search-Lean-Proofs.git ~/lean-proofs && cd ~/lean-proofs
git remote add local /mnt/c/Projects/Lean-Proofs
uv sync --locked --python 3.12 --extra ml --group dev   # ~6 minutes, 8 GB; torch and vLLM import without CUDA
deployment/setup_lean.sh                                # ~3 minutes, 5 GB; needs zstd (sudo apt install zstd)
git fetch local && git reset --hard local/master        # later: sync to the Windows master
```

Tests, from Windows (`environment.sh` puts elan's `lake` and the venv on `PATH`; Lean tests skip without `lake`):

```bash
wsl -d Ubuntu -e bash -lc 'cd ~/lean-proofs && source deployment/environment.sh && pytest -q -p no:cacheprovider'
```

The whole suite takes about 3.5 minutes on 4 CPUs; 41 tests skip (no GPU, no vLLM server, models not in the Hugging
Face cache). Tests start at most two REPLs at once; a Mathlib REPL maps ~2.4 GB of `.olean` files that are
shared through the page cache, and the run peaks at ~2 GB used, so a 6 GB WSL is enough.

Another checkout, e.g. an agent's git worktree on Windows, runs against the same venv and Lean build: `PYTHONPATH`
puts its `src/` ahead of the venv's editable install, `LEAN_SEARCH_LEAN_PROJECT` points the REPL at the built
`lean/` (a worktree has no `lean/.lake`, so its Lean tests would skip), and the worktree's own `tests/` and
`pyproject.toml` are used. New dependencies of the worktree need a `uv sync` in `~/lean-proofs` first.

```bash
wsl -d Ubuntu -e bash -lc 'source ~/lean-proofs/deployment/environment.sh
  W=/mnt/c/Projects/Lean-Proofs/.claude/worktrees/<name> && cd $W
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$W/src LEAN_SEARCH_LEAN_PROJECT=$HOME/lean-proofs/lean \
      python -m pytest -q -p no:cacheprovider tests'
```

Same results as the native run, in ~3.5 minutes (sources read over `/mnt/c`).

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

`setup_lean.sh` takes about 3–4 minutes on a fresh machine (most of it downloading the Mathlib cache from Azure) and
under a minute when `~/.cache/mathlib` is warm. It needs `git`, `curl`, `python3` and `zstd`. GitHub release
downloads (elan, the toolchain) are checked against pinned SHA-256 sums and go through `$LEAN_SEARCH_GITHUB_PROXY`
when set (`https://ghfast.top/` on the first node, where they were throttled to a few KB/s).

REPL facts for this version (handled in `src/lean_search/lean/`): it never flushes stdout (run it under
`stdbuf -oL`); tactic-level `set_option maxHeartbeats N in` does not change the heartbeat limit in Lean 4.9, so the
wrapper defines its own `lean_search_heartbeats N => tactics`; `autoImplicit` is on (Lean's default); proof states
are never freed, so processes are restarted by memory and proof-state thresholds.

## Python environment and model serving

`setup_python.sh` installs `uv.lock` (Python 3.12, extra `ml`) in about a minute. The lock records pypi.org; with
`LEAN_SEARCH_PYPI_MIRROR` set (e.g. `https://pypi.tuna.tsinghua.edu.cn/simple`) it resolves against that index
instead, keeping the locked versions. vLLM 0.31.0 pins torch 2.13.0, whose PyPI
wheels bundle the CUDA 13.0 runtime; driver 595 supports it and sm_86 is in the arch list, so the system CUDA 12.8
toolkit is not used. Models are fetched with `hf download <repository>` into `$HF_HOME`, from huggingface.co or
from `HF_ENDPOINT=https://hf-mirror.com`, for which `environment.sh` disables Xet (the mirror does not proxy it: 401).

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

## CPU budget

The container sees all 192 host CPUs but its cgroup is capped at 46 cores (`cpu.max`). Busy processes each get a CPU of
their own, so `nice` changes nothing until the quota is used up; then the kernel stops the whole cgroup, GPU feeders
included, for the rest of each 100 ms period. Measured (`results/gpu_utilization/`): 60 busy processes throttle the
cgroup in 100% of periods whether they run at nice 0 or nice 19; pinned to 32 CPUs they throttle it in 0.3%.

What throttling costs depends on the GPU feeder:

- Training keeps its GPU busy through throttling: its launch queue is full (the CPU runs ahead of the GPU), so DDP SFT
  ran at 10.9k tokens/s and 98–99.9% utilization with or without 60 busy processes.
- vLLM is latency-bound: the engine schedules every decoding step on the CPU. With 120 unpinned searches (Lean at 46
  cores, 90% of periods throttled) both GPUs fell to 70–72% utilization; with the same searches pinned to 40 CPUs (0%
  throttled) they stayed at 76–80%.

Rule:

- GPU feeders (vLLM servers, training ranks, the search orchestrator) run unpinned at nice 0.
- Everything CPU-heavy runs through `deployment/background.sh`: tracing, pre-filters, Lean stages of probes, data
  building, and the search processes themselves (their Lean REPLs are the CPU load), e.g.
  `BACKGROUND_CPUS=40 deployment/background.sh python experiments/run_search.py ...`. The wrapper pins to the last
  `BACKGROUND_CPUS` logical CPUs (default 32) and nices to 19; all background jobs share those CPUs, so together they
  can never exceed that many cores.
- Leave at least 6 cores of the quota to the feeders: 4 vLLM processes take about 3, two DDP ranks about 4. With a
  search running, give it 40 CPUs and nothing else; while training next to a search, 36.
- Give a Lean job at most `BACKGROUND_CPUS` processes doing work at once, or its tactics hit wall-clock limits they
  would not hit unpinned. Searches are an exception: most of their REPLs wait on the GPU at any moment.

## Serving the search and publishing new weights

Recommended layout (`results/gpu_utilization/`): per GPU, the merged policy and the merged value model as two vLLM
instances without LoRA, 120 searches pinned to 40 CPUs, `overlap` and `score_children_early` on. Measured 151.6
samples/s and 95–96% utilization at 340 W on both GPUs, against 138 samples/s and 76–80% for the adapters on the
raw base. The alternative, the merged policy plus the value as a rank-128 difference adapter
(`lean_search.policy.adapters.difference_adapter`: B_v A_v − B_p A_p, so it applies the value update exactly on
top of the merged policy weights; served h differs from the adapter-on-base h by 0.03 steps on average), reached 144.6
samples/s at 79–80%. The search is limited by Lean CPU, not by the GPUs: one GPU alone saturates at 91 samples/s.

```bash
C=$LEAN_SEARCH_CHECKPOINTS
python experiments/publish_weights.py merge --adapter $C/phase2_sft_v2/adapter --output $C/phase2_sft_v2/merged
for gpu in 0 1; do
  GPU_MEMORY_UTILIZATION=0.58 deployment/serve_model.sh policy-gpu$gpu $C/phase2_sft_v2/merged $gpu 810$gpu \
      --served-model-name policy-merged --no-enable-lora
  GPU_MEMORY_UTILIZATION=0.30 deployment/serve_model.sh value-gpu$gpu $C/phase3_value_v0/merged $gpu 820$gpu \
      --served-model-name value-merged --no-enable-lora
done
```

with `[policy] model = "policy-merged"` (no adapter) on ports 8100/8101 and `[value] model = "value-merged"` on
8200/8201. A second instance on a GPU sees the first one's memory: if it fails with "Free memory ... is less than
desired", lower its `GPU_MEMORY_UTILIZATION` (0.25) and `MAX_NUM_SEQS` (96 is plenty for prefill-only value requests).

Policy servers of the GRPO loop also get `--logprobs-mode processed_logprobs` (vLLM 0.31): the recorded
log-probabilities are then those of the distribution actually sampled (after temperature; top-p is 1.0), which the
GRPO trainer compares with its own, computed at the same temperature (`src/lean_search/rl/README.md`, "Trainer").
vLLM's default reports the raw distribution before temperature. Value servers keep the default: their bins are read
from raw log-probabilities.

Publishing a new policy or value version without a restart (`serve_model.sh` turns on vLLM's dev-mode endpoints,
listening on 127.0.0.1 only; `lean_search.policy.server_control`):

| Step | Command | Seconds |
|---|---|---|
| Merge the adapter (CPU, 8 threads; on a GPU 22 s) | `publish_weights.py merge --adapter A --output M` | 17 |
| Swap a running server's weights in place: pause (in-flight requests finish), `reload_weights` via `/collective_rpc`, reset the prefix cache, resume | `publish_weights.py publish --weights M --server-url URL ...` | 1.9 |
| Free a server's GPU (sleep level 2; servers started with `SLEEP_MODE=1`); new requests queue | `publish_weights.py release --server-url URL ...` | 0.4 (796 MiB left in use) |
| Bring it back with new weights | `publish_weights.py restore --weights M --server-url URL ...` | 2.0 |
| Restart instead (warm compile caches) | `stop_model.sh`, `serve_model.sh` | 56–61 (cold: 155–206) |

So a publish costs about 20 s (merge plus reload), and the train-on-every-GPU loop (the GRPO loop's layout, below)
is: `release` all servers, train with DDP, merge, `restore` with the new directory, and the searches' queued requests
continue (a request sent during a 35 s release completed right after the restore). Search clients must allow requests
that long (`request_timeout_seconds`), and searches in flight keep their wall-clock budgets running while paused. A
weight reload drops the workers' LoRA adapters: re-register them (`publish_weights.py difference ... --name value-v0`
re-creates and reloads a difference adapter).

Re-scoring a frontier after a new value version: all 14,879 open states of the 244 row-4 trees take 105 s on both
GPUs' merged value instances (141 states/s, ~17k prompt tokens/s per GPU, compute-bound; the value prompts share no
cacheable prefix because hybrid-model prefix caching works in 544-token blocks). The value estimator sends 32 states
per request: one request per state cost the client ~10 ms of CPU each. A larger prefill chunk
per step (`MAX_NUM_BATCHED_TOKENS=16384`) did not change the rate. At 120 searches the open frontiers hold
an estimated 5k states (half the trees' final frontiers, 61 on average), about 35 s; re-score larger frontiers
best-first or lazily.

## Serving precision

`experiments/serving_precision.py` (DESIGN.md "Precision"; a first-hour check, run with the loop's servers stopped)
measures how far each way of serving the policy is from the exact model, on the same tokens. It draws 200 visible-mode
prompts (as the search builds them) from the per-step evaluation's states, samples 4 completions each from the
bf16-merged policy (T 0.8, the search's max tokens, no budget forcing) and scores exactly those tokens under: an fp32
transformers reference (fp32 base + fp32 LoRA, unmerged, IEEE fp32 throughout, PyTorch Gated DeltaNet); the trainer's
own precision (`trainer_bf16`: bf16 base, fp32 LoRA, bf16 autocast, fp32 output layer); and three vLLM servers
(`bf16_merged`, `fp16_merged` merged in fp32 and cast, served with `--dtype float16`; `lora_bf16`, the adapter at
runtime on the bf16 base) through `prompt_logprobs` on prompt + completion (token ids checked against the server's).
Each server also generates a fixed workload (64 prompts x 8 samples x 512 tokens, ignore_eos, all in flight) for
tokens/s, and scores the base twice (its run-to-run noise). Update visibility: perturbed adapters (every LoRA
parameter ± lr x steps, Adam's first-step size; 1e-5 x 1, 3e-5 x 1, 3e-5 x 10) are served the same way (merged ones
swapped in place, runtime adapters loaded) and the served change in log-probability is regressed on the reference's.

```bash
mkdir -p $LEAN_SEARCH_RUNS/serving_precision
setsid nohup python experiments/serving_precision.py run --config experiments/configs/grpo/serving_precision.toml \
    --gpus 1 2 3 > $LEAN_SEARCH_RUNS/serving_precision/visible_student_v2.log 2>&1 &
deployment/fetch_results.sh serving_precision/visible_student_v2   # locally, afterwards
```

One vLLM mode per GPU (ports 8950-8952, servers `precision-<mode>`), then the reference passes spread over the same
GPUs (fp32 ~18 GiB per GPU); merged weights live under `/dev/shm/serving_precision/` until their mode is done. A rerun
with the same `--name` keeps every score already written (`scores/<source>__<adapter>.npz`); a failing mode is noted
under `failures/` and in the summary, the others go on. `summary --run-directory <run>` rebuilds the summary.

Reading `summary/README.md`: per source, the per-token |served - reference| (mean, p95, max, nats), the mean signed
difference (an offset means a temperature or scaling mismatch), k3 KL (mean of e^r - r - 1, r = served - reference;
tokens come from the bf16-merged sampler, so it approximates KL(reference || served)), and the per-sequence sum; at
T = 1 exactly, at T = 0.8 from the top 20 log-probabilities on both sides (vLLM's prompt log-probabilities are raw
whatever `--logprobs-mode` says; the estimate's own error on the reference is printed). The sampler rows compare the
generation's recorded log-probabilities with the reference's exact tempered ones (the dashboard's sampler-vs-trainer
number) and with the same server's rescoring (alignment: should be within the estimate's error). Update visibility:
slope of the served change on the reference change, per token and per sequence, ~1 when the update survives, ~0 when
it rounds away; the correlation says how much of the served change is the update rather than rounding.

## Dashboard

`experiments/dashboard.py` serves a run's metrics (`$LEAN_SEARCH_RUNS/<run>/metrics/*.jsonl`, see
`src/lean_search/monitoring/README.md`) as an overview page and detail pages, on phones too. Standard library only,
no external scripts.

The dashboard is read-only and open by default: anyone with the address sees the run's metrics, nothing else.
A password is optional (`--password-file` or `LEAN_SEARCH_DASHBOARD_PASSWORD`; never generated, printed or
committed) and turns on the login described below:

```bash
mkdir -p ~/.config/lean-search && (umask 077 && read -rsp 'password: ' p && printf '%s' "$p" > ~/.config/lean-search/dashboard_password)
```

Run it next to the loop (and the system sampler, which records GPUs, cgroup CPU, Lean REPL cores and the money spent):

```bash
R=$LEAN_SEARCH_RUNS/<run>
nohup python experiments/dashboard.py record-system --run-directory $R --hourly-price 0.80 > $R/system_sampler.log 2>&1 &
nohup python experiments/dashboard.py serve --run-directory $R --compare control=$LEAN_SEARCH_RUNS/<control run> \
    --host 0.0.0.0 --port 8600 \
    --config experiments/configs/dashboard/dashboard.toml > $R/dashboard.log 2>&1 &
```

Exposing it:

- **HTTPS tunnel (preferred, works from a phone)**: `cloudflared tunnel --url http://localhost:8600` prints a
  `https://<random>.trycloudflare.com` address (no account; the address changes on restart); with `--host
  127.0.0.1` nothing else is reachable. Vast's Instance Portal can open the same kind of tunnel for a local port.
  Behind a tunnel the session cookie is marked `Secure` (from `X-Forwarded-Proto`; `--secure-cookies` forces it).
- **Mapped port**: open the port when renting (Vast: `-p 8600:8600` in the docker options) and use the external
  port Vast lists for it, `http://<ip>:<external port>/`. Plain HTTP: the password crosses the network
  unencrypted, so prefer the tunnel or an SSH forward (`ssh -L 8600:localhost:8600 ...`).
- Login (only with a password): a form with a 14-day session cookie (signed with a per-process key, so a restart logs out); scripts can use
  basic auth (`curl -u any:<password> .../api/overview`). Ten failed attempts per minute lock a client out for the
  rest of that minute.

Try it locally with synthetic data (3 days of a run and its control, `--live` keeps appending):
`PYTHONPATH=src python experiments/dashboard.py demo --live`, then
open `http://localhost:8600/`.

TensorBoard: `MetricsWriter(..., tensorboard=True)` mirrors every scalar to `$R/tensorboard` when `tensorboard` is
installed (`uv pip install tensorboard`; not in the lock file). TensorBoard has no authentication, so never map
its port openly: run `tensorboard --logdir $R/tensorboard --host 127.0.0.1 --port 6006` and reach it through an SSH
forward or a tunnel that authenticates (Vast's Instance Portal; Cloudflare Access), not a bare quick tunnel.

## GRPO loop

The search-tree GRPO loop (`src/lean_search/rl/README.md`, "The loop") on 4x RTX 3090 with ~96 CPU threads:

| GPUs | While sampling | During a phase's pause (every search paused) |
|---|---|---|
| 0-3 | each serves the merged policy (port 810x, `GPU_MEMORY_UTILIZATION=0.62`, `--logprobs-mode processed_logprobs`) and the merged value model (port 820x, 0.28, `MAX_NUM_SEQS=96`), all with `SLEEP_MODE=1` | the servers drain and sleep (level 2, ~0.8 GiB each left in use); the persistent training job (`grpo_trainer.py`, `[training] persistent = true`; started once with the loop, its models parked in host memory between phases) trains on all four with `torchrun` (`[training] gpus`): policy GRPO, the value model, the merges into host memory; then the servers wake with the new weights from there and the searches resume while the weights are written to disk |

Fallback if the data-parallel pause costs too much (`src/lean_search/rl/README.md`, "Timing"): `gpus = [0]` in
`[training]`; GPU 0's two servers sleep and one process trains there, the other six stay loaded and idle and swap to
the new weights in place. No server changes are needed to switch. `persistent = false` runs `grpo_phase.py` once per
phase instead of the persistent job (start, loads and compilation paid every phase; merges written to disk first).

The persistent job keeps its parked bases (one copy for all ranks, ~14 GiB) and the merges it hands to the servers
(up to ~14 GiB until written to disk) under `[training] host_directory` (`/dev/shm/lean_search/<loop>`): rent with
`--shm-size 32g` or more (`df -h /dev/shm`; the job fails building its models, with the sizes, when the tmpfs is too small;
another directory works too, then the parked weights live in the page cache). Its log is
`$LEAN_SEARCH_RUNS/<loop>/training/trainer.log` (all phases, ranks prefixed), its commands and replies
`training/trainer/`.

The loop process holds one Lean REPL per concurrent search (`[sampling] concurrency`, 112) and runs the training and
evaluation jobs as child processes, each in its own process group and recorded in `$LEAN_SEARCH_RUNS/<loop>/children/`
while it runs; stopping the loop stops the job too: its group and every process carrying the job's marker
(`LEAN_SEARCH_LOOP_JOB` in the environment; torchrun starts its ranks in sessions of their own, outside the group). A
loop that refuses to start because "Jobs of an earlier loop still run" died without stopping one; it refuses before
waking any server. The message lists the job's process ids (`process_ids`, the ranks included): check them with
`ps -o pid,cmd -p <ids>`, stop them with `kill -TERM <ids>`, then start the loop again.

Bring-up on a fresh node, after the rebuild (`setup_remote.sh`, pool v3 verified statements under
`$LEAN_SEARCH_DATA/expert_iteration/pool_v3/`, the value v0 adapter at `phase3_value_v0/adapter` from `node_backup/`,
v0's training data at `$LEAN_SEARCH_DATA/value/v0/train.jsonl` for the value replay (`data/value/v0/` in
`node_backup/2026-10-15/generated_data.tar.zst`, or rebuilt with `phase3_value_data.py --name v0`), and the per-step
evaluation's states at `$LEAN_SEARCH_RUNS/phase5_eval_visible_student_v2_visible/states.jsonl`) and
after the SFT stage (`src/lean_search/data_rewrite/README.md`, steps 1-4), whose outputs the loop starts from:

- the starting policy's own LoRA adapter, `$LEAN_SEARCH_CHECKPOINTS/data_rewrite_sft_<arm>/adapter` (it continues
  visible student v2's adapter, with its rank, on raw `Qwen/Qwen3.5-4B`; `merge = false` is fine): `loop.toml` `[initial] policy_adapter`, on
  `[serving] policy_base_model = "Qwen/Qwen3.5-4B"`. Version 0 is that adapter merged (by `init`); every phase keeps
  training the same adapter on the raw base, and it stays the KL reference. Not merged weights with a fresh adapter:
  small updates would round away when merged into bf16 weights that already lie on the grid.
- its flattened SFT data, `$LEAN_SEARCH_DATA/reasoning/visible_student_v3_<arm>/{train,math}.jsonl` (`data_rewrite.py
  build`): `[training] lean_replay` and `math_replay`, the GRPO phases' NLL replay.

The configs name the numbered arm. If the naming A/B picks the named arm, change `policy_adapter`, `lean_replay` and
`math_replay` to `..._named` and set `[renaming] enabled = true` (`loop.toml`, `loop_overfit.toml`; the phase configs'
and `single_step.toml`'s defaults likewise, though the loop fills in its own).

Disk: plan on about 200 GB for the whole run and rent at least 300 GB (estimates): the Hugging Face cache (Qwen3.5-4B,
-2B and the 9B teacher, ~32 GB), Mathlib's build, the datasets and the SFT checkpoints (~30-40 GB together), merged
weights (the current version's and version 0's policy and value, the kept v0 value model and the next version's while
publishing: ~50 GB at the peak), the last 5 versions' phase adapters (~4 GB; older ones are deleted,
`src/lean_search/rl/README.md`, "Disk") and the trees, which grow by an estimated 150-250 MB per phase, 5-10 GB a day
at 30-minute phases. `system.disk_free_gib` on the System page, alert below 50 GiB free.

Order on a fresh node (each step catches what would otherwise surface hours later):

1. **Node checks** (`deployment/grpo_loop.sh node-check`, minutes): `df` of the runs, the checkpoints and `/dev/shm`
   (fails below 30 GiB of `/dev/shm`: the persistent trainer keeps ~28 GiB there, its parked bases and the merges it
   hands to the servers, and Docker's 64 MB default also breaks NCCL's shared-memory transport; rent with
   `--shm-size 32g` or more), `nproc` and the cgroup's `cpu.max`, `nvidia-smi topo -m`, and a 4-rank NCCL all-reduce of
   256 MiB (`experiments/nccl_check.py`, as the trainer sums its gradients; a hang means no peer-to-peer access over
   PCIe: `NCCL_P2P_DISABLE=1` in the loop's environment). HF and GitHub reachability.
2. **Rebuild**, then the heartbeat replay (`python experiments/heartbeat_replay.py ...`, DESIGN.md "Lean execution and
   harness"), which fixes the caps every later search uses.
3. **Smoke cycle** (`experiments/configs/grpo/loop_smoke.toml`, about an hour): the whole loop on the overfit
   statements with visible student v2 as the starting policy, 5-10-minute phases, a value phase every phase (always
   published) and every evaluation at a tiny size (probe 12 problems, 4 per part, every part twice at the start;
   miniF2F 8; held-out states 32; a value arm every slot). It runs the at-start baselines, v0 scoring the tiny value
   benchmark through the value servers, a pause with policy and value training on four ranks, both GPU merges, the
   publish and the wake, the new value model scoring the benchmark, the swap to the fixed v0 value model for a probe
   slot and to the published one for its value arm, and the adapter pruning after the second phase. Go through the
   first-hour checks below on it, stop it after two phases and delete `$LEAN_SEARCH_RUNS/grpo_smoke*` and
   `$LEAN_SEARCH_CHECKPOINTS/grpo_smoke*`.
4. **Cheap tests** (below): single-step GRPO with both credits (go or no-go on the learning rate), then the SFT stage
   and the naming A/B (`src/lean_search/data_rewrite/README.md`).
5. **Value benchmark** (the gate set) with the starting policy served (`gate`, ~1-2 h): every served value model
   scores it, a dashboard trend.
6. **Main loop**: a fresh `init`, then `loop`. Version 0's baselines run before the first phase: every probe part
   twice, the held-out states and miniF2F (`[evaluation.minif2f] at_start = true`; the loop evaluates only the version
   it serves, so a baseline missed here needs version 0 served again: its merged weights stay under `weights/v0000/`,
   never pruned).

```bash
deployment/grpo_loop.sh node-check   # step 1
deployment/grpo_loop.sh sets         # once: probe (501), gate (402) and overfit (300) sets under $LEAN_SEARCH_DATA/grpo/
LOOP_CONFIG=experiments/configs/grpo/loop_smoke.toml deployment/grpo_loop.sh init   # step 3, the smoke cycle:
LOOP_CONFIG=experiments/configs/grpo/loop_smoke.toml deployment/grpo_loop.sh servers
LOOP_CONFIG=experiments/configs/grpo/loop_smoke.toml deployment/grpo_loop.sh check
deployment/grpo_loop.sh smoke-gate   # 60 gate problems searched by the smoke's version 0, its tiny benchmark
LOOP_CONFIG=experiments/configs/grpo/loop_smoke.toml deployment/grpo_loop.sh dashboard
LOOP_CONFIG=experiments/configs/grpo/loop_smoke.toml deployment/grpo_loop.sh loop   # two phases, then stop
deployment/grpo_loop.sh init         # step 6: the starting policy's and the value v0 adapter merged into their bases
deployment/grpo_loop.sh servers      # eight vLLM servers: a GPU's two one after another, the GPUs in parallel
deployment/grpo_loop.sh check        # one live request per policy server (below)
deployment/grpo_loop.sh gate         # step 5: the value benchmark (gate set, no value model), ~1-2 h
deployment/grpo_loop.sh dashboard    # http://<node>:8600 (open; tunnel or mapped port: "Dashboard" above)
deployment/grpo_loop.sh loop         # version 0's probe (every part twice), held-out states, miniF2F, then sampling
deployment/grpo_loop.sh status       # or the dashboard; `tail -f $LEAN_SEARCH_RUNS/grpo_loop_v1/loop.log`
deployment/grpo_loop.sh value-share 0.15   # μ on from the next phase that trains (0: off again); starts at 0
```

There is no value gate: every value model the loop trains is published, and μ (the value share of the reward and the
value targets) stays 0 until set by hand with `value-share`, which writes `$LEAN_SEARCH_RUNS/<loop>/value_share.json`;
the loop reads it when each phase starts training (`status` prints it, the Value page charts the μ in effect per
phase). The value statistics are trends only: the value benchmark (Value page, per served value model, against v0 and
the previous model), the value arms (every other probe slot, paired with v0; an alert in `loop.log` and on the
dashboard when the published value model is significantly worse than v0, nothing more) and the per-phase calibration
and label/prediction distributions.

`servers` starts only the servers that do not answer, on the current version; the loop does the same by itself when
searches keep failing on a server (`src/lean_search/rl/README.md`, "The loop", server failures) and stops with an
error if a restarted server stays down.

Restart after a crash: `deployment/grpo_loop.sh loop` again (servers still up; otherwise `servers` first: they start on
the current version). The loop finishes an interrupted phase before sampling again. After the health check's hard stop
(`loop.log`: "The loop stopped after phase <k> on its health check", `$LEAN_SEARCH_RUNS/<loop>/health_stop.json`; the
held-out valid-Lean rate fell below 0.7 × version 0's) the loop refuses to start until `python
experiments/grpo_loop.py --config <loop.toml> rollback` (the last good version's policy as a new version; lower the
learning rate first) or `clear-health-stop` (keep the current version) ran (`src/lean_search/rl/README.md`, "Health
checks and budget signals"). The search budget (`[sampling] max_expansions`, 32) and the `[health]` thresholds change
the same way: edit the loop config, `stop`, `loop`. Milestones: `python
experiments/grpo_loop.py --config experiments/configs/grpo/loop.toml request-evaluation --target minif2f` (run at the
next pause); with the loop stopped, `python experiments/grpo_evaluate.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1
--target minif2f`. To end: `deployment/grpo_loop.sh stop`, then the final miniF2F and probe with grpo_evaluate.py.

First-hour checks:

- `check` prints, per policy server, one request the way the search sends it (the visible prompt, n = 8, 1,024
  tokens, temperature 0.8): `tokens_recorded` (token ids with one log-probability each), `tokens_decode_to_text`
  (the token ids decode to the text, plus the end of turn), `usable_blocks` > 0 and the finish reasons; it fails if any
  is missing. `servers` starts policy servers with `--logprobs-mode processed_logprobs` (`serve-commands` prints every
  start command); after the first phase the dashboard's sampler-vs-trainer
  difference (`grpo` family, `sampler_absolute_log_probability_difference`) must be small (bf16 resolution, ~0.01-0.05
  nats); a raw-mode server shows a systematic offset from the 1/0.8 temperature scaling. The same by sampling age
  (`sampler_by_age`, the Policy page): age 0 is that number, ages 1+ are samples from earlier versions in trees that
  spanned a phase, with the staleness on top. The first step of phase 1 should show `mean_ratio` 1 and
  `clip_fraction` 0 (`steps.jsonl` of the phase's policy output).
- Publishing keeps the update: after phase 1, `weights/v0001/policy` should differ from `v0000/policy` in a large
  share of the adapted layers' elements (merging the continued SFT adapter into the raw base, not into merged weights).
- Timings: version 0's probe (three parts, each twice) and the held-out-states run before the first phase give a
  probe slot's wall time (`fixed_targets.evaluation_seconds` per part; target 13-20 min at concurrency 64, a slot every
  ~2 h and a value arm every other slot, ~10-15% of the loop; else lower `probe_per_stratum` to 100 and re-select
  before the loop starts); the first phase's `timing` line gives sampling vs training (two passes if
  training stays well below sampling, else `passes_per_phase = 1` in `phase.toml`) and publishing.
- The pause, segment by segment (`loop.log`'s `Phase <k> pause:` line, the `timing` family's `pause.*`, the System
  page's "Pause segments"; `src/lean_search/rl/README.md`, "Timing" and "Persistent trainer"). Expected on four GPUs
  with the persistent job: `drain` and `server_sleep` seconds; `trainer_start` 0 (the job and its models came up
  during the first sampling: `Persistent trainer started` and `Policy ... resident after` in the logs); `compile` 1-2
  minutes in the first phase only, and `phase.json`'s `timings.compiled_graphs` 0 from the second phase on (`trainer.log`
  prints it per phase; a count every phase means recompilation, worth its own look); `preparation` well under a
  minute outside value phases; `policy_load` (unpark) and `park` seconds; `scoring` plus `policy_training` about a
  quarter of the one-GPU 4-8 minutes; `value_training` (~2-3 minutes) in value phases;
  `merge` and `handoff` well under a minute; `publish` ~0 (`Published version <k> from host memory` in `loop.log`; a
  `publish` of a minute or more means the CPU merge ran); `wake` a few seconds per server; then `durable_write` about
  a minute in the background (`Version <k> written to disk and recorded`). Together about 1 minute outside value
  phases; if the fixed segments still dominate, compare one phase with `gpus = [0]` before deciding.
- The parked job's GPU memory between phases: `nvidia-smi` while sampling shows each GPU's two servers plus the
  trainer rank's CUDA context and NCCL buffers (~0.5-1 GiB); a wake failing on memory means the servers' shares
  (0.62 + 0.28) leave too little beside it: lower `GPU_MEMORY_UTILIZATION` of the value servers by 0.02.
- Training on the GPUs the servers left: `nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv -l 5`
  during the first training stage. Each GPU holds the two sleeping servers' remainder (~1.6 GiB) plus one rank; the
  ranks' `peak_memory_gib` (largest over ranks) is in `phase.json`. An out-of-memory rank fails the job (the loop
  stops; the stage reruns after a restart): lower `[policy.optimization] micro_batch_tokens` (each rank keeps the
  one-GPU micro-batch size) or `scoring_micro_batch_tokens`. `training/phase_<k>.log` interleaves the ranks' output;
  a hang in the first all-reduce on a PCIe node without peer-to-peer access is fixed with `NCCL_P2P_DISABLE=1` in the
  loop's environment.
- Probe validity: `fixed_targets.probe_wall_clock_stops` must be ~0 (the 1-hour cap is an emergency stop; if it binds,
  the probe measures load). The second version-0 run of each part gives the noise: `probe_repeat_difference` and
  `probe_repeat_discordant` per part (Evaluations page; `evaluations/probe_slot000<k>_v0000_repeat1/comparison.json`,
  and the sum over the parts in `loop.log`); later differences of the whole set smaller than about twice the summed
  discordant count's square root are noise.
- Value statistics: `loop.log` has a `Value benchmark of value v0: ...` line soon after the start (v0 scoring the
  benchmark through the value servers while the searches run; seconds, not minutes) and one per published value model;
  the Value page shows the per-phase `value_phase` charts from phase 1 on and the first value arm at the first even
  probe slot after the first value retrain. Set μ only by hand (`value-share`).
- Memory (System page, budget in `src/lean_search/rl/README.md`, "Host memory"): `memory_total_gib`,
  `memory_available_gib`, `lean_private_memory_gib` and its p90, `vllm_private_memory_gib`, once while sampling, once
  while training (four ranks, each with the phase's trees, after the paused searches' REPLs stopped) and once during
  the probe; in a value phase (phase 4 with the defaults, a value phase every phase in the smoke cycle) the ranks hold
  the window's trees. `loop.log` reports the paused REPL processes stopped before training and before each evaluation
  and the host memory at each stage boundary of the pause (`Host memory before training: ...`). Lower
  `[evaluation.probe] concurrency` or `[sampling] concurrency` if available memory falls below ~15% of the limit. Lean
  cores near the thread count and GPU utilization above ~80% mean the concurrency fits.
- Server failures: `status.server_failures` stays at 0 on a healthy run; failed searches feed their statement again
  (`[sampling] server_failure_retries`), `statements_given_up` counts the dropped ones; `loop.log` reports any check
  and restart of the servers.
- Curriculum (main loop, after about 2 hours): the realized solve rate (Curriculum page) within the 30-70% band; each
  band is judged on the first 50 statements fed at it once all finished, so slow unsolved searches no longer pull it
  down. Also expansions and trees per hour and trainable groups per phase (Training page, "Trainable groups per
  phase"; `loop.log`'s `Phase <k>: ... trainable groups`): a phase ends at 300 within 45-90 min; phases that always
  hit the 90-minute cap, or always stop at 45 minutes far above 300, mean the trigger should be set once.
- Health (Training page and `loop.log`'s `Health of phase <k>` lines, from phase 1): KL to the starting policy and
  the clip fraction against their thresholds (0.02 and 0.1), distinct blocks per expansion (~5-7 of 8 expected),
  explanation length and cut-off samples; the relative thresholds appear from phase 3 on (the mean of phases 1-2) and
  the held-out ones once version 0's held-out evaluation exists. Version 0's held-out valid-Lean rate and success
  (Evaluations page) set the hard stop (0.7 × valid-Lean rate). At lr 3e-5 watch the first phases' KL and clip
  fraction closely.

First-day checks:

- Health thresholds: after 4-6 phases compare each signal's spread with its threshold and recalibrate `[health]` once
  (restart to apply): no alert should fire on phase-to-phase noise; the held-out checks after the first 6-hour
  evaluation.
- Search budget (Training page, "Search budget"): the share of solves in expansions 25-32 (a note above 10% over 3
  phases), the expansions-to-first-proof distribution, the mean proof length and the difficulty of the solved
  statements over phases. Solves crowding into the last quarter while proof lengths and solved difficulty stall mean
  32 expansions cut off harder proofs: raise `[sampling] max_expansions` to 64.
- Disk: `disk_free_gib` (System page) and its fall per phase against the projection above.
- Training memory: `peak_memory_gib` in `$LEAN_SEARCH_CHECKPOINTS/grpo_loop_v1_phase_0001/phase.json`, against
  24 GiB minus the sleeping servers' remainder.

Cheap tests (DESIGN.md "Order of work", step 3), with the same servers:

```bash
# Single-step GRPO, per-tactic vs sequence credit (~1 GPU-hour each; the loop must not run).
python experiments/phase5_reasoning_data.py states \
    --config experiments/configs/grpo/single_step_disjoint_states.toml --run-name grpo_single_step_disjoint_states
CUDA_VISIBLE_DEVICES=0 python experiments/grpo_single_step.py --config experiments/configs/grpo/single_step.toml run --arm per_tactic
CUDA_VISIBLE_DEVICES=0 python experiments/grpo_single_step.py --config experiments/configs/grpo/single_step.toml run --arm sequence
python experiments/grpo_single_step.py --config experiments/configs/grpo/single_step.toml report
# Overfit on 300 statements: a few phases, the solve rate per phase must rise.
LOOP_CONFIG=experiments/configs/grpo/loop_overfit.toml deployment/grpo_loop.sh init   # then servers, loop
python experiments/grpo_loop.py --config experiments/configs/grpo/loop_overfit.toml report
# Naming A/B (after the data rewrite's two fine-tunes; renamings first for the named arm).
python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml rename \
    --rewrite-config experiments/configs/data_rewrite/rewrite_visible_student_v2.toml \
    --sources probe gate pool minif2f --output grpo/renamings.jsonl
python experiments/grpo_naming_ab.py --config experiments/configs/grpo/naming_ab.toml probe --arm numbered
python experiments/grpo_naming_ab.py --config experiments/configs/grpo/naming_ab.toml probe --arm named
python experiments/reasoning_retention.py --config experiments/configs/evaluation/reasoning_retention_naming_ab.toml \
    run --gpu 0 --labels naming-numbered naming-named
python experiments/grpo_naming_ab.py --config experiments/configs/grpo/naming_ab.toml report
```

The single-step test and the naming A/B swap weights into the policy servers; restore the loop's version afterwards
(`servers` after `stop_model.sh --all`, or the loop's own start swaps them back).

## Node layout

| Path | Contents | Persistent |
|---|---|---|
| `/workspace/LLM-Search-Lean-Proofs` | repository checkout, `.venv`, `lean/.lake` | no |
| `/workspace/data` | downloaded and traced datasets | no |
| `/workspace/runs` | search logs and per-theorem results | no |
| `/workspace/checkpoints` | LoRA adapters and value models | no |
| `/workspace/.hf_home` | Hugging Face cache | no |

`/workspace` was not a volume on the first node, so anything that must survive the rental is either committed
(summaries under `results/`) or copied back to the local machine (adapters under the untracked `artifacts/`).

Without a writable `/workspace` (local WSL), `environment.sh` uses `~/lean-search-workspace` instead
(`LEAN_SEARCH_WORKSPACE` overrides both).

## Second node (returned within the hour, 2026-10-29)

4× RTX 3090 (PCIe 4.0 x16), AMD EPYC 7K62 with a 92-core cgroup quota, ~171 GiB RAM cgroup limit, 200 GB disk,
62 GB `/dev/shm`, driver 595 (CUDA 13.2), China. GitHub, huggingface.co and pypi.org unreachable (ghfast.top,
hf-mirror.com and the Tsinghua mirror worked), and uploads from the local machine ran at ~34 KB/s, too slow for the
~2 GB of adapters and data from `node_backup/`. Check the upload speed (and GitHub) before setting a node up.

## First node (returned)

2× RTX 3090 (24 GB), AMD EPYC 7K62 with a 46-core cgroup quota, ~120 GB RAM cgroup limit, 300 GB disk,
Ubuntu 24.04, CUDA 12.8, driver 595. Network: GitHub reachable; huggingface.co blocked (use hf-mirror.com);
pypi.org slow (use a mirror).
