#!/usr/bin/env bash
# The follow-up study's offline arm (O), unattended on the node (supervisord program offline_chain; DESIGN.md,
# "Follow-up study: controlled arms", "The offline arm"; results/followup_node_operations.md, "The offline arm's
# driver"). Installed as a copy, with deployment/chain_helpers.sh beside it, in /workspace/step1_chain_tools/; never run
# from the checkout: bash reads a running script lazily, and a deploy rewrites the checkout.
#
#   data     download the two public proof corpora, prepare (exclusions, the pool's proofs recovered), walk every proof
#            in Lean (the Lean CPUs), build the examples of both subsets; the no-reasoning held-out loop config
#   matched  (O2, small, first) its dry run; the servers stopped, both learning rates trained on the 4 GPUs; v0's
#            held-out run without reasoning (once, shared), each rate's; the ranking; one probe run of the chosen
#            rate (2,000 statements, no reasoning, value v0, 16 expansions); its reports against run 8, run 4 and the
#            anchors
#   pool     (O1) the same
#   HOLD     the servers stopped
#
# Steps done are marked under $state (done_<step>); a rerun (container restart, supervisord's retry) continues at the
# first step not done. A training run whose job died is trained again into a fresh output, the interrupted one moved
# aside. A step's 4th attempt, a rejected probe run (exit 3), servers that kept dying (exit 4), GPUs held by another
# process or a failed check write $state/STOPPED and exit 0; other failures exit 1 for supervisord to retry. HOLD and
# STOPPED make a start exit 0 at once.
set -uo pipefail
state="${OFFLINE_CHAIN_STATE:-/workspace/runs/offline_chain}"
repository="${OFFLINE_CHAIN_REPOSITORY:-/workspace/LLM-Search-Lean-Proofs}"
start_seconds="${OFFLINE_CHAIN_START_SECONDS:-60}"
poll_seconds="${OFFLINE_CHAIN_POLL_SECONDS:-60}"
mkdir -p "${state}/training" "${state}/held_out"
exec >> "${state}/chain.log" 2>&1
source "$(dirname "${BASH_SOURCE[0]}")/chain_helpers.sh" || { echo "$(date -u +%FT%TZ) no chain_helpers.sh beside the driver"; exit 1; }

say "driver start (pid $$)"
for marker in STOPPED HOLD; do
    if [[ -f "${state}/${marker}" ]]; then say "${marker} present ($(cat "${state}/${marker}")): nothing to do"; exit 0; fi
done
# Boot-time ordering: let the container's services and the GPUs settle.
sleep "${start_seconds}"

cd "${repository}" || stop_chain "no checkout at ${repository}"
source deployment/environment.sh || stop_chain "environment.sh failed"
export HF_HUB_OFFLINE=1
python="${repository}/.venv/bin/python"
config=experiments/configs/grpo/followup/offline/offline_arm.toml
# The config's name and learning_rates (offline_arm.py train refuses another rate).
arm=offline_arm
rates=(5e-5 1e-4)
v0_adapter="${LEAN_SEARCH_CHECKPOINTS}/data_rewrite_sft_numbered/adapter"
v0_held_out=offline_v0_no_reasoning
gate_run=step1_run8_v35_value_v0
held_out_loop_config="${state}/held_out_loop.toml"
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
step build "${python}" experiments/offline_arm.py --config "${config}" build
step held_out_config "${python}" experiments/offline_arm.py --config "${config}" held-out-config --output "${held_out_loop_config}"

output_of() { echo "${LEAN_SEARCH_CHECKPOINTS}/${arm}_$1_$2"; }

train_rate() {
    local subset="$1" rate="$2" status=0
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
    env CUDA_VISIBLE_DEVICES=0,1,2,3 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        taskset --cpu-list "${TRAINING_CPU_LIST}" "${python}" -m torch.distributed.run --standalone "--nproc-per-node=${gpus}" \
        experiments/offline_arm.py --config "${config}" train --subset "${subset}" --learning-rate "${rate}" \
        >> "${state}/training/${label}.log" 2>&1 || status=$?
    echo "${status}" > "${state}/training/${label}.exit"
    (( status == 0 )) || { say "training ${label} exited ${status} (training/${label}.log); the driver exits for supervisord to retry"; exit 1; }
    complete "${output}/adapter" "${output}/training_summary.json" \
        || stop_chain "training ${label} exited 0 without its adapter and training_summary.json (${output})"
    finish "train_${label}"
}

