#!/usr/bin/env bash
# Visible-reasoning student v2, after the gentle SFT v2: data, training, evaluation on the 512 validation states,
# the equal-expansion search and MATH-500 retention (thinking on and off). Run detached on the node:
#   setsid nohup bash experiments/phase5_visible_v2_chain.sh > $LEAN_SEARCH_RUNS/phase5_visible_v2_chain.txt 2>&1 < /dev/null &
# It waits for the visible control search (if running), for $LEAN_SEARCH_RUNS/phase2_sft_4b_gentle_v2/DONE and for
# both GPUs to stay free for three minutes; it writes $LEAN_SEARCH_RUNS/phase5_visible_v2/DONE at the end.
cd "$(dirname "$0")/.."
source deployment/environment.sh
configs=experiments/configs/reasoning
runs="${LEAN_SEARCH_RUNS}"
checkpoints="${LEAN_SEARCH_CHECKPOINTS}"
student=phase5_sft_visible_student_v2
merged="${checkpoints}/${student}/merged"
marker="${runs}/phase5_visible_v2/DONE"
log() { echo "$(date -u +%H:%M:%S) $*"; }
data() { CUDA_VISIBLE_DEVICES= deployment/background.sh python experiments/phase5_reasoning_data.py "$@"; }
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
    for port in "$@"; do curl -sf "http://127.0.0.1:${port}/health" > /dev/null || return 1; done
}
wait_healthy() {
    local attempt
    for attempt in $(seq 1 180); do healthy "$@" && return 0; sleep 5; done
    return 1
}
stop() { local name; for name in "$@"; do deployment/stop_model.sh "${name}" || true; done; }
mkdir -p "${runs}/phase5_visible_v2"

if [[ -f "${runs}/phase5_visible_control.pid" ]]; then
    log "waiting for the visible control search"
    while ps -p "$(cat "${runs}/phase5_visible_control.pid")" > /dev/null 2>&1; do sleep 60; done
fi
log "waiting for the gentle SFT v2"
until [[ -f "${runs}/phase2_sft_4b_gentle_v2/DONE" && -f "${checkpoints}/phase2_sft_4b_gentle_v2/adapter/adapter_config.json" ]]; do
    sleep 60
done
log "gentle SFT v2 done"

data select --config ${configs}/phase5_data_visible_student_v2.toml --name visible_student_v2 \
    > "${runs}/phase5_visible_v2/select.txt" 2>&1
log "data selection exit $?"

until gpus_stay_free; do sleep 60; done
mkdir -p "${runs}/${student}"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True torchrun --nproc-per-node 2 experiments/phase5_reasoning_sft.py \
    --config ${configs}/${student}.toml --run-name ${student} > "${runs}/${student}/log.txt" 2>&1
log "training exit $?"
CUDA_VISIBLE_DEVICES= python experiments/publish_weights.py merge --base-model Qwen/Qwen3.5-4B \
    --adapter "${checkpoints}/${student}/adapter" --output "${merged}" > "${runs}/${student}/merge.txt" 2>&1
log "merge exit $?"
if [[ ! -f "${merged}/config.json" ]]; then log "no merged student: stopping"; exit 1; fi

arms=(phase5_eval_visible_student_v2_visible phase5_eval_visible_student_v2_nothinking)
for arm in "${arms[@]}"; do
    if [[ ! -f "${runs}/${arm}/states.jsonl" ]]; then
        data states --config ${configs}/${arm}.toml --run-name ${arm} --states-from phase5_eval_bootstrap_sft_v2_thinking
    fi
done
until gpus_stay_free; do sleep 60; done
(deployment/serve_model.sh visible-student-gpu0 "${merged}" 0 8100 --served-model-name visible-student \
    --no-enable-lora > "${runs}/phase5_visible_v2/serve_eval0.txt" 2>&1 &)
deployment/serve_model.sh visible-student-gpu1 "${merged}" 1 8101 --served-model-name visible-student \
    --no-enable-lora > "${runs}/phase5_visible_v2/serve_eval1.txt" 2>&1
