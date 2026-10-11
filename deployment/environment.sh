#!/usr/bin/env bash
# Sourced on the node by every deployment script and by deployment/on_node.sh.

export LEAN_SEARCH_ROOT="${LEAN_SEARCH_ROOT:-/workspace/LLM-Search-Lean-Proofs}"
export LEAN_SEARCH_DATA="${LEAN_SEARCH_DATA:-/workspace/data}"
export LEAN_SEARCH_RUNS="${LEAN_SEARCH_RUNS:-/workspace/runs}"
export LEAN_SEARCH_CHECKPOINTS="${LEAN_SEARCH_CHECKPOINTS:-/workspace/checkpoints}"

# The node cannot reach huggingface.co directly, and pypi.org is slow from it.
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="${HF_HOME:-/workspace/.hf_home}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"

export PATH="${HOME}/.elan/bin:${LEAN_SEARCH_ROOT}/.venv/bin:${PATH}"

# Vast.ai containers report the host's nproc but are throttled to a cgroup quota.
effective_cpu_count() {
    local quota period
    if [[ -r /sys/fs/cgroup/cpu.max ]]; then
        read -r quota period < /sys/fs/cgroup/cpu.max
        if [[ "${quota}" != max ]]; then
            echo $(( quota / period > 0 ? quota / period : 1 ))
            return
        fi
    fi
    nproc
}
export LEAN_SEARCH_CPU_COUNT="${LEAN_SEARCH_CPU_COUNT:-$(effective_cpu_count)}"

mkdir -p "${LEAN_SEARCH_DATA}" "${LEAN_SEARCH_RUNS}" "${LEAN_SEARCH_CHECKPOINTS}" "${HF_HOME}"
ulimit -Sn 65536 2>/dev/null || true
