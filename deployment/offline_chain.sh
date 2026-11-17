#!/usr/bin/env bash
# The follow-up study's offline arm (O), unattended on the node (supervisord program offline_chain; DESIGN.md,
# "The offline arm"; results/followup_node_operations.md, "The offline arm's driver"). Installed as a copy, with
# deployment/chain_helpers.sh beside it, in /workspace/step1_chain_tools/; never run from the checkout: bash reads a
# running script lazily, and a deploy rewrites the checkout.
#
#   data     download, prepare, walk (Lean CPUs), the walk's record checked, build, the held-out states' flattened
#            reference steps (Lean CPUs), the no-reasoning held-out loop config
#   matched  (O2) the servers stopped; its dry run; both learning rates trained on the 4 GPUs; v0's held-out run without
#            reasoning (shared) and each rate's; the rate chosen on the flattened held-out success; one probe run;
#            its reports; then HOLD with the servers stopped
#   pool     (O1) only once $state/run_pool exists (the owner's word): at the rate O2 chose, one training, its held-out
#            run, one probe run, its reports; then HOLD
#
# Steps done are marked under $state (done_<step>); a rerun (container restart, supervisord's retry) continues at the
# first step not done. A training whose job died is trained again into a fresh output, the interrupted one moved aside.
# A step's 4th attempt, a rejected probe run (exit 3), servers that kept dying (exit 4), GPUs held by another process,
# the detached data steps still alive, or a failed check write $state/STOPPED and exit 0; other failures exit 1 for
# supervisord to retry. HOLD and STOPPED make a start exit 0 at once.
set -uo pipefail
state="${OFFLINE_CHAIN_STATE:-/workspace/runs/offline_chain}"
repository="${OFFLINE_CHAIN_REPOSITORY:-/workspace/LLM-Search-Lean-Proofs}"
start_seconds="${OFFLINE_CHAIN_START_SECONDS:-60}"
poll_seconds="${OFFLINE_CHAIN_POLL_SECONDS:-60}"
mkdir -p "${state}/training" "${state}/held_out"
exec >> "${state}/chain.log" 2>&1
# Without the helpers, a STOPPED of its own: an exit 1 would make supervisord restart the driver at once, forever.
source "$(dirname "${BASH_SOURCE[0]}")/chain_helpers.sh" \
    || { echo "$(date -u +%FT%TZ) no chain_helpers.sh beside the driver: install it" | tee "${state}/STOPPED"; exit 0; }

say "driver start (pid $$)"
for marker in STOPPED HOLD; do
    if [[ -f "${state}/${marker}" ]]; then say "${marker} present ($(cat "${state}/${marker}")): nothing to do"; exit 0; fi
done
# The CPU steps run detached before the driver (offline_data_steps.sh, its pid in data_steps.pid) must be gone: a
# second walk beside theirs would share the Lean CPUs and append to the same walks.jsonl.
data_steps_pid="$(cat "${state}/data_steps.pid" 2>/dev/null)"
if [[ -n "${data_steps_pid}" ]] && tr '\0' ' ' < "/proc/${data_steps_pid}/cmdline" 2>/dev/null | grep -q offline_data_steps.sh; then
    stop_chain "the detached data steps (pid ${data_steps_pid}) still run: install the driver only once they are gone, then move STOPPED aside"
fi
# Boot-time ordering: let the container's services and the GPUs settle.
sleep "${start_seconds}"

cd "${repository}" || stop_chain "no checkout at ${repository}"
source deployment/environment.sh || stop_chain "environment.sh failed"
export HF_HUB_OFFLINE=1
python="${repository}/.venv/bin/python"
config=experiments/configs/grpo/followup/offline/offline_arm.toml
# The config's name and learning_rates, and its initial_policy_adapter under the checkpoints (a test pins them).
arm=offline_arm
rates=(5e-5 1e-4)
v0_adapter="${LEAN_SEARCH_CHECKPOINTS}/data_rewrite_sft_numbered/adapter"
v0_held_out=offline_v0_no_reasoning
gate_run=step1_run8_v35_value_v0
held_out_loop_config="${state}/held_out_loop.toml"
flat_references="${state}/flat_references.jsonl"
gpus=4
# A GPU reads 1 MiB used after stop_model.sh; a CUDA context alone holds a few hundred.
gpu_free_mib=100

[[ -z "${BACKGROUND_CPUS:-}" && -n "${BACKGROUND_CPU_LIST:-}" && -n "${TRAINING_CPU_LIST:-}" ]] \
    || stop_chain "the CPU layout must come from the node environment: BACKGROUND_CPU_LIST and TRAINING_CPU_LIST set, BACKGROUND_CPUS not"

