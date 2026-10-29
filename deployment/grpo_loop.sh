#!/usr/bin/env bash
# The search-tree GRPO loop on a 4x RTX 3090 node, one step at a time (deployment/README.md, "GRPO loop").
#
#   deployment/grpo_loop.sh sets                 # once: probe, value gate and overfit statement sets (CPU)
#   deployment/grpo_loop.sh init                 # once: version 0 (merges the policy and value [initial] adapters)
#   deployment/grpo_loop.sh servers              # start every vLLM server on the current version (~2-5 min each)
#   deployment/grpo_loop.sh check                # one live request per policy server: what the search parses
#   deployment/grpo_loop.sh gate                 # once, ~1-2 h: the value gate's benchmark (no value model)
#   deployment/grpo_loop.sh dashboard            # system sampler and dashboard on port ${DASHBOARD_PORT:-8600}
#   deployment/grpo_loop.sh loop                 # the loop in the background; rerun after a crash to resume
#   deployment/grpo_loop.sh status               # progress, versions, trees, the last phase
#   deployment/grpo_loop.sh stop                 # stops the loop (SIGTERM; it saves its state) and the servers
#
# LOOP_CONFIG (default experiments/configs/grpo/loop.toml) picks the loop, e.g. loop_overfit.toml for the overfit test.
# HOURLY_PRICE (0.80) feeds the dashboard's cost; BACKGROUND_CPUS, if set, pins the loop (its Lean REPLs) through
# background.sh.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

config="${LOOP_CONFIG:-experiments/configs/grpo/loop.toml}"
name="$(python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["name"])' "${config}")"
run_directory="${LEAN_SEARCH_RUNS}/${name}"

[[ $# -ge 1 ]] || { sed -n '2,17p' "$0" >&2; exit 2; }

case "$1" in
    sets)
        python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select
        python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select-overfit
        ;;
    init)
        python experiments/grpo_loop.py --config "${config}" init
        ;;
    servers)
        python experiments/grpo_loop.py --config "${config}" serve-commands | while read -r command; do
            echo "+ ${command}"
            bash -c "${command}"
        done
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
        nohup "${prefix[@]}" python experiments/grpo_loop.py --config "${config}" run \
            >> "${run_directory}/loop.out" 2>&1 &
        echo $! > "${run_directory}/loop.pid"
        echo "Loop ${name} started (pid $(cat "${run_directory}/loop.pid")); log ${run_directory}/loop.log"
        ;;
    status)
        python experiments/grpo_loop.py --config "${config}" status
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
