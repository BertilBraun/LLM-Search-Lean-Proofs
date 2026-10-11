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