# A step that only runs a command: its log is $state/<step>.log; a failure is retried.
step() {
    local name="$1"
    shift
    done_step "${name}" && return 0
    attempt "${name}"
    mark_start "${name}"
    "$@" >> "${state}/${name}.log" 2>&1 \
        || { say "step ${name} failed (${name}.log); the driver exits for supervisord to retry"; exit 1; }
    finish "${name}"
}

# The data. The download needs the hub (public, no token); everything after it runs offline.
step download env -u HF_HUB_OFFLINE HF_HUB_DISABLE_XET=1 "${python}" experiments/offline_arm.py --config "${config}" download
step prepare deployment/background.sh "${python}" experiments/offline_arm.py --config "${config}" prepare --processes 32
# Resumable: a restart walks only the proofs walks.jsonl lacks.
step walk deployment/background.sh "${python}" experiments/offline_arm.py --config "${config}" walk
# Once more with this checkout: it records walk.json for walks the detached data steps made (or checks it), and walks
# again the walks that raised.
step walk_record deployment/background.sh "${python}" experiments/offline_arm.py --config "${config}" walk
step build "${python}" experiments/offline_arm.py --config "${config}" build
step flat_references deployment/background.sh "${python}" experiments/offline_arm.py --config "${config}" \
    flat-references --output "${flat_references}"
step held_out_config "${python}" experiments/offline_arm.py --config "${config}" held-out-config --output "${held_out_loop_config}"

output_of() { echo "${LEAN_SEARCH_CHECKPOINTS}/${arm}_$1_$2"; }

stop_servers() {
    deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
        || stop_chain "stop_model.sh refused to stop a server (servers.log): look before stopping it by PID"
}

dry_run() {
    local subset="$1" rate="$2" status=0
    done_step "dry_run_${subset}" && return 0
    "${python}" experiments/offline_arm.py --config "${config}" train --subset "${subset}" --learning-rate "${rate}" \
        --dry-run > "${state}/dry_run_${subset}.log" 2>&1 || status=$?
    case "${status}" in
        0) ;;
        3) stop_chain "the dry run of ${subset}: the ranks' data would not fit the host's memory ($(tail -1 "${state}/dry_run_${subset}.log"))" ;;
        *) stop_chain "the dry run of ${subset} failed: $(tail -1 "${state}/dry_run_${subset}.log")" ;;
    esac
    say "dry run of ${subset}: $(tail -1 "${state}/dry_run_${subset}.log")"
    touch "${state}/done_dry_run_${subset}"
}

train_rate() {
    local subset="$1" rate="$2" status=0 trainer logged=0 log_start line
    local label="${subset}_${rate}" output
    output="$(output_of "${subset}" "${rate}")"
    done_step "train_${label}" && return 0
    # The trainer writes training_summary.json last (whole or not at all): its output is finished even if the trainer
    # then exited non-zero at its teardown or lost its driver before the step was marked.
    if [[ -f "${state}/attempts_train_${label}" ]] && complete "${output}/adapter" "${output}/training_summary.json"; then
        say "training ${label}: the earlier attempt left a finished output; kept (exit status $(cat "${state}/training/${label}.exit" 2>/dev/null || echo unknown))"
        finish "train_${label}"
        return 0
    fi
    attempt "train_${label}"
    mark_start "train_${label}"
    gpus_free
    [[ -e "${output}" ]] && aside "${output}"
    rm -f "${state}/training/${label}.exit"
    # The log is appended across attempts: only this attempt's part is searched for its throughput line.
    log_start=$(( $(stat -c %s "${state}/training/${label}.log" 2>/dev/null || echo 0) + 1 ))
    env CUDA_VISIBLE_DEVICES=0,1,2,3 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        taskset --cpu-list "${TRAINING_CPU_LIST}" "${python}" -m torch.distributed.run --standalone "--nproc-per-node=${gpus}" \
        experiments/offline_arm.py --config "${config}" train --subset "${subset}" --learning-rate "${rate}" \
        >> "${state}/training/${label}.log" 2>&1 &
    trainer=$!
    # The first steps' throughput and peak memory, into chain.log as soon as the trainer prints them.
    while kill -0 "${trainer}" 2>/dev/null; do
        if (( ! logged )); then
            line="$(tail -c "+${log_start}" "${state}/training/${label}.log" 2>/dev/null | grep -m1 '^throughput: ')"
            [[ -n "${line}" ]] && { say "training ${label}, ${line}"; logged=1; }
        fi
        sleep "${poll_seconds}"
    done
    wait "${trainer}" || status=$?
    echo "${status}" > "${state}/training/${label}.exit"
    (( status == 0 )) || { say "training ${label} exited ${status} (training/${label}.log); the driver exits for supervisord to retry"; exit 1; }
    complete "${output}/adapter" "${output}/training_summary.json" \
        || stop_chain "training ${label} exited 0 without its adapter and training_summary.json (${output})"
    finish "train_${label}"
}

