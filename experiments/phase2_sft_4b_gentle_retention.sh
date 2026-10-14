#!/usr/bin/env bash
# MATH retention of the gentle 4B SFT (visible mode) and the visible-reasoning student (visible and thinking modes),
# independent of agent sessions. Waits for the gentle training to end, for "all done" (or a failure) in the
# reasoning agent's series chain log (or for that chain to die), and for both GPUs to stay under 1 GiB for 3 minutes;
# gives up waiting after TIMEOUT_SECONDS (default 14 h) and runs whatever is possible.
#   setsid nohup retention_final.sh > retention_final.log 2>&1 &   (pid in retention_final.pid)
# Test the gating with DRY_RUN=1 CHAIN_FILE=... CHAIN_PID_FILE=... TRAINING_PID=... FREE_SECONDS=... (no GPU use).
# Node copy: /workspace/sft_scratch/retention_final.sh, launched detached on 2026-10-14 at 23:06 UTC.
cd /workspace/LLM-Search-Lean-Proofs
source deployment/environment.sh
run_dir="${LEAN_SEARCH_RUNS}/phase2_sft_4b_gentle"
chain_file="${CHAIN_FILE:-${LEAN_SEARCH_RUNS}/phase5_visible_series_chain.txt}"
chain_pid_file="${CHAIN_PID_FILE:-${LEAN_SEARCH_RUNS}/phase5_visible_series_chain.pid}"
training_pid="${TRAINING_PID:-17456}"
timeout_seconds="${TIMEOUT_SECONDS:-50400}"
free_seconds="${FREE_SECONDS:-180}"
started=$(date +%s)
log() { echo "$(date -u +%H:%M:%S) $*"; }
timed_out() { (( $(date +%s) - started >= timeout_seconds )); }
[[ -n "${DRY_RUN:-}" ]] || echo $$ > "${run_dir}/retention_final.pid"

while ps -p "${training_pid}" > /dev/null 2>&1 && ! timed_out; do sleep 30; done
log "gentle training finished (adapter: $(ls /workspace/checkpoints/phase2_sft_4b_gentle/adapter 2>/dev/null | tr '\n' ' '))"

chain_finished() {
    grep -q -E "all done|failed|stopping" "${chain_file}" 2>/dev/null && return 0
    # A chain that died (e.g. a container restart) never writes its last line.
    [[ -f "${chain_pid_file}" ]] && ! ps -p "$(cat "${chain_pid_file}")" > /dev/null 2>&1
}
until chain_finished || timed_out; do sleep 60; done
log "series chain: $(tail -1 "${chain_file}" 2>/dev/null)"

gpus_free() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1 >= 1024 {busy=1} END {exit busy}'; }
free_since=""
until [[ -n "${free_since}" && $(( $(date +%s) - free_since )) -ge ${free_seconds} ]] || timed_out; do
    if gpus_free; then free_since="${free_since:-$(date +%s)}"; else free_since=""; fi
    sleep 15
done
timed_out && log "safety timeout reached; running the checks anyway"
log "checks start"
if [[ -n "${DRY_RUN:-}" ]]; then log "dry run: would run the checks now"; exit 0; fi

visible=experiments/configs/evaluation/reasoning_retention_nothinking.toml
thinking=experiments/configs/evaluation/reasoning_retention.toml
student=/workspace/checkpoints/phase5_sft_visible_student/adapter
check() { python experiments/reasoning_retention.py --config "$1" "${@:2}"; }
(
    check "${visible}" run --gpu 0 --port 8130 --labels qwen3.5-4b-sft-gentle > "${run_dir}/retention_gentle_visible_run.log" 2>&1
    check "${visible}" force --gpu 0 --port 8133 --labels qwen3.5-4b-sft-gentle > "${run_dir}/retention_gentle_visible_force.log" 2>&1
    if [[ -f "${student}/adapter_config.json" ]]; then
        check "${thinking}" run --gpu 0 --port 8130 --labels qwen3.5-4b-visible-student > "${run_dir}/retention_student_thinking_run.log" 2>&1
        check "${thinking}" force --gpu 0 --port 8133 --labels qwen3.5-4b-visible-student > "${run_dir}/retention_student_thinking_force.log" 2>&1
    fi
) &
(
    if [[ -f "${student}/adapter_config.json" ]]; then
        check "${visible}" run --gpu 1 --port 8131 --labels qwen3.5-4b-visible-student > "${run_dir}/retention_student_visible_run.log" 2>&1
        check "${visible}" force --gpu 1 --port 8134 --labels qwen3.5-4b-visible-student > "${run_dir}/retention_student_visible_force.log" 2>&1
    else
        log "no visible student at ${student}: skipped"
    fi
) &
wait
check "${visible}" summarize > "${run_dir}/retention_visible_summary.log" 2>&1
check "${thinking}" summarize > "${run_dir}/retention_thinking_summary.log" 2>&1
log "checks done; summaries in ${LEAN_SEARCH_RUNS}/reasoning_retention/summary{,_nothinking}"
rm -f "${run_dir}/retention_final.pid"
