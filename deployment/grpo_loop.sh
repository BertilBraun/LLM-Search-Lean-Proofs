#!/usr/bin/env bash
# The search-tree GRPO loop on a 4x RTX 3090 node, one step at a time (deployment/README.md, "GRPO loop").
#
#   deployment/grpo_loop.sh node-check           # first: disk, /dev/shm, CPUs, GPU topology, a 4-rank NCCL all-reduce
#   deployment/grpo_loop.sh sets                 # once: probe, value benchmark (gate) and overfit sets (CPU)
#   deployment/grpo_loop.sh init                 # once: version 0 (merges the policy and value [initial] adapters)
#   deployment/grpo_loop.sh servers              # start the vLLM servers not answering on the current version
#                                                # (a GPU's two one after another, the GPUs in parallel)
#   deployment/grpo_loop.sh check                # one live request per policy server: what the search parses
#   deployment/grpo_loop.sh gate                 # once, ~1-2 h: the value benchmark of the gate set (no value model)
#   deployment/grpo_loop.sh dashboard            # system sampler and dashboard on port ${DASHBOARD_PORT:-8600}
#   deployment/grpo_loop.sh loop                 # the loop in the background; rerun after a crash to resume
#   deployment/grpo_loop.sh status               # progress, versions, trees, the last phase, μ
#   deployment/grpo_loop.sh value-share 0.15     # μ from the next phase that starts training (0: off; starts at 0)
#   deployment/grpo_loop.sh stop                 # stops the loop (SIGTERM: saves its state, stops its job), servers
#
# LOOP_CONFIG (default experiments/configs/grpo/loop.toml) picks the loop, e.g. loop_smoke.toml for the smoke cycle or
# loop_overfit.toml for the overfit test.
# HOURLY_PRICE (0.80) feeds the dashboard's cost; BACKGROUND_CPUS, if set, pins the loop (its Lean REPLs) through
# background.sh.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

config="${LOOP_CONFIG:-experiments/configs/grpo/loop.toml}"
name="$(python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["name"])' "${config}")"
run_directory="${LEAN_SEARCH_RUNS}/${name}"

[[ $# -ge 1 ]] || { sed -n '2,21p' "$0" >&2; exit 2; }

case "$1" in
    node-check)
        mkdir -p "${LEAN_SEARCH_RUNS}" "${LEAN_SEARCH_CHECKPOINTS}"
        df -h "${LEAN_SEARCH_RUNS}" "${LEAN_SEARCH_CHECKPOINTS}" /dev/shm
        nproc
        cat /sys/fs/cgroup/cpu.max 2>/dev/null || true
        nvidia-smi topo -m
        shm_mebibytes=$(( $(df -k --output=size /dev/shm | tail -n 1) / 1024 ))
        # The persistent trainer keeps its parked bases (~14 GiB) and the merges it hands to the servers (~14 GiB) there.
        if (( shm_mebibytes < 30720 )); then
            echo "/dev/shm holds ${shm_mebibytes} MiB, too small for the persistent trainer and NCCL (docker --shm-size 32g)" >&2
            exit 1
        fi
        python -m torch.distributed.run --standalone --nproc-per-node "$(nvidia-smi -L | wc -l)" experiments/nccl_check.py
        ;;
    sets)
        python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select
        python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select-overfit
        ;;
    init)
        python experiments/grpo_loop.py --config "${config}" init
        ;;
    servers)
        python experiments/grpo_loop.py --config "${config}" start-servers
        ;;
    check)
        python experiments/grpo_loop.py --config "${config}" check-servers
        ;;
    gate)
        python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml gate-benchmark \
            --search-config experiments/configs/grpo/gate_search.toml --run-name grpo_gate_search \
            --output grpo_gate/benchmark.json.gz 2>&1 | tee -a "${LEAN_SEARCH_RUNS}/grpo_gate_search.log"
        ;;
    dashboard)
        mkdir -p "${run_directory}"
        nohup python experiments/dashboard.py record-system --run-directory "${run_directory}" \
            --hourly-price "${HOURLY_PRICE:-0.80}" > "${run_directory}/system_sampler.log" 2>&1 &
        nohup python experiments/dashboard.py serve --run-directory "${run_directory}" --host 0.0.0.0 \
            --port "${DASHBOARD_PORT:-8600}" --config experiments/configs/dashboard/dashboard.toml \
            > "${run_directory}/dashboard.log" 2>&1 &
        echo "Dashboard on port ${DASHBOARD_PORT:-8600}; logs in ${run_directory}/{system_sampler,dashboard}.log"
        ;;
    loop)
        mkdir -p "${run_directory}"
        prefix=()
        if [[ -n "${BACKGROUND_CPUS:-}" ]]; then
            prefix=("${script_directory}/background.sh")
        fi
        # The bases are cached by init; offline, an unreachable Hub cannot fail a tokenizer load mid-run.
        HF_HUB_OFFLINE=1 nohup "${prefix[@]}" python experiments/grpo_loop.py --config "${config}" run \
            >> "${run_directory}/loop.out" 2>&1 &
        echo $! > "${run_directory}/loop.pid"
        echo "Loop ${name} started (pid $(cat "${run_directory}/loop.pid")); log ${run_directory}/loop.log"
        ;;
    status)
        python experiments/grpo_loop.py --config "${config}" status
        ;;
    value-share)
        [[ $# -eq 2 ]] || { echo "usage: $0 value-share <mu in [0, 1]>" >&2; exit 2; }
        python experiments/grpo_loop.py --config "${config}" set-value-share "$2"
        ;;
    stop)
        if [[ -f "${run_directory}/loop.pid" ]]; then
            kill -TERM "$(cat "${run_directory}/loop.pid")" 2>/dev/null || true
            rm -f "${run_directory}/loop.pid"
        fi
        "${script_directory}/stop_model.sh" --all
        ;;
    *)
        echo "Unknown step $1" >&2
        exit 2
        ;;
esac