if ! wait_healthy 8100 8101; then log "evaluation servers failed"; stop visible-student-gpu0 visible-student-gpu1; exit 1; fi
for arm in "${arms[@]}"; do
    data run --config ${configs}/${arm}.toml --run-name ${arm} --pool-size 16 > "${runs}/${arm}/log.txt" 2>&1
    log "${arm} exit $?"
done
stop visible-student-gpu0 visible-student-gpu1

until gpus_stay_free; do sleep 60; done
for gpu in 0 1; do
    GPU_MEMORY_UTILIZATION=0.62 deployment/serve_model.sh policy-gpu${gpu} "${merged}" ${gpu} 810${gpu} \
        --served-model-name policy-merged --no-enable-lora > "${runs}/phase5_visible_v2/serve_policy${gpu}.txt" 2>&1
    GPU_MEMORY_UTILIZATION=0.30 deployment/serve_model.sh value-gpu${gpu} "${checkpoints}/phase3_value_v0/merged" \
        ${gpu} 820${gpu} --served-model-name value-merged --no-enable-lora > "${runs}/phase5_visible_v2/serve_value${gpu}.txt" 2>&1
done
if ! wait_healthy 8100 8101 8200 8201; then
    log "search servers failed"
    stop policy-gpu0 value-gpu0 policy-gpu1 value-gpu1
    exit 1
fi
search=phase5_expansions_visible_student_v2
mkdir -p "${runs}/${search}"
python experiments/node_monitor.py record --output "${runs}/${search}/monitor.jsonl" \
    --server-url http://127.0.0.1:8100 --results "${runs}/${search}/results.jsonl" > /dev/null 2>&1 &
monitor=$!
BACKGROUND_CPUS=40 deployment/background.sh python experiments/run_search.py \
    --config "${configs}/${search}.toml" --split valid --run-name "${search}" > "${runs}/${search}/log.txt" 2>&1
log "${search} exit $?"
kill ${monitor}
stop policy-gpu0 value-gpu0 policy-gpu1 value-gpu1

until gpus_stay_free; do sleep 60; done
retention() {
    local config="$1" label="$2" gpu="$3" port="$4"
    for command in run force; do
        python experiments/reasoning_retention.py --config "${config}" ${command} --gpu ${gpu} --port ${port} \
            --labels ${label} >> "${runs}/phase5_visible_v2/retention_$(basename "${config}" .toml).txt" 2>&1
        log "retention ${config} ${command} exit $?"
    done
}
# Distinct labels: each run serves its model under a name made from the label.
retention ${configs}/phase5_retention_visible_student_v2.toml qwen3.5-4b-visible-student-v2 0 8130 &
retention ${configs}/phase5_retention_visible_student_v2_nothinking.toml qwen3.5-4b-visible-student-v2-visible 1 8131 &
wait
python - "${runs}/reasoning_retention" > "${runs}/phase5_visible_v2/retention_accuracy.txt" <<'EOF'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for directory, label in (
    ("models", "qwen3.5-4b-visible-student-v2"),
    ("models_nothinking", "qwen3.5-4b-visible-student-v2-visible"),
):
    base = root / directory / label
    scores = [json.loads(line) for line in (base / "scores.jsonl").open(encoding="utf-8")]
    forced_path = base / "forced.jsonl"
    forced = [json.loads(line) for line in forced_path.open(encoding="utf-8")] if forced_path.exists() else []
    forced_correct = {(entry["unique_id"], entry["sample_index"]) for entry in forced if entry["correct"]}
    correct = sum(
        entry["correct"] or (entry["truncated"] and (entry["unique_id"], entry["sample_index"]) in forced_correct)
        for entry in scores
    )
    tokens = sorted(entry["total_tokens"] for entry in scores)
    print(
        f"{directory}: {len(scores)} samples, pass@1 {sum(entry['correct'] for entry in scores) / len(scores):.3f}, "
        f"forced pass@1 {correct / len(scores):.3f}, truncated {sum(entry['truncated'] for entry in scores) / len(scores):.3f}, "
        f"median tokens {tokens[len(tokens) // 2]}"
    )
EOF
log "retention accuracy exit $?"
touch "${marker}"
log "all done"