probe_run() {
    local subset="$1" status=0
    done_step "probe_${subset}" && return 0
    attempt "probe_${subset}"
    mark_start "probe_${subset}"
    PROBE_CONCURRENCY=112 deployment/probe_runs.sh --foreground "${state}/runs_${subset}.toml" \
        >> "${state}/probe_${subset}.log" 2>&1 || status=$?
    case "${status}" in
        0) finish "probe_${subset}" ;;
        3) stop_chain "the probe run of ${subset} was rejected for wall-clock stops (exit 3; probe_${subset}.log): see the operations note, \"A rejected probe run\"" ;;
        4) stop_chain "the probe run of ${subset}: the servers kept dying (exit 4; probe_${subset}.log, the servers' logs)" ;;
        *) say "the probe run of ${subset} exited ${status}; the driver exits for supervisord to retry (it resumes)"; exit 1 ;;
    esac
}

# The probe run at the subset's rate, then the reports; standard error goes beside them.
evaluate_subset() {
    local subset="$1" rate="$2"
    if ! done_step "probe_list_${subset}"; then
        "${python}" experiments/offline_arm.py --config "${config}" probe-list --subset "${subset}" --rate "${rate}" \
            --output "${state}/runs_${subset}.toml" > "${state}/probe_list_${subset}.log" 2>&1 \
            || stop_chain "probe-list failed for ${subset}: $(tail -1 "${state}/probe_list_${subset}.log")"
        touch "${state}/done_probe_list_${subset}"
    fi
    probe_run "${subset}"
    if ! done_step "report_${subset}"; then
        "${python}" experiments/probe_compare.py pair --x "${arm}_${subset}" --x-label "O ${subset}" --y "${gate_run}" \
            --y-label "run 8" --descriptive-across-settings > "${state}/${subset}_against_run8.txt" 2> "${state}/${subset}_against_run8.log" \
            || stop_chain "probe_compare.py failed for ${subset}: $(tail -1 "${state}/${subset}_against_run8.log")"
        "${python}" experiments/offline_arm.py --config "${config}" report --subset "${subset}" \
            > "${state}/report_${subset}.md" 2> "${state}/report_${subset}.log" \
            || stop_chain "the report of ${subset} failed: $(tail -1 "${state}/report_${subset}.log")"
        say "${subset}: $(grep -m1 'the owner.s gate' "${state}/report_${subset}.md")"
        touch "${state}/done_report_${subset}"
    fi
}

hold() {
    stop_servers
    echo "$(date -u +%FT%TZ) $*; the servers are stopped" > "${state}/HOLD"
    say "HOLD: $*; the servers are stopped"
    exit 0
}

# O2, the matched subset: both rates, the choice, its probe run.
if ! done_step train_matched_${rates[0]} || ! done_step train_matched_${rates[1]}; then
    stop_servers
    dry_run matched "${rates[0]}"
    for rate in "${rates[@]}"; do
        train_rate matched "${rate}"
    done
fi
held_out "${v0_held_out}" v0 0 "${v0_adapter}"
for rate in "${rates[@]}"; do
    held_out "${arm}_matched_${rate}" offline_matched 1 "$(output_of matched "${rate}")/adapter"
done
if ! done_step rank_matched; then
    "${python}" experiments/offline_arm.py --config "${config}" rank --subset matched --v0 "${v0_held_out}" \
        --flat-references "${flat_references}" > "${state}/rank_matched.txt" 2> "${state}/rank_matched.log" \
        || stop_chain "the ranking of matched failed: $(tail -1 "${state}/rank_matched.log")"
    say "matched: $(grep -m1 '^Chosen:' "${state}/rank_matched.txt")"
    touch "${state}/done_rank_matched"
fi
chosen_rate="$("${python}" experiments/offline_arm.py --config "${config}" chosen-rate --subset matched \
    --rank "${state}/rank_matched.txt" 2>> "${state}/rank_matched.log")" || stop_chain "chosen-rate failed: $(tail -1 "${state}/rank_matched.log")"
evaluate_subset matched "${chosen_rate}"

# O1, the pool subset: only on the owner's word, at O2's rate.
[[ -f "${state}/run_pool" ]] \
    || hold "the matched subset (O2) is done: ${state}/report_matched.md; the pool subset (O1) waits for the owner's word (${state}/run_pool, then move HOLD aside)"
if ! done_step "train_pool_${chosen_rate}"; then
    stop_servers
    dry_run pool "${chosen_rate}"
    train_rate pool "${chosen_rate}"
fi
held_out "${arm}_pool_${chosen_rate}" offline_pool 1 "$(output_of pool "${chosen_rate}")/adapter"
evaluate_subset pool "${chosen_rate}"
hold "the offline arm is done: ${state}/report_matched.md and report_pool.md hold the gate reports"
