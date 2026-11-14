#!/usr/bin/env bash
# Stop vLLM servers started by serve_model.sh.
#
#   deployment/stop_model.sh <name> [<name> ...]
#   deployment/stop_model.sh --all

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
source "${script_directory}/server_pid.sh"

server_directory="${LEAN_SEARCH_RUNS}/servers"

[[ $# -ge 1 ]] || { echo "Usage: stop_model.sh <name> [<name> ...] | --all" >&2; exit 2; }
if [[ "$1" == --all ]]; then
    shopt -s nullglob
    pid_files=("${server_directory}"/*.pid)
else
    pid_files=()
    for name in "$@"; do
        pid_files+=("${server_directory}/${name}.pid")
    done
fi

for pid_file in ${pid_files[@]+"${pid_files[@]}"}; do
    name="$(basename "${pid_file}" .pid)"
    if [[ ! -f "${pid_file}" ]]; then
        echo "No server named ${name}." >&2
        continue
    fi
    # serve_model.sh starts vLLM with setsid, so its pid is the process group of the API server and engine core.
    if ! process_group="$(trusted_server_pid "${pid_file}" "${name}")" &&
        ! process_group="$(orphaned_server_group "${pid_file}")"; then
        echo "Stale pid file ${pid_file}: no vLLM of ${name} started with it; removed, nothing signalled." >&2
        rm -f "${pid_file}"
        continue
    fi
    kill -TERM -- "-${process_group}" 2>/dev/null || true
    for _ in $(seq 60); do
        [[ -n "$(live_group_members "${process_group}")" ]] || break
        sleep 1
    done
    kill -KILL -- "-${process_group}" 2>/dev/null || true
    rm -f "${pid_file}"
    echo "Stopped ${name}."
done
