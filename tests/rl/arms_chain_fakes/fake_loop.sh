#!/usr/bin/env bash
# The arms driver's stand-in loop, started as `fake_loop.sh grpo_loop.py <run> <phases> <stage seconds> <scenario>`
# (its command line names grpo_loop.py, as the driver checks before a kill): phase by phase through the stages, written
# to loop_state.json as the real loop's first two fields, resumed from the stage it was in when started again. Each
# phase trained is a line "trained <k>" in <run>/trained, each published "published <k>" in <run>/published. Scenario
# files: health_stop_<name> (a collapse at phase 3, or the last phase if earlier), die_<name> (how many starts die after
# the first phase they close).
run="$2"
phases="$3"
seconds="$4"
scenario="$5"
name="$(basename "${run}")"
echo "Loop ${name}: version, pid $$" >> "${run}/loop.log"

position() { printf '{"phase": %s, "stage": "%s", "sampling_seconds": 0.0}\n' "$1" "$2" > "${run}/loop_state.json"; }

read -r phase stage < <(sed -n 's/^{"phase": *\([0-9]*\), *"stage": *"\([a-z]*\)".*/\1 \2/p' "${run}/loop_state.json" 2>/dev/null)
phase="${phase:-1}"
stage="${stage:-sampling}"
dies=0
if [[ -f "${scenario}/die_${name}" ]] && (( $(cat "${scenario}/die_${name}") > 0 )); then
    echo $(( $(cat "${scenario}/die_${name}") - 1 )) > "${scenario}/die_${name}"
    dies=1
fi

while (( phase <= phases )); do
    if [[ "${stage}" == sampling || "${stage}" == training ]]; then
        position "${phase}" sampling
        sleep "${seconds}"
        position "${phase}" training
        echo "trained ${phase}" >> "${run}/trained"
        sleep "${seconds}"
        stage=publishing
    fi
    if [[ "${stage}" == publishing ]]; then
        position "${phase}" publishing
        sleep "$(awk -v seconds="${seconds}" 'BEGIN { print 3 * seconds }')"
        grep -qx "published ${phase}" "${run}/published" 2>/dev/null || echo "published ${phase}" >> "${run}/published"
    fi
    position "${phase}" evaluating
    sleep "${seconds}"
    if (( phase == (phases < 3 ? phases : 3) )) && [[ -f "${scenario}/health_stop_${name}" ]]; then
        echo '{"phase": 3, "policy_version": 3, "last_good_version": 2, "reason": "collapse", "stopped_at": "now"}' \
            > "${run}/health_stop.json"
        rm -f "${run}/loop.pid"
        exit 0
    fi
    if (( dies )); then
        position $(( phase + 1 )) sampling
        exit 1
    fi
    phase=$(( phase + 1 ))
    stage=sampling
    position "${phase}" sampling
done
echo "{\"last_phase\": ${phases}, \"generated_tokens\": 1, \"lost_tokens\": 0, \"finished_at\": \"now\"}" > "${run}/finished.json"
rm -f "${run}/loop.pid"
