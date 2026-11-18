#!/usr/bin/env bash
# The follow-up study's closed-loop arms, one after another, unattended on the node (supervisord program arms_chain;
# DESIGN.md, "Follow-up study: controlled arms", "Step 3"; results/followup_node_operations.md, "The arms driver").
# Installed as a copy, /workspace/step1_chain_tools/arms_chain.sh with deployment/chain_helpers.sh beside it, never run
# from the checkout: bash reads a running script lazily, and a deploy rewrites the checkout.
#
#   A      arm A's loop (adopted while it runs or a start of it is in flight: never started a second time), then its
#          phase-8 and final policy and value adapters copied to $state/adapters/A for the PC, one probe run of its
#          final checkpoint with its own final value model (longest expected search first), the comparisons against
#          the anchors and run 7, a report
#   smoke  one phase of arm C and one of arm D at 6M generated tokens under their own names (followup_smoke_C, _D),
#          each training GRPO (D), the value model and a round in one pause: GPU memory and /dev/shm sampled every
#          few seconds, D's loop killed by PID while it publishes and started again; experiments/arms_chain.py
#          smoke-check judges them (smoke_report.md); arm C starts only if every gate passed
#   C, D   as A, each also compared with the other arms' probe runs
#   HOLD   the servers stopped
#
# The order is $state/order's words (A, C, D and smoke, each at most once, smoke before C and D unless it is done;
# read at each start), "A smoke C D" without it. When the order reaches an arm held by $state/hold_<arm>, the chain
# writes HOLD "waiting for: <arm>" with the servers stopped; the arm is not started, adopted, resumed or evaluated, and
# the steps after it wait too. Remove the hold file, move HOLD aside and start the chain to go on.
#
# Steps done are marked under $state (done_<step>); a rerun (container restart, supervisord's retry) continues at the
# first step not done, and a loop found neither running nor ended is started again through arm_loop.sh (which resumes
# it), unless $state/pause_<arm> says it was stopped by hand. An arm's health stop (health_stop.json) is never
# restarted: a report, then by $state/on_health_stop either STOPPED with the servers stopped (wait, the default) or
# the next arm (continue); the owner's word (skip or evaluate in $state/word_<arm>) settles the stopped arm, at the end
# at the latest. A step's 4th attempt, a failed smoke test, a rejected probe run (exit 3), servers that kept dying
# (exit 4), another chain started and neither at HOLD nor STOPPED, another run's loop alive, GPUs held by another
# process or a failed check write $state/STOPPED and exit 0; other failures exit 1 for supervisord to retry. HOLD and
# STOPPED make a start exit 0 at once.
set -uo pipefail
state="${ARMS_CHAIN_STATE:-/workspace/runs/arms_chain}"
repository="${ARMS_CHAIN_REPOSITORY:-/workspace/LLM-Search-Lean-Proofs}"
# The sampling mode step 2 recorded (arm A was started with it); every arm is checked against the shared run's.
mode="${ARMS_CHAIN_MODE:-/workspace/runs/study_chain/mode.toml}"
start_seconds="${ARMS_CHAIN_START_SECONDS:-60}"
poll_seconds="${ARMS_CHAIN_POLL_SECONDS:-60}"
smoke_poll_seconds="${ARMS_CHAIN_SMOKE_POLL_SECONDS:-5}"
sample_seconds="${ARMS_CHAIN_SAMPLE_SECONDS:-5}"
# Into D's publishing stage before the kill: with swap = "restart" it lands while the servers restart onto the
# handed-off merges, before the version is recorded (A's phase 1 published for 135-250 s).
kill_delay_seconds="${ARMS_CHAIN_KILL_DELAY_SECONDS:-30}"
loop_exit_seconds="${ARMS_CHAIN_LOOP_EXIT_SECONDS:-600}"
# Before a loop is started again: a dead loop's persistent trainer finishes its command (up to a train timeout) first.
gpu_wait_seconds="${ARMS_CHAIN_GPU_WAIT_SECONDS:-3600}"
lock_wait_seconds="${ARMS_CHAIN_LOCK_WAIT_SECONDS:-1800}"
shared_memory="${ARMS_CHAIN_SHARED_MEMORY:-/dev/shm}"
mkdir -p "${state}/loops" "${state}/probe" "${state}/compare" "${state}/smoke"
exec >> "${state}/chain.log" 2>&1
# Without the helpers, a STOPPED of its own: an exit 1 would make supervisord restart the driver at once, forever.
source "$(dirname "${BASH_SOURCE[0]}")/chain_helpers.sh" \
    || { echo "$(date -u +%FT%TZ) no chain_helpers.sh beside the driver: install it" | tee "${state}/STOPPED"; exit 0; }
