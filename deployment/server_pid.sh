#!/usr/bin/env bash
# Sourced by serve_model.sh, stop_model.sh and arm_loop.sh: a server's pid file (<name>.pid, the process group
# serve_model.sh started vLLM in) is trusted only when its process is a vLLM started for that server about when the
# file was written. A pid reused after a host reboot, or by another job, is not, and is never signalled
# (src/lean_search/policy/server_processes.py is the same rule in Python).

pid_start_slack_seconds=60

# Seconds since the epoch at which the process started; fails when it does not exist.
process_start_seconds() {
    local stat_line start_ticks boot_seconds
    stat_line="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
    # Field 22 of the line; the command name before it may hold spaces.
    start_ticks="$(sed 's/.*) //' <<< "${stat_line}" | awk '{print $20}')"
    boot_seconds="$(awk '/^btime/ {print $2}' /proc/stat)"
    echo $(( boot_seconds + start_ticks / $(getconf CLK_TCK) ))
}

# Prints the pid when <pid file> names a live `vllm serve ... --served-model-name <name>` started within the slack of
# the file's time; fails otherwise.
trusted_server_pid() {
    local pid_file="$1" name="$2" pid arguments started written
    [[ -f "${pid_file}" ]] || return 1
    pid="$(cat "${pid_file}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    arguments="$(tr '\0' '\n' < "/proc/${pid}/cmdline" 2>/dev/null)" || return 1
    head -n 2 <<< "${arguments}" | grep -q '\(^\|/\)vllm$' || return 1
    grep -qx -- serve <<< "${arguments}" || return 1
    grep -A1 -x -- --served-model-name <<< "${arguments}" | grep -qx -- "${name}" || return 1
    started="$(process_start_seconds "${pid}")" || return 1
    written="$(stat -c %Y "${pid_file}")"
    (( started - written <= pid_start_slack_seconds && written - started <= pid_start_slack_seconds )) || return 1
    echo "${pid}"
}

# The process group's members that are not zombies (a container's PID 1 may never reap an exited server).
live_group_members() {
    ps -eo pid=,pgid=,stat= | awk -v group="$1" '$2 == group && $3 !~ /^Z/ {print $1}'
}

# Prints the process group of <pid file>'s server when what is left of it can be told apart from anything else: its
# leader (the API process) a zombie or gone, and every member alive started after the file was written (while a
# member lives, its group's number is not handed to a new process). That is a server whose API process died while its
# engine process lives on.
orphaned_server_group() {
    local pid_file="$1" group written member started state
    group="$(cat "${pid_file}")"
    [[ "${group}" =~ ^[0-9]+$ ]] || return 1
    written="$(stat -c %Y "${pid_file}")"
    if [[ -e "/proc/${group}" ]]; then
        state="$(sed 's/.*) //' "/proc/${group}/stat" | awk '{print $1}')"
        [[ "${state}" == Z ]] || return 1
    fi
    for member in $(live_group_members "${group}"); do
        started="$(process_start_seconds "${member}")" || continue
        (( started >= written - pid_start_slack_seconds )) || return 1
    done
    [[ -n "$(live_group_members "${group}")" ]] || return 1
    echo "${group}"
}
