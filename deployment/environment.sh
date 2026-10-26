#!/usr/bin/env bash
# Sourced on the node by every deployment script and by deployment/on_node.sh.
#
# Downloads go direct. Mirrors are opt-in for networks without direct access (the first node, in China):
#   HF_ENDPOINT=https://hf-mirror.com
#   LEAN_SEARCH_GITHUB_PROXY=https://ghfast.top/                        (setup_lean.sh)
#   LEAN_SEARCH_PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple    (setup_python.sh)

export LEAN_SEARCH_ROOT="${LEAN_SEARCH_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# /workspace on nodes; machines without it (local WSL) keep the same layout under the home directory.
if [[ -z "${LEAN_SEARCH_WORKSPACE:-}" ]]; then
    if [[ -w /workspace ]]; then
        LEAN_SEARCH_WORKSPACE=/workspace
    else
        LEAN_SEARCH_WORKSPACE="${HOME}/lean-search-workspace"
    fi
fi
export LEAN_SEARCH_WORKSPACE
export LEAN_SEARCH_DATA="${LEAN_SEARCH_DATA:-${LEAN_SEARCH_WORKSPACE}/data}"
export LEAN_SEARCH_RUNS="${LEAN_SEARCH_RUNS:-${LEAN_SEARCH_WORKSPACE}/runs}"
export LEAN_SEARCH_CHECKPOINTS="${LEAN_SEARCH_CHECKPOINTS:-${LEAN_SEARCH_WORKSPACE}/checkpoints}"

export HF_HOME="${HF_HOME:-${LEAN_SEARCH_WORKSPACE}/.hf_home}"
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
if [[ "${HF_ENDPOINT:-}" == *hf-mirror.com* ]]; then
    # hf-mirror.com serves plain files, but Xet downloads go to cas-server.xethub.hf.co and fail with 401.
    export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
fi

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
