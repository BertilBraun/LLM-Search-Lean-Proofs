# Deployment

All heavy work runs on one rented Vast.ai node. The local machine only edits code and drives the node over SSH.
Changes reach the node through GitHub: commit locally, then `deployment/deploy.sh` pushes and fast-forwards the
node's checkout.

| Script | Runs on | Purpose |
|---|---|---|
| `remote_command.sh` | local | Run one command on a node over SSH (key, port, banner filtering). |
| `on_node.sh` | local | Run a command inside the node's checkout with `environment.sh` loaded. |
| `deploy.sh` | local | Push the current branch and fast-forward the node to it. |
| `setup_remote.sh` | node | Provision a node: clone the repo, then `setup_python.sh` and `setup_lean.sh`. |
| `environment.sh` | node | Paths, mirrors and `PATH`; sourced by everything else. |
| `setup_python.sh` | node | Create the virtual environment from `uv.lock`. |
| `setup_lean.sh` | node | Install elan, the pinned Lean toolchain, Mathlib (from cache) and the REPL. |

## First-time setup

```bash
echo "HOST:PORT" > deployment/.node_address
deployment/remote_command.sh "$(cat deployment/.node_address)" 'bash -s' < deployment/setup_remote.sh
```

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
