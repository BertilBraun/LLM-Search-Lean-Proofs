#!/usr/bin/env bash
# Gentle 4B SFT v2, end to end and independent of agent sessions:
#   1. self-solutions: base Qwen3.5-4B served on both GPUs solves ~8,000 visible and 1,500 thinking math problems;
#   2. training: Lean steps (`4b`) plus the kept self-solutions (`self_v1`), LoRA, DDP, packed;
#   3. MATH-500 retention of the new adapter in visible (GPU 0) and thinking (GPU 1) mode, forced answers.
# Starts after the reasoning agent's control search (experiments/phase5_visible_control.sh: "all done" or a failure
# in its log, or its pid gone) and once both GPUs have been under 1 GiB for 3 minutes (14 h safety timeout).
# Writes $LEAN_SEARCH_RUNS/phase2_sft_4b_gentle_v2/DONE at the end. Run detached:
#   setsid nohup bash experiments/phase2_sft_4b_gentle_v2_chain.sh > $LEAN_SEARCH_RUNS/phase2_sft_4b_gentle_v2/chain.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.."
source deployment/environment.sh
run=phase2_sft_4b_gentle_v2
run_dir="${LEAN_SEARCH_RUNS}/${run}"
mkdir -p "${run_dir}"
echo $$ > "${run_dir}/chain.pid"
control_log="${LEAN_SEARCH_RUNS}/phase5_visible_control.txt"
control_pid_file="${LEAN_SEARCH_RUNS}/phase5_visible_control.pid"
timeout_seconds="${TIMEOUT_SECONDS:-50400}"
started=$(date +%s)
log() { echo "$(date -u +%H:%M:%S) $*"; }
timed_out() { (( $(date +%s) - started >= timeout_seconds )); }
gpus_free() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1 >= 1024 {busy=1} END {exit busy}'; }
wait_gpus_free() {
    local free_since=""
    until [[ -n "${free_since}" && $(( $(date +%s) - free_since )) -ge 180 ]] || timed_out; do
        if gpus_free; then free_since="${free_since:-$(date +%s)}"; else free_since=""; fi
        sleep 15
    done
}
control_finished() {
    grep -q -E "all done|failed" "${control_log}" 2>/dev/null && return 0
    [[ -f "${control_pid_file}" ]] && ! ps -p "$(cat "${control_pid_file}")" > /dev/null 2>&1
}
finish() { log "$1"; echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $1" > "${run_dir}/DONE"; rm -f "${run_dir}/chain.pid"; exit "${2:-0}"; }

log "waiting for the control search"
until control_finished || timed_out; do sleep 60; done
log "control search: $(tail -1 "${control_log}" 2>/dev/null)"
wait_gpus_free
log "GPUs free"

# 1. Self-solutions.
(MAX_MODEL_LEN=6144 deployment/serve_model.sh self-solutions-gpu0 Qwen/Qwen3.5-4B 0 8140 --served-model-name base-4b \
    --no-enable-lora > "${run_dir}/serve0.txt" 2>&1 &)
MAX_MODEL_LEN=6144 deployment/serve_model.sh self-solutions-gpu1 Qwen/Qwen3.5-4B 1 8141 --served-model-name base-4b \
    --no-enable-lora > "${run_dir}/serve1.txt" 2>&1
for attempt in $(seq 1 180); do
    curl -sf http://127.0.0.1:8140/health > /dev/null && curl -sf http://127.0.0.1:8141/health > /dev/null && break
    sleep 5
done
log "self-solution servers up"
python experiments/phase2_sft_self_solutions.py --name self_v1 --served-name base-4b \
    --server-urls http://127.0.0.1:8140/v1,http://127.0.0.1:8141/v1 > "${run_dir}/self_solutions.log" 2>&1
status=$?
deployment/stop_model.sh self-solutions-gpu0
deployment/stop_model.sh self-solutions-gpu1
log "self-solutions exit ${status}"
[[ ${status} -eq 0 ]] || finish "self-solutions failed" 1

# 2. Training.
wait_gpus_free
log "training"
TRITON_CACHE_AUTOTUNING=1 CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc-per-node 2 experiments/phase2_sft.py \
    --config experiments/configs/training/${run}.toml --run-name "${run}" > "${run_dir}/log.txt" 2>&1
status=$?
log "training exit ${status}"
[[ -f "${LEAN_SEARCH_CHECKPOINTS}/${run}/adapter/adapter_config.json" ]] || finish "training failed" 1

# 3. Retention, visible on GPU 0 and thinking on GPU 1.
wait_gpus_free
visible=experiments/configs/evaluation/reasoning_retention_nothinking.toml
thinking=experiments/configs/evaluation/reasoning_retention.toml
label=qwen3.5-4b-sft-gentle-v2
check() { python experiments/reasoning_retention.py --config "$1" "${@:2}"; }
(check "${visible}" run --gpu 0 --port 8130 --labels ${label} > "${run_dir}/retention_visible_run.log" 2>&1
 check "${visible}" force --gpu 0 --port 8133 --labels ${label} > "${run_dir}/retention_visible_force.log" 2>&1) &
(check "${thinking}" run --gpu 1 --port 8131 --labels ${label} > "${run_dir}/retention_thinking_run.log" 2>&1
 check "${thinking}" force --gpu 1 --port 8134 --labels ${label} > "${run_dir}/retention_thinking_force.log" 2>&1) &
wait
check "${visible}" summarize > "${run_dir}/retention_visible_summary.log" 2>&1
check "${thinking}" summarize > "${run_dir}/retention_thinking_summary.log" 2>&1
finish "all done: summaries in ${LEAN_SEARCH_RUNS}/reasoning_retention/summary{,_nothinking}"
