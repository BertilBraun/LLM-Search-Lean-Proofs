#!/usr/bin/env bash
# The follow-up's probe evaluations, one after another on the node (experiments/probe_evaluate.py; run lists such as
# experiments/configs/grpo/followup/step1/runs_*.toml, src/lean_search/rl/probe_run_list.py).
#
#   BACKGROUND_CPUS=40 PROBE_CONCURRENCY=56 deployment/probe_runs.sh <run list.toml> [<run list.toml> ...]
#
# Several lists are interleaved (their first runs, then their second runs, ...), so two arms' checkpoints alternate.
# Refuses without a run list, without BACKGROUND_CPUS (every evaluation runs pinned through background.sh) or
# PROBE_CONCURRENCY (the throughput test's one probe concurrency, which every run's evaluation config must hold), on a
# placeholder left in a run or its configs, while the serving lock is held or a loop runs. Starts the servers that do
# not answer (deployment/grpo_loop.sh servers with the runs' loop config, initialized once with grpo_loop.sh init).
# A finished run is skipped and an interrupted one resumed, so rerun the same command after an interruption; a rejected
# run (exit status 3: too many wall-clock stops) stops the list. One line per finished run goes to
# $LEAN_SEARCH_RUNS/<output>/ledger.tsv.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

[[ $# -ge 1 ]] || { sed -n '2,14p' "$0" >&2; exit 2; }
[[ -n "${BACKGROUND_CPUS:-}" ]] || { echo "Set BACKGROUND_CPUS: every evaluation runs pinned (DESIGN.md, Load)." >&2; exit 2; }
[[ -n "${PROBE_CONCURRENCY:-}" ]] || { echo "Set PROBE_CONCURRENCY to the throughput test's probe concurrency." >&2; exit 2; }

loop_config="$(python experiments/probe_runs.py check --concurrency "${PROBE_CONCURRENCY}" "$@")"
python experiments/probe_runs.py record "$@"
LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" servers

next_file="$(mktemp)"
trap 'rm -f "${next_file}"' EXIT
while true; do
    status=0
    python experiments/probe_runs.py next "$@" > "${next_file}" || status=$?
    (( status == 0 )) || { echo "Stopped before the next run (exit ${status})." >&2; exit "${status}"; }
    if [[ ! -s "${next_file}" ]]; then
        echo "Every run of the lists is accepted."
        break
    fi
    mapfile -d '' -t arguments < "${next_file}"
    echo "$(date -Is) probe_evaluate.py ${arguments[*]}"
    status=0
    HF_HUB_OFFLINE=1 "${script_directory}/background.sh" python experiments/probe_evaluate.py "${arguments[@]}" || status=$?
    python experiments/probe_runs.py record "$@"
    case "${status}" in
        0) ;;
        3)
            echo "The run was rejected (too many wall-clock stops): repeat it under another name with the wall cap" \
                "doubled, and every run it is compared with at that cap. The list stops here." >&2
            exit 3
            ;;
        *)
            echo "probe_evaluate.py failed (exit ${status}); rerun this command to resume." >&2
            exit "${status}"
            ;;
    esac
done
