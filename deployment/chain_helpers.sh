# Helpers of the node's chain drivers (deployment/study_chain.sh, offline_chain.sh, arms_chain.sh), sourced by a driver from
# its own directory: installed as a copy beside it, never read from the checkout while a driver runs. A driver sets
# before using them: state (its state directory, chain.log's), python, poll_seconds, gpus and gpu_free_mib (gpus_free),
# held_out_loop_config (held_out); its working directory is the checkout. other_chain_idle takes the other driver's
# state directory; no_other_loop reads LEAN_SEARCH_RUNS (deployment/environment.sh).

say() { echo "$(date -u +%FT%TZ) $*"; }
stop_chain() { say "STOPPED: $*"; echo "$(date -u +%FT%TZ) $*" > "${state}/STOPPED"; exit 0; }

attempt() {
    local step="$1" count
    count=$(( $(cat "${state}/attempts_${step}" 2>/dev/null || echo 0) + 1 ))
    echo "${count}" > "${state}/attempts_${step}"
    (( count <= 3 )) || stop_chain "step ${step} failed 3 times"
    say "step ${step}, attempt ${count}"
}
done_step() { [[ -f "${state}/done_$1" ]]; }
# A step's wall clock runs from its first attempt to its end, interruptions included (timings.tsv, for the report).
mark_start() { [[ -f "${state}/started_$1" ]] || date +%s > "${state}/started_$1"; }
finish() {
    printf '%s\t%s\t%s\n' "$1" "$(cat "${state}/started_$1")" "$(date +%s)" >> "${state}/timings.tsv"
    touch "${state}/done_$1"
    say "step $1 done"
}

# The node's chain drivers (study_chain, offline_chain, arms_chain) share the GPUs and the servers: before its first
# server or GPU action a driver stops while another has started (its chain.log exists; an empty or prepared state directory
# does not count) and stands neither at HOLD nor STOPPED.
other_chain_idle() {
    local other="$1" name="$2"
    [[ -f "${other}/chain.log" ]] || return 0
    [[ -f "${other}/HOLD" || -f "${other}/STOPPED" ]] && return 0
    stop_chain "the ${name} chain (${other}) has started and stands neither at HOLD nor STOPPED: the two chains share the GPUs and servers; move STOPPED aside and start this one once the other holds"
}

# A start of the run is in flight or its loop lives: deployment/arm_loop.sh holds <run>.lock from its start, and the
# detached loop holds it for its whole life.
run_lock_held() { [[ -e "$1.lock" ]] && ! flock -n "$1.lock" true; }

# Before a driver's first server or GPU action, whatever the other chains' markers say (the arms' loops outlive their
# driver, so a STOPPED arms chain may have a loop running): no loop of a run but the given own runs lives, and no start
# of one is in flight.
no_other_loop() {
    local own=" $* " pid_file lock run pid
    for pid_file in "${LEAN_SEARCH_RUNS}"/*/loop.pid; do
        run="$(dirname "${pid_file}")"
        [[ "${own}" == *" ${run} "* ]] && continue
        pid="$(cat "${pid_file}" 2>/dev/null)"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            stop_chain "the loop of ${run} runs (pid ${pid}): this chain shares the GPUs and servers with it; stop it or wait for its end, then move STOPPED aside"
        fi
    done
    for lock in "${LEAN_SEARCH_RUNS}"/*.lock; do
        run="${lock%.lock}"
        [[ "${own}" == *" ${run} "* ]] && continue
        run_lock_held "${run}" && stop_chain "a start of ${run} is in flight or its loop runs (${lock} is held); wait for its end, then move STOPPED aside"
    done
    return 0
}

aside() {
    local path="$1" moved
    moved="${path}.interrupted_$(date -u +%Y%m%dT%H%M%SZ)"
    mv "${path}" "${moved}" || stop_chain "could not move ${path} aside"
    say "moved the interrupted ${path} aside to ${moved}"
}

# A held-out run on the servers (started if not answering; the run puts the adapter on the policy servers itself).
held_out() {
    local name="$1" arm="$2" phase="$3" adapter="$4" status=0
    done_step "held_out_${name}" && return 0
    attempt "held_out_${name}"
    mark_start "held_out_${name}"
    LOOP_CONFIG="${held_out_loop_config}" deployment/grpo_loop.sh servers >> "${state}/servers.log" 2>&1 \
        || { say "starting the servers failed (servers.log); the driver exits for supervisord to retry"; exit 1; }
    deployment/background.sh "${python}" experiments/held_out_evaluate.py --name "${name}" --arm "${arm}" \
        --phase "${phase}" --policy-adapter "${adapter}" --loop-config "${held_out_loop_config}" \
        >> "${state}/held_out/${name}.log" 2>&1 || status=$?
    case "${status}" in
        0)
            # Exit 0 also after server failures left states without a tree (summary.json's dropped): resumed next start.
            "${python}" experiments/learning_rate_step.py check-held-out --name "${name}" >> "${state}/held_out/${name}.log" 2>&1 \
                || { say "held-out run ${name} left states without a tree; the driver exits for supervisord to resume it"; exit 1; }
            finish "held_out_${name}"
            ;;
        4) stop_chain "held-out run ${name}: the servers kept dying (exit 4; held_out/${name}.log, the servers' logs)" ;;
        *) say "held-out run ${name} exited ${status}; the driver exits for supervisord to retry"; exit 1 ;;
    esac
}

# The GPUs must be free before a round trains (a dead round's torchrun workers live in sessions of their own). Judged
# by the memory used, which a container sees; its process list may be empty or name host PIDs, so it is only shown.
gpus_free() {
    local readings busy check
    for check in 1 2 3 4 5; do
        readings="$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits)" \
            || stop_chain "nvidia-smi --query-gpu failed: ${readings}"
        (( $(grep -c . <<< "${readings}") == gpus )) || stop_chain "nvidia-smi reads not ${gpus} GPUs: ${readings//$'\n'/; }"
        busy="$(awk -F', *' -v limit="${gpu_free_mib}" '$2 + 0 >= limit { printf "GPU %s %s MiB; ", $1, $2 }' <<< "${readings}")"
        [[ -z "${busy}" ]] && return 0
        say "GPUs in use (check ${check} of 5): ${busy}processes: $(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader | paste -sd';' -)"
        sleep "${poll_seconds}"
    done
    stop_chain "the GPUs stay in use (${busy}): look (nvidia-smi), stop what holds them by PID, move STOPPED aside"
}

complete() {
    local file
    for file in "$@"; do
        [[ -e "${file}" ]] || return 1
    done
}
