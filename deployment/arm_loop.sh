#!/usr/bin/env bash
# An arm's loop (or step 2's shared sampling) started detached from its overlay (DESIGN.md, "Follow-up study:
# controlled arms"; experiments/configs/grpo/followup/arms/, followup/shared_sampling.toml).
#
#   BACKGROUND_CPUS=52 deployment/arm_loop.sh experiments/configs/grpo/followup/arms/A.toml
#   BACKGROUND_CPUS=52 deployment/arm_loop.sh --kind "shared sampling" experiments/configs/grpo/followup/shared_sampling.toml
#
# Refuses without BACKGROUND_CPUS (the Lean side of every arm runs pinned, below the cgroup quota), while the serving
# lock is held or a loop runs, and when experiments/followup_arm.py refuses the overlay (a placeholder left, a setting
# outside the arm's own, no token budget per phase or no phase count). Writes the arm's configs under
# $LEAN_SEARCH_RUNS/followup_configs/<name>/ (the same again on a restart), records version 0 once
# (deployment/grpo_loop.sh init), then starts the loop detached through deployment/grpo_loop.sh loop, which resumes an
# interrupted one. Prints where the logs are.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
cd "${script_directory}/.."

kind=arm
if [[ "${1:-}" == --kind ]]; then
    kind="$2"
    shift 2
fi
[[ $# -eq 1 ]] || { sed -n '2,13p' "$0" >&2; exit 2; }
[[ -n "${BACKGROUND_CPUS:-}" ]] || { echo "Set BACKGROUND_CPUS: every arm runs pinned (DESIGN.md, Load)." >&2; exit 2; }

python experiments/node_checks.py pinning --background-cpus "${BACKGROUND_CPUS}"
python experiments/node_checks.py servers-free
loop_config="$(python experiments/followup_arm.py --kind "${kind}" --arm "$1" --output "${LEAN_SEARCH_RUNS}/followup_configs")"
name="$(python -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["name"])' "${loop_config}")"
run_directory="${LEAN_SEARCH_RUNS}/${name}"

if [[ ! -f "${run_directory}/models/current.json" ]]; then
    LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" init
fi
LOOP_CONFIG="${loop_config}" "${script_directory}/grpo_loop.sh" loop
echo "Logs: ${run_directory}/loop.out (its output), ${run_directory}/loop.log; pid in ${run_directory}/loop.pid"
