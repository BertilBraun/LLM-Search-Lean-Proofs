#!/usr/bin/env bash
# The visible student's non-thinking search at equal expansions (the control for its visible arm). Run detached:
#   setsid nohup bash experiments/phase5_visible_control.sh > $LEAN_SEARCH_RUNS/phase5_visible_control.txt 2>&1 < /dev/null &
cd "$(dirname "$0")/.."
source deployment/environment.sh
configs=experiments/configs/reasoning
runs="${LEAN_SEARCH_RUNS}"
merged="${LEAN_SEARCH_CHECKPOINTS}/phase5_sft_visible_student/merged"
arm=phase5_expansions_visible_student_nothinking
log() { echo "$(date -u +%H:%M:%S) $*"; }
gpus_free() {
    local used
    for used in $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); do
        (( used < 1024 )) || return 1
    done
}
retention_running() { pgrep -f "reasoning_retention|retention\.sh" > /dev/null; }
gpus_stay_free() {
    local check
    for check in 1 2 3 4 5 6; do
        gpus_free && ! retention_running || return 1
        sleep 30
    done
}
healthy() {
    local port
    for port in 8100 8101 8200 8201; do curl -sf "http://127.0.0.1:${port}/health" > /dev/null || return 1; done
}
stop() { local name; for name in policy-gpu0 value-gpu0 policy-gpu1 value-gpu1; do deployment/stop_model.sh ${name} || true; done; }

log "waiting for free GPUs (three minutes) and no retention check"
until gpus_stay_free; do sleep 60; done
for gpu in 0 1; do
    GPU_MEMORY_UTILIZATION=0.62 deployment/serve_model.sh policy-gpu${gpu} "${merged}" ${gpu} 810${gpu} \
        --served-model-name policy-merged --no-enable-lora > "${runs}/phase5_visible_control_policy${gpu}.txt" 2>&1
    GPU_MEMORY_UTILIZATION=0.30 deployment/serve_model.sh value-gpu${gpu} "${LEAN_SEARCH_CHECKPOINTS}/phase3_value_v0/merged" \
        ${gpu} 820${gpu} --served-model-name value-merged --no-enable-lora > "${runs}/phase5_visible_control_value${gpu}.txt" 2>&1
done
for attempt in $(seq 1 180); do healthy && break; sleep 5; done
if ! healthy; then log "servers failed to start"; stop; exit 1; fi
log "servers up"
mkdir -p "${runs}/${arm}"
python experiments/node_monitor.py record --output "${runs}/${arm}/monitor.jsonl" \
    --server-url http://127.0.0.1:8100 --results "${runs}/${arm}/results.jsonl" > /dev/null 2>&1 &
monitor=$!
BACKGROUND_CPUS=40 deployment/background.sh python experiments/run_search.py \
    --config "${configs}/${arm}.toml" --split valid --run-name "${arm}" > "${runs}/${arm}/log.txt" 2>&1
log "${arm} exit $?"
kill ${monitor}
stop
log "servers stopped"
log "all done"
