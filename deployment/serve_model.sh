#!/usr/bin/env bash
# Start a detached vLLM OpenAI-compatible server for one model on one GPU and wait until it is healthy.
#
#   deployment/serve_model.sh <name> <model> <gpu> <port> [extra vllm serve arguments ...]
#   deployment/on_node.sh 'deployment/serve_model.sh qwen3.5-2b Qwen/Qwen3.5-2B 0 8000'
#
# The model is served under <name>. Prefix caching and LoRA are on; adapters are loaded at runtime through
# POST /v1/load_lora_adapter and then requested by their adapter name. Sampling defaults are vLLM's, not the
# model's generation_config.json, so every request states its own parameters. Later arguments override earlier
# ones, e.g. --no-enable-lora for a merged model; GRPO policy servers add --logprobs-mode processed_logprobs so the
# recorded log-probabilities are those of the tempered distribution the trainer compares against (deployment/README.md).
# Log: $LEAN_SEARCH_RUNS/servers/<name>.log (a start moves the previous server's to <name>.<UTC time>.log, so a crash's
# log survives the restart; old logs are not pruned), process group id: <name>.pid, written before the wait for
# /health and trusted only for a vLLM started with it (server_pid.sh). A start removes <name>.swapped (the tooling's
# mark of an in-place sleep or swap) and refuses a port that already answers. Stop with stop_model.sh <name>.
# Overrides: MAX_MODEL_LEN (8192), GPU_MEMORY_UTILIZATION (0.90), MAX_NUM_SEQS and MAX_NUM_BATCHED_TOKENS (vLLM
# defaults), MAX_LORA_RANK (64), MAX_LORAS (4), SLEEP_MODE=1 (--enable-sleep-mode, for /sleep and /wake_up),
# SERVER_START_TIMEOUT seconds (900), CORE_DUMPS=1 (core files up to the container's hard limit, written where
# /proc/sys/kernel/core_pattern says, relative to $LEAN_SEARCH_RUNS/servers/cores; the log's first lines show the
# pattern and the free space there). Dev-mode endpoints (/pause, /collective_rpc,
# /reset_prefix_cache, ...) are on for in-place weight swaps (experiments/publish_weights.py); the server only listens
# on 127.0.0.1.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"
source "${script_directory}/server_pid.sh"

[[ $# -ge 4 ]] || { echo "Usage: serve_model.sh <name> <model> <gpu> <port> [vllm arguments ...]" >&2; exit 2; }
name="$1"
model="$2"
gpu="$3"
port="$4"
shift 4
# A local weights directory by its absolute path: vLLM may run in another working directory (CORE_DUMPS).
if [[ -e "${model}" ]]; then
    model="$(realpath "${model}")"
fi

server_directory="${LEAN_SEARCH_RUNS}/servers"
log_file="${server_directory}/${name}.log"
pid_file="${server_directory}/${name}.pid"
mkdir -p "${server_directory}"

if running="$(trusted_server_pid "${pid_file}" "${name}")"; then
    echo "Server ${name} is already running (pid ${running})." >&2
    exit 1
fi
if curl -sf "http://127.0.0.1:${port}/health" > /dev/null; then
    echo "Port ${port} already answers, but not as ${name} of ${pid_file}: stop that server first." >&2
    exit 1
fi

if [[ -f "${log_file}" ]]; then
    mv "${log_file}" "${server_directory}/${name}.$(date -u +%Y%m%dT%H%M%S.%NZ).log"
fi
# This server holds the weights it starts from (policy/server_processes.py: the swap skip trusts no older marker).
rm -f "${server_directory}/${name}.swapped"
working_directory="$(pwd)"
if [[ "${CORE_DUMPS:-0}" == 1 ]]; then
    # As far as the container's hard limit allows; a relative core_pattern writes into the working directory.
    ulimit -S -c "$(ulimit -H -c)" || true
    working_directory="${server_directory}/cores"
    mkdir -p "${working_directory}"
    {
        echo "Core dumps up to $(ulimit -c) blocks; core_pattern: $(cat /proc/sys/kernel/core_pattern)"
        df -h "${working_directory}"
    } > "${log_file}"
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
cd "${working_directory}"
CUDA_VISIBLE_DEVICES="${gpu}" VLLM_ALLOW_RUNTIME_LORA_UPDATING=True VLLM_SERVER_DEV_MODE=1 TRITON_CACHE_AUTOTUNING=1 \
    setsid nohup vllm "${arguments[@]}" "$@" >> "${log_file}" 2>&1 < /dev/null &
# Written before the wait below, so that an interrupted start leaves a server stop_model.sh can find.
echo $! > "${pid_file}"
cd - > /dev/null
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
