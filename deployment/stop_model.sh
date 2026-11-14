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

status=0
for pid_file in ${pid_files[@]+"${pid_files[@]}"}; do
    name="$(basename "${pid_file}" .pid)"
    if [[ ! -f "${pid_file}" ]]; then
        echo "No server named ${name}." >&2
        continue
    fi
    # serve_model.sh starts vLLM with setsid, so its pid is the process group of the API server and engine core.
    if ! process_group="$(trusted_server_pid "${pid_file}" "${name}")"; then
        found=0
        process_group="$(orphaned_server_group "${pid_file}" "${name}")" || found=$?
        case "${found}" in
            0) ;;
            1)
                echo "Stale pid file ${pid_file}: no vLLM of ${name} started with it; removed, nothing signalled." >&2
                rm -f "${pid_file}" "${pid_file%.pid}.members"
                continue
                ;;
            *)
                echo "Refused: ${pid_file}'s process group has members that are not ${name}'s vLLM" \
                    "(${process_group}); nothing signalled, the pid file kept. Look before stopping them by pid." >&2
                status=1
                continue
                ;;
        esac
    fi
    kill -TERM -- "-${process_group}" 2>/dev/null || true
    for _ in $(seq 60); do
        [[ -n "$(live_group_members "${process_group}")" ]] || break
        sleep 1
    done
    if [[ -n "$(live_group_members "${process_group}")" ]]; then
        kill -KILL -- "-${process_group}" 2>/dev/null || true
    fi
    rm -f "${pid_file}" "${pid_file%.pid}.members"
    echo "Stopped ${name}."
done
exit "${status}"
