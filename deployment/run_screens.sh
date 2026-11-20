#!/usr/bin/env bash
# The two GRPO screens one after the other (results/followup_progress.md, "hold D, screen two GRPO fixes"), started
# detached at the arms driver's HOLD from an installed copy (bash reads a script as it runs, so a deploy must not change
# the running one):
#
#   mkdir -p /workspace/runs/screens && cp deployment/run_screens.sh /workspace/runs/screens/run_screens.sh
#   (cd /workspace/LLM-Search-Lean-Proofs && setsid nohup bash /workspace/runs/screens/run_screens.sh \
#       > /workspace/runs/screens/run.log 2>&1 < /dev/null &)
#
# Each screen (experiments/configs/grpo/followup/screens/) is skipped once it has finished.json or health_stop.json;
# a loop still running is waited on; otherwise every server is stopped (arm_loop.sh keeps any that answers), the GPUs
# are waited on until free and the screen starts through arm_loop.sh as a smoke-kind overlay (which resumes it), at most
# 3 times while its loop exits without either file. Then grpo_loop.sh stop takes its servers down. A failure writes
# STOPPED in /workspace/runs/screens/ and exits; a restart of this script goes on where it stopped.

set -euo pipefail

repository=/workspace/LLM-Search-Lean-Proofs
cd "${repository}"
source deployment/environment.sh

state="${LEAN_SEARCH_RUNS}/screens"
mode="${LEAN_SEARCH_RUNS}/study_chain/mode.toml"
screens=(A_2e-5 B2_2e-5)
gpus=4
# A GPU reads 1 MiB used after stop_model.sh; a CUDA context alone holds a few hundred (as deployment/arms_chain.sh).
gpu_free_mib=100
gpu_wait_seconds=3600
mkdir -p "${state}"

say() {
    echo "$(date -u +%FT%TZ) $*"
}

stop_screens() {
    say "STOPPED: $1"
    echo "$(date -u +%FT%TZ) $1" > "${state}/STOPPED"
    exit 1
}

# Exactly one numeric reading per GPU, every one under the limit; anything else (an nvidia-smi error) is not free.
gpus_free() {
    local readings
    readings="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || true)"
    awk -v limit="${gpu_free_mib}" -v expected="${gpus}" '
        $0 !~ /^[0-9]+$/ { bad = 1 } $0 + 0 >= limit { bad = 1 } END { exit (bad || NR != expected) }' \
        <<< "${readings}"
}

wait_gpus() {
    local waited=0
    until gpus_free; do
        (( waited >= gpu_wait_seconds )) && return 1
        sleep 10
        waited=$(( waited + 10 ))
    done
}

# The pid alive and still a loop (a crashed loop's pid may be reused).
loop_alive() {
    local pid_file="$1/loop.pid" pid
    [[ -f "${pid_file}" ]] || return 1
    pid="$(cat "${pid_file}")"
    kill -0 "${pid}" 2>/dev/null && tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null | grep -q grpo_loop
}

ended() {
    [[ -f "$1/finished.json" || -f "$1/health_stop.json" ]]
}

[[ -e "${state}/STOPPED" ]] && { echo "${state}/STOPPED exists: move it aside first" >&2; exit 1; }

for stem in "${screens[@]}"; do
    name="followup_screen_${stem}"
    run="${LEAN_SEARCH_RUNS}/${name}"
    if ended "${run}" && ! loop_alive "${run}"; then
        say "${name}: ended before, skipped"
        continue
    fi
    attempt=0
    until ended "${run}" && ! loop_alive "${run}"; do
        if ! loop_alive "${run}"; then
            attempt=$(( attempt + 1 ))
            (( attempt <= 3 )) || stop_screens "${name}: the loop kept dying (${run}/loop.out)"
            deployment/stop_model.sh --all >> "${state}/${name}.start.log" 2>&1 \
                || stop_screens "${name}: stop_model.sh refused to stop a server (${name}.start.log)"
            wait_gpus || stop_screens "${name}: GPUs still in use after ${gpu_wait_seconds} s"
            say "${name}: start, attempt ${attempt}"
            deployment/arm_loop.sh --kind smoke --mode "${mode}" "experiments/configs/grpo/followup/screens/${stem}.toml" \
                >> "${state}/${name}.start.log" 2>&1 || stop_screens "${name}: arm_loop.sh failed (${name}.start.log)"
        fi
        while loop_alive "${run}"; do
            sleep 60
        done
        ended "${run}" || say "${name}: the loop exited without finished.json or health_stop.json"
    done
    LOOP_CONFIG="${LEAN_SEARCH_RUNS}/followup_configs/${name}/loop.toml" deployment/grpo_loop.sh stop \
        >> "${state}/${name}.start.log" 2>&1 || stop_screens "${name}: grpo_loop.sh stop failed"
    if [[ -f "${run}/health_stop.json" ]]; then
        say "${name}: stopped on its health rule ($(head -c 300 "${run}/health_stop.json")); the next screen goes on"
    else
        say "${name}: finished"
    fi
done
deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 || true
say "every screen done"