all_trained() {
    local rate
    for rate in "${rates[@]}"; do
        done_step "train_$1_${rate}" || return 1
    done
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
        3) stop_chain "the probe run of ${subset} was rejected for wall-clock stops (exit 3; probe_${subset}.log): repeat it at a doubled cap under a new name" ;;
        4) stop_chain "the probe run of ${subset}: the servers kept dying (exit 4; probe_${subset}.log, the servers' logs)" ;;
        *) say "the probe run of ${subset} exited ${status}; the driver exits for supervisord to retry (it resumes)"; exit 1 ;;
    esac
}

run_subset() {
    local subset="$1" rate variants=()
    if ! done_step "dry_run_${subset}"; then
        "${python}" experiments/offline_arm.py --config "${config}" train --subset "${subset}" --learning-rate "${rates[0]}" \
            --dry-run > "${state}/dry_run_${subset}.log" 2>&1 || stop_chain "the dry run of ${subset} failed: $(tail -1 "${state}/dry_run_${subset}.log")"
        say "dry run of ${subset}: $(tail -1 "${state}/dry_run_${subset}.log")"
        touch "${state}/done_dry_run_${subset}"
    fi
    if ! all_trained "${subset}"; then
        deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
            || stop_chain "stop_model.sh refused to stop a server (servers.log): look before stopping it by PID"
        for rate in "${rates[@]}"; do
            train_rate "${subset}" "${rate}"
        done
    fi
    held_out "${v0_held_out}" v0 0 "${v0_adapter}"
    for rate in "${rates[@]}"; do
        held_out "${arm}_${subset}_${rate}" "offline_${subset}" 1 "$(output_of "${subset}" "${rate}")/adapter"
        variants+=(--variant "${subset}_${rate}" "${rate}" "${arm}_${subset}_${rate}")
    done
    if ! done_step "rank_${subset}"; then
        "${python}" experiments/rank_learning_rates.py --v0 "${v0_held_out}" "${variants[@]}" > "${state}/rank_${subset}.txt" 2>&1 \
            || stop_chain "rank_learning_rates.py failed for ${subset}: $(tail -1 "${state}/rank_${subset}.txt")"
        "${python}" experiments/offline_arm.py --config "${config}" probe-list --subset "${subset}" \
            --rank "${state}/rank_${subset}.txt" --output "${state}/runs_${subset}.toml" >> "${state}/rank_${subset}.log" 2>&1 \
            || stop_chain "probe-list failed for ${subset}: $(tail -1 "${state}/rank_${subset}.log")"
        say "${subset}: $(grep -m1 '^Chosen:' "${state}/rank_${subset}.txt")"
        touch "${state}/done_rank_${subset}"
    fi
    probe_run "${subset}"
    if ! done_step "report_${subset}"; then
        "${python}" experiments/probe_compare.py pair --x "${arm}_${subset}" --x-label "O ${subset}" --y "${gate_run}" \
            --y-label "run 8" --descriptive-across-settings > "${state}/${subset}_against_run8.txt" 2>&1 \
            || stop_chain "probe_compare.py failed for ${subset}: $(tail -1 "${state}/${subset}_against_run8.txt")"
        "${python}" experiments/offline_arm.py --config "${config}" report --subset "${subset}" > "${state}/report_${subset}.md" 2>&1 \
            || stop_chain "the report of ${subset} failed: $(tail -1 "${state}/report_${subset}.md")"
        say "${subset}: $(grep -m1 'the owner.s gate' "${state}/report_${subset}.md")"
        touch "${state}/done_report_${subset}"
    fi
}

# The matched subset first: small and fast, so its result arrives first.
run_subset matched
run_subset pool

deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
    || stop_chain "stop_model.sh refused to stop a server after the reports (servers.log): look before stopping it by PID"
echo "$(date -u +%FT%TZ) offline arm done: ${state}/report_matched.md and report_pool.md hold the gate reports; the servers are stopped" > "${state}/HOLD"
say "HOLD: offline arm done; the reports are ${state}/report_matched.md and report_pool.md; the servers are stopped"
