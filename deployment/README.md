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
| `grpo_loop.sh` | node | The GRPO loop step by step: held-out sets, version 0, servers, checks, gate, dashboard, loop, status. |
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

So a publish costs about 20 s (merge plus reload), and the train-on-both-GPUs loop is: `release` all servers, train
with DDP, merge, `restore` with the new directory, and the searches' queued requests continue (a request sent during
a 35 s release completed right after the restore). Search clients must allow requests that long
(`request_timeout_seconds`), and searches in flight keep their wall-clock budgets running while paused. A weight
reload drops the workers' LoRA adapters: re-register them (`publish_weights.py difference ... --name value-v0`
re-creates and reloads a difference adapter).

Re-scoring a frontier after a new value version: all 14,879 open states of the 244 row-4 trees take 105 s on both
GPUs' merged value instances (141 states/s, ~17k prompt tokens/s per GPU, compute-bound; the value prompts share no
cacheable prefix because hybrid-model prefix caching works in 544-token blocks). The value estimator sends 32 states
per request: one request per state cost the client ~10 ms of CPU each. A larger prefill chunk
per step (`MAX_NUM_BATCHED_TOKENS=16384`) did not change the rate. At 120 searches the open frontiers hold
an estimated 5k states (half the trees' final frontiers, 61 on average), about 35 s; re-score larger frontiers
best-first or lazily.

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

| GPU | Role |
|---|---|
| 0 | training: the policy GRPO phase, then the value model and its gate (`[training] gpu`) |
| 1-3 | serving: the merged policy (port 810x, 62% of memory, `--logprobs-mode processed_logprobs`) and the merged value model (port 820x, 28%, `MAX_NUM_SEQS=96`) |

The loop process holds one Lean REPL per concurrent search (`[sampling] concurrency`, 112) and runs the training and
evaluation jobs as child processes. Servers on the training GPU (none by default) would sleep during each phase.

Bring-up on a fresh node, after the rebuild (`setup_remote.sh`, pool v3 verified statements under
`$LEAN_SEARCH_DATA/expert_iteration/pool_v3/`, from `node_backup/` the merged starting policy at
`$LEAN_SEARCH_CHECKPOINTS/grpo_start/merged`, the value v0 adapter at `phase3_value_v0/adapter`, and the per-step
evaluation's states at `$LEAN_SEARCH_RUNS/phase5_eval_visible_student_v2_visible/states.jsonl`):

```bash
deployment/grpo_loop.sh sets         # probe (501), gate (402) and overfit (300) sets under $LEAN_SEARCH_DATA/grpo/
deployment/grpo_loop.sh init         # version 0: the starting policy as is, the value v0 adapter merged (~20 s)
deployment/grpo_loop.sh servers      # six vLLM servers on GPUs 1-3 (each waits until healthy)
deployment/grpo_loop.sh check        # one live request per policy server (below)
python experiments/heartbeat_replay.py ...   # the heartbeat caps (DESIGN.md "Lean execution and harness")
deployment/grpo_loop.sh gate         # the value gate's benchmark, ~1-2 h, before value phases can publish
deployment/grpo_loop.sh dashboard    # http://<node>:8600 (open; tunnel or mapped port: "Dashboard" above)
deployment/grpo_loop.sh loop         # probe and held-out states of version 0 first, then sampling
deployment/grpo_loop.sh status       # or the dashboard; `tail -f $LEAN_SEARCH_RUNS/grpo_loop_v1/loop.log`
```

Restart after a crash: `deployment/grpo_loop.sh loop` again (servers still up; otherwise `servers` first: they start on
the current version). The loop finishes an interrupted phase before sampling again. Milestones: `python
experiments/grpo_loop.py --config experiments/configs/grpo/loop.toml request-evaluation --target minif2f` (run at the
next pause); with the loop stopped, `python experiments/grpo_evaluate.py --loop-directory $LEAN_SEARCH_RUNS/grpo_loop_v1
--target minif2f`. To end: `deployment/grpo_loop.sh stop`, then the final miniF2F and probe with grpo_evaluate.py.

First-hour checks:

- `check` prints, per policy server, one request the way the search sends it (the visible prompt, n = 8, 1,024
  tokens, temperature 0.8): `tokens_recorded` (token ids with one log-probability each), `tokens_decode_to_text`
  (the token ids decode to the text, plus the end of turn), `usable_blocks` > 0 and the finish reasons; it fails if any
  is missing. `serve-commands` starts policy servers with `--logprobs-mode processed_logprobs`; after the first phase the dashboard's sampler-vs-trainer
  difference (`grpo` family, `sampler_absolute_log_probability_difference`) must be small (bf16 resolution, ~0.01-0.05
  nats); a raw-mode server shows a systematic offset from the 1/0.8 temperature scaling.
- Timings: the version-0 probe and held-out-states runs before the first phase give the probe's wall time
  (`fixed_targets.evaluation_seconds`; target 40-60 min, else lower `probe_per_stratum` to 100 and re-select before the
  loop starts); the first phase's `timing` line gives sampling vs training (two passes if training stays well below
  sampling, else `passes_per_phase = 1` in `phase.toml`) and publishing (~20 s merge plus swaps).
- Memory and CPU (System page): the paused searches' REPLs plus the evaluation's own pool during the probe; lower
  `[evaluation.probe] concurrency` or `[sampling] concurrency` if memory runs short. Lean cores near the thread count
  and GPU utilization above ~80% mean the concurrency fits.
- Training memory: `peak_memory_gib` in `$LEAN_SEARCH_CHECKPOINTS/grpo_loop_v1_phase_0001/phase.json`.

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

## First node (returned)

2× RTX 3090 (24 GB), AMD EPYC 7K62 with a 46-core cgroup quota, ~120 GB RAM cgroup limit, 300 GB disk,
Ubuntu 24.04, CUDA 12.8, driver 595. Network: GitHub reachable; huggingface.co blocked (use hf-mirror.com);
pypi.org slow (use a mirror).