# An older copy of the helpers lacks what this driver calls (bash would only print "command not found" and go on).
declare -F other_chain_idle gpus_free run_lock_held no_other_loop > /dev/null \
    || stop_chain "chain_helpers.sh is older than the driver: install the current one"
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
smoke_killed_arm=D
gpus=4
# A GPU reads 1 MiB used after stop_model.sh; a CUDA context alone holds a few hundred.
gpu_free_mib=100

[[ -z "${BACKGROUND_CPUS:-}" && -n "${BACKGROUND_CPU_LIST:-}" && -n "${TRAINING_CPU_LIST:-}" ]] \
    || stop_chain "the CPU layout must come from the node environment: BACKGROUND_CPU_LIST and TRAINING_CPU_LIST set, BACKGROUND_CPUS not"
[[ -f "${mode}" ]] || stop_chain "no sampling mode at ${mode} (step 2's): put the mode arm A was started with there"

# The order of the arms and the smoke test, checked before anything runs.
order=(A smoke C D)
if [[ -f "${state}/order" ]]; then
    read -r -a order <<< "$(tr '\n' ' ' < "${state}/order")"
fi
(( ${#order[@]} )) || stop_chain "the order file ${state}/order is empty: write e.g. 'smoke C A D'"
seen=" "
for step in "${order[@]}"; do
    [[ "${step}" =~ ^(A|C|D|smoke)$ ]] || stop_chain "the order (${order[*]}) names '${step}': only A, C, D and smoke"
    [[ "${seen}" == *" ${step} "* ]] && stop_chain "the order (${order[*]}) names ${step} twice"
    if [[ "${step}" == C || "${step}" == D ]] && [[ "${seen}" != *" smoke "* ]] && ! done_step smoke; then
        stop_chain "the order (${order[*]}) puts ${step} before the smoke test, which arms C and D need first"
    fi
    seen+="${step} "
done
say "order: ${order[*]}$(for step in "${order[@]}"; do [[ -f "${state}/hold_${step}" ]] && printf ' (%s held)' "${step}"; done)"

# The three drivers share the GPUs and the servers, and only this one's runs may have a loop alive.
other_chain_idle "${STUDY_CHAIN_STATE:-/workspace/runs/study_chain}" study
other_chain_idle "${OFFLINE_CHAIN_STATE:-/workspace/runs/offline_chain}" offline
no_other_loop "${LEAN_SEARCH_RUNS}"/followup_{A,C,D,smoke_C,smoke_D}

# The loop's process lives: its loop.pid names a grpo_loop.py process (a reused pid is not adopted).
loop_process_alive() {
    local pid
    pid="$(cat "$1/loop.pid" 2>/dev/null)"
    [[ -n "${pid}" ]] && { tr '\0' ' ' < "/proc/${pid}/cmdline"; } 2>/dev/null | grep -q grpo_loop.py
}

# Its process lives, or a start of it is in flight (arm_loop.sh's run lock, which the loop then holds).
loop_alive() { loop_process_alive "$1" || run_lock_held "$1"; }

stop_servers() {
    deployment/stop_model.sh --all >> "${state}/servers.log" 2>&1 \
        || stop_chain "stop_model.sh refused to stop a server (servers.log): look before stopping it by PID"
}

# The owner's word on a health-stopped arm into `word` ("" when not given yet); STOPPED on an unknown one.
read_word() {
    word=""
    [[ -f "${state}/word_$1" ]] || return 0
    word="$(tr -d '[:space:]' < "${state}/word_$1")"
    [[ "${word}" == skip || "${word}" == evaluate ]] || stop_chain "word_$1 holds '${word}': write skip or evaluate"
}

# The loop's phase and stage ("2 training"), from loop_state.json's first two fields.
loop_position() {
    sed -n 's/^{"phase": *\([0-9]*\), *"stage": *"\([a-z]*\)".*/\1 \2/p' "$1/loop_state.json" 2>/dev/null
}

# Every GPU's memory (nvidia-smi's used: the allocators' reserved memory included) and /dev/shm's use, with the loop's
# phase and stage, while the driver lives.
sample_resources() {
    local run="$1" output="$2" driver="$3" position shm
    while kill -0 "${driver}" 2>/dev/null; do
        position="$(loop_position "${run}")"
        shm="$(df -k --output=used,size "${shared_memory}" 2>/dev/null | tail -n 1 | awk '{ print $1 "\t" $2 }')"
        nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null \
            | awk -F', *' -v time="$(date +%s)" -v position="${position:-0 none}" -v shm="${shm}" \
                '{ split(position, at, " "); print time "\t" at[1] "\t" at[2] "\t" $1 "\t" $2 "\t" $3 "\t" shm }' \
            >> "${output}"
        sleep "${sample_seconds}"
    done
}

# Once: the smoke loop of D killed by PID (SIGKILL, a crash) once it has published for kill_delay_seconds.
kill_while_publishing() {
    local run="$1" record="${state}/smoke/kill_${smoke_killed_arm}.json" now pid
    local config="followup_configs/followup_smoke_${smoke_killed_arm}/loop.toml"
    [[ -f "${record}" ]] && return 0
    if [[ "$(loop_position "${run}")" != "1 publishing" ]]; then
        [[ -n "${publishing_since}" ]] && say "the smoke loop left publishing before the kill: none this time"
        publishing_since=""
        return 0
    fi
    now="$(date +%s)"
    if [[ -z "${publishing_since}" ]]; then
        publishing_since="${now}"
        say "the smoke loop publishes phase 1; the kill follows in ${kill_delay_seconds} s"
    fi
    (( now - publishing_since >= kill_delay_seconds )) || return 0
    pid="$(cat "${run}/loop.pid")"
    { tr '\0' ' ' < "/proc/${pid}/cmdline"; } 2>/dev/null | grep "grpo_loop.py" | grep -q "${config}" \
        || stop_chain "${run}/loop.pid names ${pid}, not the grpo_loop.py process of ${config}: no kill"
    kill -KILL "${pid}" || return 0
    printf '{"killed_at": %s, "pid": %s, "phase": 1, "stage": "publishing", "stage_seconds": %s}\n' \
        "$(date +%s.%N)" "${pid}" "$(( now - publishing_since ))" > "${record}"
    say "killed the smoke loop (pid ${pid}, SIGKILL) $(( now - publishing_since )) s into publishing phase 1"
}

# Up to gpu_wait_seconds for every GPU to read free (a dead loop's trainer ends its command first); gpus_free decides.
wait_gpus() {
    local waited=0
    while nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits 2>/dev/null \
        | awk -F', *' -v limit="${gpu_free_mib}" '$2 + 0 >= limit { busy = 1 } END { exit !busy }'; do
        (( waited == 0 )) && say "GPUs still in use before the loop's start: waiting up to ${gpu_wait_seconds} s"
        (( waited >= gpu_wait_seconds )) && break
        sleep "${poll_seconds}"
        waited=$(( waited + ${poll_seconds%.*} + 1 ))
    done
    gpus_free
}

# The servers stopped (arm_loop.sh keeps any that answers, whatever it holds), the GPUs free, the loop started.
start_loop() {
    local key="$1" kind="$2" overlay="$3"
    stop_servers
    wait_gpus
    echo "$(date -u +%FT%TZ) $(git -C "${repository}" rev-parse HEAD 2>/dev/null || echo unknown)" >> "${state}/loops/${key}.revisions"
    # A session of its own: stopping or restarting the driver never stops the loop, which the next start adopts.
    setsid --wait deployment/arm_loop.sh --kind "${kind}" --mode "${mode}" "${overlay}" >> "${state}/loops/${key}.log" 2>&1 \
        || say "arm_loop.sh failed for ${key} (loops/${key}.log); the next check starts it again"
}

# The loop wrote finished.json or health_stop.json before it exits; the next step needs its process gone.
wait_loop_exit() {
    local key="$1" run="$2" waited=0
    while loop_alive "${run}"; do
        if (( waited >= loop_exit_seconds )); then
            attempt "loop_exit_${key}"
            say "the loop ${run} still runs ${loop_exit_seconds} s after it ended; the driver exits for supervisord to retry"
            exit 1
        fi
        sleep 1
        waited=$(( waited + 1 ))
    done
}

health_stopped() {
    local arm="$1" run="$2" policy=wait
    read_word "${arm}"
    if [[ -z "${word}" ]]; then
        if ! done_step "health_report_${arm}"; then
            "${python}" experiments/arms_chain.py health-report --arm "${arm}" --run "${run}" \
                > "${state}/health_report_${arm}.md" 2> "${state}/health_report_${arm}.log" \
                || say "the health report failed (health_report_${arm}.log)"
            touch "${state}/done_health_report_${arm}"
        fi
        [[ -f "${state}/on_health_stop" ]] && policy="$(tr -d '[:space:]' < "${state}/on_health_stop")"
        case "${policy}" in
            continue)
                say "arm ${arm} stopped on its health rule (health_report_${arm}.md); on_health_stop says continue: the next arm runs, and word_${arm} (skip or evaluate) is asked for at the end"
                finish "loop_${arm}"
                return 0
                ;;
            wait) ;;
            *) stop_chain "on_health_stop holds '${policy}': write wait or continue" ;;
        esac
        stop_servers
        stop_chain "arm ${arm} stopped on its health rule ($(head -c 300 "${run}/health_stop.json")): see health_report_${arm}.md; the owner decides: echo skip (no probe run) or evaluate (probe the last good version) > ${state}/word_${arm}, move STOPPED aside, supervisorctl start arms_chain"
    fi
    say "arm ${arm}: the owner's word after its health stop: ${word}"
    finish "loop_${arm}"
}

