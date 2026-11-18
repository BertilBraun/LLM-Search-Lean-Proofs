#!/usr/bin/env bash
# The follow-up study's step 2, arm A's learning rate, unattended on the node (supervisord program study_chain;
# DESIGN.md, "Follow-up study: controlled arms", "Step 2", with the owner's decisions of 2026-11-17: arm B dropped, C
# takes the offline run O2's rate and a 4-phase window, D takes C's rate and window and A's rate;
# results/followup_node_operations.md, "The study driver"). Installed as a copy, /workspace/step1_chain_tools/
# study_chain.sh with deployment/chain_helpers.sh beside it, never run from the checkout: bash reads a running script
# lazily, and a deploy rewrites the checkout.
#
#   S1  the servers step 1 left up stopped; the shared sampling run from v0 and value v0 (one phase: 12M generated
#       tokens, no training) in the sampling mode $state/mode.toml, then (once the loop process is gone) its trees
#       linked into one directory (slice_trees.py --slices 1)
#   S3a v0's held-out run, while the servers still hold v0
#   S2  the servers stopped; A's three per-tactic GRPO rounds from v0 on the phase's trees (2e-5, 5e-5, 1e-4), one at a
#       time on the 4 GPUs
#   S3b the servers started; each variant's held-out run, then v0's again (the A/A and drift check)
#   S4  rank_learning_rates.py for A, the report learning_rates_report.md, the servers stopped (an arm's launcher keeps
#       any server that answers, whatever it holds), then HOLD
#
# The plan (rounds, configs, held-out runs) comes from experiments/learning_rate_step.py. Steps done are marked under
# $state (done_<step>); a rerun (container restart, supervisord's retry) continues at the first step not done. A round
# whose job died is trained again into a fresh output, the interrupted one moved aside; only a round whose trainer left
# its completion files (phase.json reading back) is marked done and evaluated. A step's 4th attempt, a health stop, a
# refused or changed mode, the offline chain started and neither at HOLD nor STOPPED, servers that kept dying
# (held_out_evaluate.py exit 4), GPUs held by another process or a failed check write $state/STOPPED and exit 0; other failures exit 1 for supervisord to retry. HOLD and STOPPED make a
# start exit 0 at once.
set -uo pipefail
state="${STUDY_CHAIN_STATE:-/workspace/runs/study_chain}"
repository="${STUDY_CHAIN_REPOSITORY:-/workspace/LLM-Search-Lean-Proofs}"
start_seconds="${STUDY_CHAIN_START_SECONDS:-60}"
poll_seconds="${STUDY_CHAIN_POLL_SECONDS:-60}"
# How long the shared loop may take to exit after finished.json before giving up.
loop_exit_seconds="${STUDY_CHAIN_LOOP_EXIT_SECONDS:-600}"
mkdir -p "${state}/rounds" "${state}/held_out"
exec >> "${state}/chain.log" 2>&1
# Without the helpers, a STOPPED of its own: an exit 1 would make supervisord restart the driver at once, forever.
source "$(dirname "${BASH_SOURCE[0]}")/chain_helpers.sh" \
    || { echo "$(date -u +%FT%TZ) no chain_helpers.sh beside the driver: install it" | tee "${state}/STOPPED"; exit 0; }
# An older copy of the helpers lacks what this driver calls (bash would only print "command not found" and go on).
declare -F other_chain_idle no_other_loop > /dev/null || stop_chain "chain_helpers.sh is older than the driver: install the current one"
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
followup=experiments/configs/grpo/followup
shared=followup_shared_sampling
shared_run="${LEAN_SEARCH_RUNS}/${shared}"
shared_loop_config="${LEAN_SEARCH_RUNS}/followup_configs/${shared}/loop.toml"
held_out_loop_config="${shared_loop_config}"
configs="${state}/configs"
mode="${state}/mode.toml"
gpus=4
# A GPU reads 1 MiB used after stop_model.sh; a CUDA context alone holds a few hundred.
gpu_free_mib=100

[[ -z "${BACKGROUND_CPUS:-}" && -n "${BACKGROUND_CPU_LIST:-}" && -n "${TRAINING_CPU_LIST:-}" ]] \
    || stop_chain "the CPU layout must come from the node environment: BACKGROUND_CPU_LIST and TRAINING_CPU_LIST set, BACKGROUND_CPUS not"

