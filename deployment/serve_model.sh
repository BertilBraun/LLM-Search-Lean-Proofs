#!/usr/bin/env bash
# Start a detached vLLM OpenAI-compatible server for one model on one GPU and wait until it is healthy.
#
#   deployment/serve_model.sh <name> <model> <gpu> <port> [extra vllm serve arguments ...]
#   deployment/on_node.sh 'deployment/serve_model.sh qwen3.5-2b Qwen/Qwen3.5-2B 0 8000'
#
# The model is served under <name>. Prefix caching and LoRA are on; adapters are loaded at runtime through
# POST /v1/load_lora_adapter and then requested by their adapter name. Sampling defaults are vLLM's, not the
# model's generation_config.json, so every request states its own parameters. Later arguments override earlier
# ones, e.g. --no-enable-lora for a merged model.
# Log: $LEAN_SEARCH_RUNS/servers/<name>.log, process group id: <name>.pid. Stop with stop_model.sh <name>.
# Overrides: MAX_MODEL_LEN (8192), GPU_MEMORY_UTILIZATION (0.90), MAX_NUM_SEQS and MAX_NUM_BATCHED_TOKENS (vLLM
# defaults), MAX_LORA_RANK (64), MAX_LORAS (4), SLEEP_MODE=1 (--enable-sleep-mode, for /sleep and /wake_up),
# SERVER_START_TIMEOUT seconds (900). Dev-mode endpoints (/pause, /collective_rpc, /reset_prefix_cache, ...) are on
# for in-place weight swaps (experiments/publish_weights.py); the server only listens on 127.0.0.1.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"

[[ $# -ge 4 ]] || { echo "Usage: serve_model.sh <name> <model> <gpu> <port> [vllm arguments ...]" >&2; exit 2; }
name="$1"
model="$2"
gpu="$3"
port="$4"
shift 4

server_directory="${LEAN_SEARCH_RUNS}/servers"
log_file="${server_directory}/${name}.log"
pid_file="${server_directory}/${name}.pid"
mkdir -p "${server_directory}"

if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
    echo "Server ${name} is already running (pid $(cat "${pid_file}"))." >&2
    exit 1
fi

arguments=(
    serve "${model}"
    --served-model-name "${name}"
    --host 127.0.0.1
    --port "${port}"
    --max-model-len "${MAX_MODEL_LEN:-8192}"
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.90}"
    --enable-prefix-caching
    # Hybrid models checkpoint recurrent state per 544-token block; a finer unit lets n samples share the prompt tail.
    --prefix-match-unit 16
    --enable-lora
    --max-lora-rank "${MAX_LORA_RANK:-64}"
    --max-loras "${MAX_LORAS:-4}"
    --generation-config vllm
    --enable-prompt-tokens-details
    --disable-uvicorn-access-log
)
if [[ -n "${MAX_NUM_SEQS:-}" ]]; then
    arguments+=(--max-num-seqs "${MAX_NUM_SEQS}")
fi
if [[ -n "${MAX_NUM_BATCHED_TOKENS:-}" ]]; then
    arguments+=(--max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS}")
fi
if [[ "${SLEEP_MODE:-0}" == 1 ]]; then
    arguments+=(--enable-sleep-mode)
fi
# Qwen3.5 checkpoints are vision-language models; the vision tower would otherwise reserve memory.
has_vision_tower="$(python -c 'import sys, transformers
print(hasattr(transformers.AutoConfig.from_pretrained(sys.argv[1]), "vision_config"))' "${model}")"
if [[ "${has_vision_tower}" == True ]]; then
    arguments+=(--language-model-only)
fi

# Persisting Triton autotuning results removes about a minute of warmup from later starts.
CUDA_VISIBLE_DEVICES="${gpu}" VLLM_ALLOW_RUNTIME_LORA_UPDATING=True VLLM_SERVER_DEV_MODE=1 TRITON_CACHE_AUTOTUNING=1 \
    setsid nohup vllm "${arguments[@]}" "$@" > "${log_file}" 2>&1 < /dev/null &
echo $! > "${pid_file}"
echo "Starting ${name} (${model}) on GPU ${gpu}, port ${port}, pid $(cat "${pid_file}"), log ${log_file}"

deadline=$(( SECONDS + ${SERVER_START_TIMEOUT:-900} ))
until curl -sf "http://127.0.0.1:${port}/health" > /dev/null; do
    if ! kill -0 "$(cat "${pid_file}")" 2>/dev/null || (( SECONDS > deadline )); then
        echo "Server ${name} failed to start; last log lines:" >&2
        tail -n 40 "${log_file}" >&2
        "${script_directory}/stop_model.sh" "${name}" || true
        exit 1
    fi
    sleep 2
done
echo "Server ${name} is healthy after ${SECONDS} s at http://127.0.0.1:${port}/v1"