# An arm's (or a smoke run's) loop until it ends. Adopted when it already runs: no server is touched then.
run_loop() {
    local key="$1" kind="$2" overlay="$3" run="${LEAN_SEARCH_RUNS}/$4" poll="${poll_seconds}" sampler=""
    local publishing_since="" lock_since=""
    done_step "loop_${key}" && return 0
    mark_start "loop_${key}"
    if [[ "${kind}" == smoke ]]; then
        poll="${smoke_poll_seconds}"
        sample_resources "${run}" "${state}/smoke/readings_${key#smoke_}.tsv" "$$" &
        sampler=$!
    fi
    loop_alive "${run}" && say "${key}: its loop runs or a start of it is in flight (loop.pid $(cat "${run}/loop.pid" 2>/dev/null)): adopted, waiting for its end"
    while [[ ! -f "${run}/finished.json" && ! -f "${run}/health_stop.json" ]]; do
        if loop_process_alive "${run}"; then
            lock_since=""
            [[ "${key}" == "smoke_${smoke_killed_arm}" ]] && kill_while_publishing "${run}"
        elif run_lock_held "${run}"; then
            # arm_loop.sh's init and server starts take minutes; a lock held far longer without a loop is looked at.
            [[ -n "${lock_since}" ]] || { lock_since="$(date +%s)"; say "${key}: a start of its loop is in flight (${run}.lock held)"; }
            (( $(date +%s) - lock_since <= lock_wait_seconds )) \
                || stop_chain "${run}.lock is held for ${lock_wait_seconds} s without a live loop: find its holder (fuser -v ${run}.lock), stop it by PID, move STOPPED aside"
        elif [[ -f "${run}/finished.json" || -f "${run}/health_stop.json" ]]; then
            # It ended (and exited) between the two checks.
            continue
        elif [[ -f "${state}/pause_${key}" ]]; then
            stop_chain "${key} is paused (pause_${key}): its loop is not started again; to resume it delete pause_${key}, move STOPPED aside and start arms_chain"
        elif [[ "${key}" == "smoke_${smoke_killed_arm}" && -f "${state}/smoke/kill_${smoke_killed_arm}.json" \
            && ! -f "${state}/smoke/restarted_${smoke_killed_arm}" ]]; then
            touch "${state}/smoke/restarted_${smoke_killed_arm}"
            say "${key}: started again after the kill"
            start_loop "${key}" "${kind}" "${overlay}"
        else
            attempt "loop_${key}_start"
            start_loop "${key}" "${kind}" "${overlay}"
        fi
        sleep "${poll}"
    done
    wait_loop_exit "${key}" "${run}"
    [[ -n "${sampler}" ]] && kill "${sampler}" 2>/dev/null
    if [[ -f "${run}/finished.json" ]]; then
        say "${key}: finished: $(cat "${run}/finished.json")"
        finish "loop_${key}"
        return 0
    fi
    if [[ "${kind}" == smoke ]]; then
        stop_servers
        stop_chain "the smoke run ${run} stopped on its health check ($(head -c 300 "${run}/health_stop.json")): arm C does not start"
    fi
    health_stopped "${key}" "${run}"
}