# The sampling mode the arms will use (with or without visible reasoning, the expansions per search): the owner's
# decision, put in place by hand; the step never starts without it and never changes it once begun.
[[ -f "${mode}" ]] || stop_chain "no sampling mode: copy the chosen mode (e.g. ${followup}/modes/visible.toml) to ${mode}, move STOPPED aside and start study_chain"
# Standard output only: a library warning on stderr must not make two starts' mode.txt differ.
"${python}" experiments/learning_rate_step.py check-mode --mode "${mode}" > "${state}/mode.txt" 2> "${state}/mode.err" \
    || stop_chain "the sampling mode ${mode} is refused: $(tail -1 "${state}/mode.err")"
# mode.txt names the search config's sha256: an edit or a deploy changing that file is caught as well.
if [[ -f "${state}/mode.recorded" ]]; then
    cmp -s "${mode}" "${state}/mode.recorded" && cmp -s "${state}/mode.txt" "${state}/mode.recorded.txt" \
        || stop_chain "${mode} or its search config differs from the mode the step began with (mode.recorded, mode.recorded.txt): the shared trees were sampled in that one"
else
    cp "${state}/mode.txt" "${state}/mode.recorded.txt"
    cp "${mode}" "${state}/mode.recorded"
fi
say "sampling mode: $(paste -sd' ' "${state}/mode.txt")"

if ! done_step configs; then
    "${python}" experiments/learning_rate_step.py write-configs --output "${configs}" --shared-run "${shared}" \
        > "${state}/configs.log" 2>&1 || stop_chain "write-configs failed: $(tail -1 "${state}/configs.log")"
    touch "${state}/done_configs"
fi

# From here on servers and GPUs: never beside a running offline chain.
other_chain_idle "${OFFLINE_CHAIN_STATE:-/workspace/runs/offline_chain}" offline
other_chain_idle "${ARMS_CHAIN_STATE:-/workspace/runs/arms_chain}" arms
# The arms' loops outlive their driver: a STOPPED arms chain may still have one running.
no_other_loop "${shared_run}"

loop_alive() { [[ -f "${shared_run}/loop.pid" ]] && kill -0 "$(cat "${shared_run}/loop.pid")" 2>/dev/null; }

# S1. The shared sampling run, (re)started through arm_loop.sh whenever it is found neither running nor finished.
# Before its first start the servers step 1 left up are stopped: grpo_loop.sh servers keeps any server that answers,
# whatever weights it holds, and the run must sample with its own version 0.
if ! done_step s1_sampling; then
    if [[ ! -f "${state}/started_s1_sampling" ]]; then
        deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
            || stop_chain "stop_model.sh refused to stop a server (servers.log): look before stopping it by PID"
    fi
    mark_start s1_sampling
    while [[ ! -f "${shared_run}/finished.json" ]]; do
        if [[ -f "${shared_run}/health_stop.json" ]]; then
            stop_chain "the shared sampling run stopped on its health check ($(head -c 300 "${shared_run}/health_stop.json"))"
        fi
        if ! loop_alive; then
            attempt s1_sampling_start
            deployment/arm_loop.sh --kind "shared sampling" --mode "${mode}" "${followup}/shared_sampling.toml" \
                || say "arm_loop.sh failed; the next check starts it again"
        fi
        sleep "${poll_seconds}"
    done
    say "shared sampling finished: $(cat "${shared_run}/finished.json")"
    # The loop writes finished.json before it shuts down; slice_trees.py refuses while its process lives.
    waited=0
    while loop_alive; do
        if (( waited >= loop_exit_seconds )); then
            # Counted, so a loop that never exits (or a pid reused by another process) ends in STOPPED.
            attempt s1_loop_exit
            say "the shared loop still runs ${loop_exit_seconds} s after finished.json; the driver exits for supervisord to retry"
            exit 1
        fi
        sleep 1
        waited=$(( waited + 1 ))
    done
    finish s1_sampling
fi

if ! done_step s1_slices; then
    mark_start s1_slices
    [[ -e "${shared_run}/slices" ]] && aside "${shared_run}/slices"
    "${python}" experiments/slice_trees.py --trees "${shared_run}/trees" --slices 1 --output "${shared_run}/slices" \
        > "${state}/slices.log" 2>&1 || stop_chain "slice_trees.py failed: $(tail -1 "${state}/slices.log")"
    cat "${state}/slices.log"
    finish s1_slices
fi

# S3a. v0's baseline under this step's code, mode and layout (the first line of held_out.tsv).
IFS=$'\t' read -r v0_name v0_arm v0_phase v0_adapter < "${configs}/held_out.tsv"
held_out "${v0_name}" "${v0_arm}" "${v0_phase}" "${v0_adapter}"

