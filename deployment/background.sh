#!/usr/bin/env bash
# Run a CPU-heavy background job (tracing, pre-filters, Lean stages of probes) so that it cannot starve GPU feeders.
#
#   deployment/background.sh <command> [argument ...]
#   BACKGROUND_CPUS=24 deployment/background.sh python experiments/phase2_trace_proofs.py --processes 24 ...
#
# The container sees all 192 host CPUs but is throttled to a 46-core quota (cpu.max) as a whole. Busy processes
# each get a CPU of their own, so nice changes nothing until the quota runs out, and then the whole cgroup, GPU
# feeders included, is throttled for the rest of the period. The job is therefore pinned to the last
# BACKGROUND_CPUS logical CPUs (default 32), which caps all background jobs together at that many cores and leaves
# the rest of the quota to the foreground, and niced to 19 so that a foreground thread scheduled onto one of those
# CPUs still wins it. Give Lean jobs at most BACKGROUND_CPUS processes: more would share CPUs and hit wall-clock
# timeouts that an unpinned run would not.

set -euo pipefail

[[ $# -ge 1 ]] || { echo "Usage: background.sh <command> [argument ...]" >&2; exit 2; }

cpu_count="$(nproc --all)"
background_cpus="${BACKGROUND_CPUS:-32}"
(( background_cpus >= 1 && background_cpus <= cpu_count )) || { echo "BACKGROUND_CPUS must be in 1..${cpu_count}" >&2; exit 2; }

exec taskset --cpu-list "$(( cpu_count - background_cpus ))-$(( cpu_count - 1 ))" nice -n 19 "$@"