probe_run() {
    local arm="$1" status=0
    done_step "probe_${arm}" && return 0
    attempt "probe_${arm}"
    mark_start "probe_${arm}"
    PROBE_CONCURRENCY=112 deployment/probe_runs.sh --foreground "${state}/probe/runs_${arm}.toml" \
        >> "${state}/probe/${arm}.log" 2>&1 || status=$?
    case "${status}" in
        0) finish "probe_${arm}" ;;
        3) stop_chain "arm ${arm}'s probe run was rejected for wall-clock stops (exit 3; probe/${arm}.log): repeat it at a doubled cap under a new name, with what it is compared with" ;;
        4) stop_chain "arm ${arm}'s probe run: the servers kept dying (exit 4; probe/${arm}.log, the servers' logs)" ;;
        *) say "arm ${arm}'s probe run exited ${status}; the driver exits for supervisord to retry (it resumes)"; exit 1 ;;
    esac
}

# Comparisons and the report only read results: a failure is logged and the GPUs move on to the next arm.
compare_arm() {
    local arm="$1" plan file x_run x_label y_label y_runs
    done_step "compare_${arm}" && return 0
    plan="$("${python}" experiments/arms_chain.py compare-plan --arm "${arm}" --state "${state}" 2> "${state}/compare/plan_${arm}.log")" \
        || stop_chain "compare-plan failed for ${arm}: $(tail -1 "${state}/compare/plan_${arm}.log")"
    while IFS=$'\t' read -r file x_run x_label y_label y_runs; do
        [[ -n "${file}" ]] || continue
        # shellcheck disable=SC2086
        "${python}" experiments/probe_compare.py pair --x "${x_run}" --x-label "${x_label}" --y ${y_runs} \
            --y-label "${y_label}" > "${state}/compare/${file}" 2> "${state}/compare/${file%.txt}.log" \
            || say "probe_compare.py failed for ${file} (compare/${file%.txt}.log); the chain goes on"
    done <<< "${plan}"
    touch "${state}/done_compare_${arm}"
}

