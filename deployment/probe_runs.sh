#!/usr/bin/env bash
# The follow-up's probe evaluations, one after another on the node (experiments/probe_evaluate.py; run lists such as
# experiments/configs/grpo/followup/step1/runs_*.toml, src/lean_search/rl/probe_run_list.py).
#
#   BACKGROUND_CPUS=52 PROBE_CONCURRENCY=84 deployment/probe_runs.sh [--foreground] <run list.toml> [<run list.toml> ...]
#
# By default the lists run detached (nohup), so an SSH drop cannot stop them: the output goes to
# $LEAN_SEARCH_RUNS/probe_runs/<lists>.log, the process id to <lists>.pid, and the command prints both and the ledgers
# ($LEAN_SEARCH_RUNS/<output>/ledger.tsv, one line per finished run): what a watchdog reads. --foreground runs them in
# this shell. Several lists are interleaved (their first runs, then their second runs, ...).
# Refuses without a run list, without BACKGROUND_CPUS (every evaluation runs pinned through background.sh; the pinned
# set must lie below the cgroup quota) or PROBE_CONCURRENCY (the throughput test's one probe concurrency, which every
# run's evaluation config must hold), on a placeholder or a missing adapter or probe set, while the serving lock is
# held or a loop runs, and while the same lists already run. Starts the servers that do not answer
# (deployment/grpo_loop.sh servers with the runs' loop config, initialized once with grpo_loop.sh init). Each run
# records its CPUs and the quota in its pinning.jsonl. A finished run is skipped and an interrupted one resumed, both
# only when its record matches the list, so rerun the same command after an interruption; a rejected run (exit
# status 3: too many wall-clock stops) stops the lists.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

foreground=0
if [[ "${1:-}" == --foreground ]]; then
    foreground=1
    shift
fi
[[ $# -ge 1 ]] || { sed -n '2,18p' "$0" >&2; exit 2; }
[[ -n "${BACKGROUND_CPUS:-}" ]] || { echo "Set BACKGROUND_CPUS: every evaluation runs pinned (DESIGN.md, Load)." >&2; exit 2; }
[[ -n "${PROBE_CONCURRENCY:-}" ]] || { echo "Set PROBE_CONCURRENCY to the throughput test's probe concurrency." >&2; exit 2; }

python experiments/node_checks.py pinning --background-cpus "${BACKGROUND_CPUS}"
python experiments/node_checks.py servers-free
loop_config="$(python experiments/probe_runs.py check --concurrency "${PROBE_CONCURRENCY}" "$@")"

log_directory="${LEAN_SEARCH_RUNS}/probe_runs"
lists_name="$(for list in "$@"; do basename "${list}" .toml; done | paste -sd+ -)"
log_file="${log_directory}/${lists_name}.log"
pid_file="${log_directory}/${lists_name}.pid"

if (( ! foreground )); then
    mkdir -p "${log_directory}"
    if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
        echo "These lists already run (pid $(cat "${pid_file}")); log ${log_file}" >&2
        exit 1
    fi
    nohup "$0" --foreground "$@" >> "${log_file}" 2>&1 &
    echo $! > "${pid_file}"
    echo "Started (pid $!). Log: ${log_file}; pid file: ${pid_file}; ledgers:"
    python experiments/probe_runs.py ledgers "$@"
    exit 0
fi

next_file="$(mktemp)"
cleanup() {
    rm -f "${next_file}"
    if [[ -f "${pid_file}" && "$(cat "${pid_file}")" == "$$" ]]; then
        rm -f "${pid_file}"
    fi
}
trap cleanup EXIT

python experiments/probe_runs.py record "$@"
LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" servers

while true; do
    status=0
    python experiments/probe_runs.py next "$@" > "${next_file}" || status=$?
    (( status == 0 )) || { echo "Stopped before the next run (exit ${status})." >&2; exit "${status}"; }
    if [[ ! -s "${next_file}" ]]; then
        echo "$(date -Is) Every run of the lists is accepted."
        break
    fi
    mapfile -d '' -t fields < "${next_file}"
    run_directory="${fields[0]}"
    arguments=("${fields[@]:1}")
    echo "$(date -Is) probe_evaluate.py ${arguments[*]}"
    "${script_directory}/background.sh" python experiments/node_checks.py record --directory "${run_directory}"
    status=0
    HF_HUB_OFFLINE=1 "${script_directory}/background.sh" python experiments/probe_evaluate.py "${arguments[@]}" || status=$?
    python experiments/probe_runs.py record "$@"
    case "${status}" in
        0) ;;
        3)
            echo "The run was rejected (too many wall-clock stops): repeat it under another name with the wall cap" \
                "doubled, and every run it is compared with at that cap. The lists stop here." >&2
            exit 3
            ;;
        *)
            echo "probe_evaluate.py failed (exit ${status}); rerun this command to resume." >&2
            exit "${status}"
            ;;
    esac
done
