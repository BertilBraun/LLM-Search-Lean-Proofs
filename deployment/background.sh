#!/usr/bin/env bash
# Run a CPU-heavy background job (tracing, pre-filters, Lean stages of probes) so that it cannot starve GPU feeders.
#
#   deployment/background.sh <command> [argument ...]
#   BACKGROUND_CPUS=24 deployment/background.sh python experiments/phase2_trace_proofs.py --processes 24 ...
#   BACKGROUND_CPU_LIST=144-191 deployment/background.sh python experiments/run_search.py ...
#
# The container sees all the host's CPUs but is throttled to a cgroup CPU quota as a whole. Busy processes
# each get a CPU of their own, so nice changes nothing until the quota runs out, and then the whole cgroup, GPU
# feeders included, is throttled for the rest of the period. The job is therefore pinned, to BACKGROUND_CPU_LIST
# (taskset's CPU list, e.g. 48-95,144-191: one socket of a two-socket node) or to the last BACKGROUND_CPUS logical
# CPUs (32 when neither is set; both set is a usage error, and an empty one counts as unset), which caps all background
# jobs together at that many cores and leaves the rest of the quota to the foreground. Only pinned, not niced: the
# Lean REPLs the job starts lower their own priority to 19 (lean/repl.py, LeanReplConfig.niceness), so that a
# foreground thread scheduled onto one of those CPUs still wins it, while what else the job starts (servers,
# training jobs) keeps the caller's priority, which the container could not raise again. Give Lean jobs at most that
# many processes: more would share CPUs and hit wall-clock timeouts that an unpinned run would not.

set -euo pipefail

[[ $# -ge 1 ]] || { echo "Usage: background.sh <command> [argument ...]" >&2; exit 2; }

if [[ -n "${BACKGROUND_CPU_LIST:-}" ]]; then
    if [[ -n "${BACKGROUND_CPUS:-}" ]]; then
        echo "Set BACKGROUND_CPUS or BACKGROUND_CPU_LIST, not both (BACKGROUND_CPU_LIST=${BACKGROUND_CPU_LIST}, e.g." \
            "from the node environment; BACKGROUND_CPU_LIST= unsets it)." >&2
        exit 2
    fi
    cpu_list="${BACKGROUND_CPU_LIST}"
else
    cpu_count="$(nproc --all)"
    background_cpus="${BACKGROUND_CPUS:-32}"
    (( background_cpus >= 1 && background_cpus <= cpu_count )) || {
        echo "BACKGROUND_CPUS must be in 1..${cpu_count}" >&2
        exit 2
    }
    cpu_list="$(( cpu_count - background_cpus ))-$(( cpu_count - 1 ))"
fi

exec taskset --cpu-list "${cpu_list}" "$@"