# Adapters, then (unless the owner said skip after a health stop) the probe run and its comparisons, then the report.
evaluate_arm() {
    local arm="$1" run="${LEAN_SEARCH_RUNS}/followup_$1"
    read_word "${arm}"
    if ! done_step "adapters_${arm}"; then
        mark_start "adapters_${arm}"
        "${python}" experiments/arms_chain.py adapters --run "${run}" --output "${state}/adapters/${arm}" \
            > "${state}/adapters_${arm}.log" 2>&1 || stop_chain "copying arm ${arm}'s adapters failed: $(tail -1 "${state}/adapters_${arm}.log")"
        say "arm ${arm}: adapters for the PC: $(tail -1 "${state}/adapters_${arm}.log")"
        finish "adapters_${arm}"
    fi
    if [[ "${word}" != skip ]]; then
        if ! done_step "probe_list_${arm}"; then
            "${python}" experiments/arms_chain.py probe-list --arm "${arm}" --run "${run}" \
                --output "${state}/probe/runs_${arm}.toml" > "${state}/probe/list_${arm}.log" 2>&1 \
                || stop_chain "probe-list failed for ${arm}: $(tail -1 "${state}/probe/list_${arm}.log")"
            touch "${state}/done_probe_list_${arm}"
        fi
        probe_run "${arm}"
        compare_arm "${arm}"
    fi
    if ! done_step "report_${arm}"; then
        "${python}" experiments/arms_chain.py report --arm "${arm}" --run "${run}" --state "${state}" \
            --probe-runs "${LEAN_SEARCH_RUNS}/probe_evaluations" > "${state}/report_${arm}.md" \
            2> "${state}/report_${arm}.log" || say "the report of ${arm} failed (report_${arm}.log); the chain goes on"
        touch "${state}/done_report_${arm}"
        say "arm ${arm} done: $(grep -m1 '^- Probe run\|^- No probe run' "${state}/report_${arm}.md")"
    fi
}

