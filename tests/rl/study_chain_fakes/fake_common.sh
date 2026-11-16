# Sourced by the stand-ins for the study driver's commands (tests/rl/test_study_chain_script.py). FAKE_LOG gets one
# line per command; FAKE_SCENARIO holds what should go wrong: kill_<key> kills the driver's whole process group once
# (as a container restart or supervisord's stop would), fail_<key> holds how many more calls fail.

log_command() { echo "$*" >> "${FAKE_LOG}"; }

outcome() {
    local key="$1" count
    if [[ -f "${FAKE_SCENARIO}/kill_${key}" ]]; then
        rm "${FAKE_SCENARIO}/kill_${key}"
        log_command "killed at ${key}"
        kill -KILL -- "-$(ps -o pgid= -p $$ | tr -d ' ')"
    fi
    if [[ -f "${FAKE_SCENARIO}/fail_${key}" ]]; then
        count="$(cat "${FAKE_SCENARIO}/fail_${key}")"
        if (( count > 0 )); then
            echo $(( count - 1 )) > "${FAKE_SCENARIO}/fail_${key}"
            log_command "failed at ${key}"
            return 1
        fi
    fi
    return 0
}

# The value after an option in the arguments, e.g. option_value --name "$@".
option_value() {
    local option="$1"
    shift
    while (( $# > 1 )); do
        if [[ "$1" == "${option}" ]]; then echo "$2"; return 0; fi
        shift
    done
    return 1
}