all_rounds_done() {
    local label rest
    while IFS=$'\t' read -r label rest; do
        done_step "round_${label}" || return 1
    done < "${configs}/rounds.tsv"
}

train_round() {
    local label="$1" config="$2" run_name="$3" output="$4" trees="$5" lean_replay="$6" math_replay="$7"
    local completion="$8" status=0
    done_step "round_${label}" && return 0
    # A trainer that wrote its completion files last (and phase.json parses: not cut by a kill mid-write), then exited
    # non-zero at its teardown or lost its driver before the round was marked.
    # shellcheck disable=SC2086
    if [[ -f "${state}/attempts_round_${label}" ]] && complete ${completion} \
        && "${python}" experiments/learning_rate_step.py check-round --label "${label}" >> "${state}/rounds/${label}.log" 2>&1; then
        say "round ${label}: the earlier attempt left a finished output; kept (that attempt's trainer exit status:" \
            "$(cat "${state}/rounds/${label}.exit" 2>/dev/null || echo "unknown, the driver died first"); rounds/${label}.log)"
        finish "round_${label}"
        return 0
    fi
    attempt "round_${label}"
    mark_start "round_${label}"
    gpus_free
    [[ -e "${output}" ]] && aside "${output}"
    rm -f "${state}/rounds/${label}.exit"
    env CUDA_VISIBLE_DEVICES=0,1,2,3 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        taskset --cpu-list "${TRAINING_CPU_LIST}" "${python}" -m torch.distributed.run --standalone \
        "--nproc-per-node=${gpus}" experiments/grpo_phase.py --config "${config}" --trees "${trees}" \
        --run-name "${run_name}" --part policy --lean-replay "${lean_replay}" --math-replay "${math_replay}" \
        >> "${state}/rounds/${label}.log" 2>&1 || status=$?
    echo "${status}" > "${state}/rounds/${label}.exit"
    (( status == 0 )) || { say "round ${label} exited ${status} (rounds/${label}.log); the driver exits for supervisord to retry"; exit 1; }
    # shellcheck disable=SC2086
    complete ${completion} || stop_chain "round ${label} exited 0 without its completion files (${completion})"
    finish "round_${label}"
}

# S2. A's three rounds, the servers stopped (only through stop_model.sh).
if ! all_rounds_done; then
    deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
        || stop_chain "stop_model.sh refused to stop a server (servers.log): look before stopping it by PID"
    gpus_free
    while IFS=$'\t' read -r -u 3 label config run_name output trees lean_replay math_replay completion; do
        train_round "${label}" "${config}" "${run_name}" "${output}" "${trees}" "${lean_replay}" "${math_replay}" \
            "${completion}"
    done 3< "${configs}/rounds.tsv"
fi

# S3b. Every variant's held-out run, then v0's again (the lines after v0's first).
while IFS=$'\t' read -r -u 3 name arm phase adapter; do
    held_out "${name}" "${arm}" "${phase}" "${adapter}"
done 3< <(tail -n +2 "${configs}/held_out.tsv")

# S4. A's ranking, then the report (C's and D's rate named there as O2's, from the offline chain's choice).
if ! done_step s4_report; then
    arguments_text="$("${python}" experiments/learning_rate_step.py rank-arguments)" || stop_chain "rank-arguments failed"
    mapfile -t arguments <<< "${arguments_text}"
    "${python}" experiments/rank_learning_rates.py "${arguments[@]}" > "${state}/rank_A.txt" 2>&1 \
        || stop_chain "rank_learning_rates.py failed: $(tail -1 "${state}/rank_A.txt")"
    say "arm A: $(grep -m1 '^Chosen:' "${state}/rank_A.txt")"
    "${python}" experiments/learning_rate_step.py report --state "${state}" --mode "${mode}" --shared-run "${shared}" \
        --earlier-v0 v0 --o2-ranking "${LEAN_SEARCH_RUNS}/offline_chain/rank_matched.txt" \
        --output "${state}/learning_rates_report.md" > "${state}/report.log" 2>&1 \
        || stop_chain "the report failed: $(tail -1 "${state}/report.log")"
    touch "${state}/done_s4_report"
fi

# The policy servers hold the last held-out run's merge, and arm_loop.sh keeps any server that answers: stopped here.
deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
    || stop_chain "stop_model.sh refused to stop a server after the report (servers.log): look before stopping it by PID"
echo "$(date -u +%FT%TZ) step 2 done: ${state}/learning_rates_report.md holds the arms' values (not applied); the servers are stopped" > "${state}/HOLD"
say "HOLD: step 2 done; the report is ${state}/learning_rates_report.md; the servers are stopped"
