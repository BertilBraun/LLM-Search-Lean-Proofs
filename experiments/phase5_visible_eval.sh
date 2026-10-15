#!/usr/bin/env bash
# Evaluates the visible-reasoning student (merged) on the bootstrap evaluation's 512 validation states, visible and
# non-thinking. Run detached on the node; it waits for another job's pid file (if given) to exit and for both GPUs to
# stay free for three minutes:
#   setsid nohup bash experiments/phase5_visible_eval.sh [<pid file to wait for>] > $LEAN_SEARCH_RUNS/phase5_visible_eval.txt 2>&1 < /dev/null &
cd "$(dirname "$0")/.."
source deployment/environment.sh
configs=experiments/configs/reasoning
runs="${LEAN_SEARCH_RUNS}"
merged="${LEAN_SEARCH_CHECKPOINTS}/phase5_sft_visible_student/merged"
wait_for="${1:-}"
log() { echo "$(date -u +%H:%M:%S) $*"; }
data() { CUDA_VISIBLE_DEVICES= deployment/background.sh python experiments/phase5_reasoning_data.py "$@"; }
gpus_free() {
    local used
    for used in $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits); do
        (( used < 1024 )) || return 1
    done
}
gpus_stay_free() {
    local check
    for check in 1 2 3 4 5 6; do gpus_free || return 1; sleep 30; done
}
wait_healthy() {
    local attempt
    for attempt in $(seq 1 180); do
        curl -sf http://127.0.0.1:8100/health > /dev/null && curl -sf http://127.0.0.1:8101/health > /dev/null && return 0
        sleep 5
    done
    return 1
}
stop() { deployment/stop_model.sh visible-student-gpu0 || true; deployment/stop_model.sh visible-student-gpu1 || true; }

arms=(phase5_eval_visible_student_visible phase5_eval_visible_student_nothinking)
for arm in "${arms[@]}"; do
    # A run directory exists only once its states are chosen; the evaluations reuse the bootstrap evaluation's.
    if [[ ! -f "${runs}/${arm}/states.jsonl" ]]; then
        data states --config ${configs}/${arm}.toml --run-name ${arm} --states-from phase5_eval_bootstrap_sft_v2_thinking
    fi
done
if [[ -n "${wait_for}" ]]; then
    log "waiting for pid $(cat "${wait_for}") (${wait_for}) to exit"
    while ps -p "$(cat "${wait_for}")" > /dev/null 2>&1; do sleep 60; done
fi
log "waiting for both GPUs to stay free for three minutes"
until gpus_stay_free; do sleep 60; done
(deployment/serve_model.sh visible-student-gpu0 "${merged}" 0 8100 --served-model-name visible-student \
    --no-enable-lora > "${runs}/phase5_visible_eval_serve0.txt" 2>&1 &)
deployment/serve_model.sh visible-student-gpu1 "${merged}" 1 8101 --served-model-name visible-student \
    --no-enable-lora > "${runs}/phase5_visible_eval_serve1.txt" 2>&1
if ! wait_healthy; then log "servers failed to start"; stop; exit 1; fi
log "servers up"
for arm in "${arms[@]}"; do
    data run --config ${configs}/${arm}.toml --run-name ${arm} --pool-size 16 > "${runs}/${arm}/log.txt" 2>&1
    log "${arm} exit $?"
done
stop
log "servers stopped"
log "all done"