# A health-stopped arm without the owner's word yet (on_health_stop = continue) waits for the end.
run_arm() {
    run_loop "$1" arm "${followup}/arms/$1.toml" "followup_$1"
    read_word "$1"
    if [[ -f "${LEAN_SEARCH_RUNS}/followup_$1/health_stop.json" && -z "${word}" ]]; then
        say "arm $1 waits for the owner's word (word_$1); the chain goes on"
        return 0
    fi
    evaluate_arm "$1"
}

smoke_test() {
    local status=0 arm
    done_step smoke && return 0
    mark_start smoke
    if ! done_step smoke_overlays; then
        "${python}" experiments/arms_chain.py smoke-overlays --output "${state}/smoke/overlays" \
            > "${state}/smoke/overlays.log" 2>&1 || stop_chain "smoke-overlays failed: $(tail -1 "${state}/smoke/overlays.log")"
        touch "${state}/done_smoke_overlays"
    fi
    for arm in C D; do
        run_loop "smoke_${arm}" smoke "${state}/smoke/overlays/${arm}.toml" "followup_smoke_${arm}"
    done
    "${python}" experiments/arms_chain.py smoke-check --runs "${LEAN_SEARCH_RUNS}" --checkpoints "${LEAN_SEARCH_CHECKPOINTS}" \
        --state "${state}" --output "${state}/smoke_report.md" > "${state}/smoke/check.log" 2>&1 || status=$?
    case "${status}" in
        0) say "smoke test passed: smoke_report.md"; finish smoke ;;
        3)
            stop_servers
            stop_chain "the smoke test failed ($(tail -1 "${state}/smoke/check.log")): see smoke_report.md; arm C does not start"
            ;;
        *) stop_chain "the smoke check could not run: $(tail -1 "${state}/smoke/check.log")" ;;
    esac
}

for step in "${order[@]}"; do
    case "${step}" in
        smoke) smoke_test ;;
        *)
            if [[ -f "${state}/hold_${step}" ]]; then
                # A held arm's run directory (an old, stopped run before a rerun) is never adopted or resumed.
                loop_alive "${LEAN_SEARCH_RUNS}/followup_${step}" \
                    && stop_chain "arm ${step} is held (hold_${step}) but its loop runs or a start of it is in flight: stop it (pause_${step}, then grpo_loop.sh stop) or remove the hold"
                # The steps after it wait too (D after A: both train on the reward a rerun of A waits for).
                stop_servers
                echo "$(date -u +%FT%TZ) waiting for: ${step} (hold_${step}) in the order ${order[*]}; the steps before it are done; the servers are stopped" > "${state}/HOLD"
                say "HOLD: waiting for: ${step} (hold_${step}); the servers are stopped"
                exit 0
            fi
            run_arm "${step}"
            ;;
    esac
done

# The arms that stopped on their health rule while the chain went on: their evaluation waits for the owner's word.
for arm in "${order[@]}"; do
    [[ "${arm}" == smoke ]] && continue
    [[ -f "${LEAN_SEARCH_RUNS}/followup_${arm}/health_stop.json" ]] || continue
    read_word "${arm}"
    if [[ -z "${word}" ]]; then
        stop_servers
        stop_chain "the arms are done but arm ${arm}'s health stop waits for the owner's word (health_report_${arm}.md): echo skip or evaluate > ${state}/word_${arm}, move STOPPED aside, supervisorctl start arms_chain"
    fi
    evaluate_arm "${arm}"
done

stop_servers
echo "$(date -u +%FT%TZ) the order ${order[*]} is done: its reports are report_<arm>.md; the servers are stopped" > "${state}/HOLD"
say "HOLD: the order ${order[*]} is done; the servers are stopped"
