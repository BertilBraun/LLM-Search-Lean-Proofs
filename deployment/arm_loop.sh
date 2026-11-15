#!/usr/bin/env bash
# An arm's loop (or step 2's shared sampling) started detached from its overlay (DESIGN.md, "Follow-up study:
# controlled arms"; experiments/configs/grpo/followup/arms/, followup/shared_sampling.toml).
#
#   BACKGROUND_CPU_LIST=144-191 deployment/arm_loop.sh experiments/configs/grpo/followup/arms/A.toml
#   BACKGROUND_CPUS=52 deployment/arm_loop.sh --kind "shared sampling" experiments/configs/grpo/followup/shared_sampling.toml
#   deployment/arm_loop.sh --status [--kind ...] <overlay>   # running, finished or stopped; which servers are up
#
# Refuses without BACKGROUND_CPUS or BACKGROUND_CPU_LIST (the Lean side of every arm runs pinned, below the cgroup
# quota), while the serving lock is held or a loop runs, and when experiments/followup_arm.py refuses the overlay (a
# placeholder left, a setting outside the arm's own, no token budget per phase or no phase count). Writes the arm's
# configs under $LEAN_SEARCH_RUNS/followup_configs/<name>/ (the same again on a restart), records version 0 once
# (deployment/grpo_loop.sh init), starts the servers that do not answer (grpo_loop.sh servers; a server that cannot
# start fails here), records the CPUs and settings the loop runs under (<run>/pinning.jsonl), then starts the loop
# detached through deployment/grpo_loop.sh loop, which resumes an interrupted one, and fails when the loop has exited
# ARM_LOOP_START_SECONDS (30) later. Prints where the logs are. A run that ended by itself (finished.json: after
# max_phases, or a sampling-only run at its token total) is not started again: the loop leaves its servers up,
# serving the last version, and this says which still run and how to stop them.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

status_only=0
if [[ "${1:-}" == --status ]]; then
    status_only=1
    shift
fi
kind=arm
if [[ "${1:-}" == --kind ]]; then
    kind="$2"
    shift 2
fi
[[ $# -eq 1 ]] || { sed -n '2,18p' "$0" >&2; exit 2; }

loop_config="$(python experiments/followup_arm.py --kind "${kind}" --arm "$1" --output "${LEAN_SEARCH_RUNS}/followup_configs")"
name="$(python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["name"])' "${loop_config}")"
run_directory="${LEAN_SEARCH_RUNS}/${name}"

source "${script_directory}/server_pid.sh"

servers_up() {
    local pid_file
    for pid_file in "${LEAN_SEARCH_RUNS}"/servers/*.pid; do
        [[ -f "${pid_file}" ]] && trusted_server_pid "${pid_file}" "$(basename "${pid_file}" .pid)" > /dev/null &&
            basename "${pid_file}" .pid
    done
    return 0
}

report() {
    local servers
    servers="$(servers_up | paste -sd' ' -)"
    if [[ -f "${run_directory}/loop.pid" ]] && kill -0 "$(cat "${run_directory}/loop.pid")" 2>/dev/null; then
        echo "${name} runs (pid $(cat "${run_directory}/loop.pid")); log ${run_directory}/loop.log"
    elif [[ -f "${run_directory}/finished.json" ]]; then
        echo "${name} finished: $(cat "${run_directory}/finished.json")"
    else
        echo "${name} is not running and has not finished; start it again to resume."
    fi
    if [[ -n "${servers}" ]]; then
        echo "Servers still up: ${servers}. They cost money while nothing searches:" \
            "LOOP_CONFIG=${loop_config} deployment/grpo_loop.sh stop"
    else
        echo "No server is up."
    fi
}

if (( status_only )); then
    report
    exit 0
fi
if [[ -f "${run_directory}/finished.json" ]]; then
    echo "${name} ended by itself; nothing is started." >&2
    report
    exit 0
fi

[[ -n "${BACKGROUND_CPUS:-}${BACKGROUND_CPU_LIST:-}" ]] || {
    echo "Set BACKGROUND_CPUS or BACKGROUND_CPU_LIST: every arm runs pinned (DESIGN.md, Load)." >&2
    exit 2
}
python experiments/node_checks.py pinning
python experiments/node_checks.py servers-free

if [[ ! -f "${run_directory}/models/current.json" ]]; then
    LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" init
fi
# Before detaching: a server that cannot start fails here, not in a loop nobody watches.
LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" servers
"${script_directory}/background.sh" python experiments/node_checks.py record --directory "${run_directory}"
LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" loop
# A loop that refuses its start (a health stop, a held lock, a config error) exits within seconds.
sleep "${ARM_LOOP_START_SECONDS:-30}"
if ! kill -0 "$(cat "${run_directory}/loop.pid")" 2>/dev/null; then
    echo "${name} exited right after its start; the end of ${run_directory}/loop.out:" >&2
    tail -n 30 "${run_directory}/loop.out" >&2
    exit 1
fi
echo "Logs: ${run_directory}/loop.out (its output), ${run_directory}/loop.log; pid in ${run_directory}/loop.pid"
echo "When it ends by itself (finished.json) its servers stay up: deployment/arm_loop.sh --status $1"
