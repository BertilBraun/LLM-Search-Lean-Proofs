#!/usr/bin/env bash
# Sourced by serve_model.sh, stop_model.sh and arm_loop.sh: a server's pid file (<name>.pid, the process group
# serve_model.sh started vLLM in) is trusted only when it was written since the host booted and its process is a vLLM
# started for that server about when the file was written. A pid reused after a host reboot, or by another job, is
# not, and is never signalled (src/lean_search/policy/server_processes.py is the same rule in Python).

pid_start_slack_seconds=60
# serve_model.sh's own wait for /health: an engine process starts within it.
server_start_seconds="${SERVER_START_TIMEOUT:-900}"

boot_seconds() {
    awk '/^btime/ {print $2}' /proc/stat
}

# Seconds since the epoch at which the process started; fails when it does not exist.
process_start_seconds() {
    local stat_line start_ticks
    stat_line="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
    # Field 22 of the line; the command name before it may hold spaces.
    start_ticks="$(sed 's/.*) //' <<< "${stat_line}" | awk '{print $20}')"
    echo $(( $(boot_seconds) + start_ticks / $(getconf CLK_TCK) ))
}

# A pid file from before the host booted names a process of an earlier boot: stale, whatever runs under its number.
written_since_boot() {
    (( $(stat -c %Y "$1") >= $(boot_seconds) ))
}

# Prints the pid when <pid file> names a live `vllm serve ... --served-model-name <name>` started within the slack of
# the file's time; fails otherwise.
trusted_server_pid() {
    local pid_file="$1" name="$2" pid arguments started written
    [[ -f "${pid_file}" ]] && written_since_boot "${pid_file}" || return 1
    pid="$(cat "${pid_file}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    arguments="$(tr '\0' '\n' 2>/dev/null < "/proc/${pid}/cmdline")" || return 1
    head -n 2 <<< "${arguments}" | grep -q '\(^\|/\)vllm$' || return 1
    grep -qxF -- serve <<< "${arguments}" || return 1
    grep -A1 -xF -- --served-model-name <<< "${arguments}" | grep -qxF -- "${name}" || return 1
    started="$(process_start_seconds "${pid}")" || return 1
    written="$(stat -c %Y "${pid_file}")"
    (( started - written <= pid_start_slack_seconds && written - started <= pid_start_slack_seconds )) || return 1
    echo "${pid}"
}

# The process group's members that are not zombies (a container's PID 1 may never reap an exited server).
live_group_members() {
    ps -eo pid=,pgid=,stat= 2>/dev/null | awk -v group="$1" '$2 == group && $3 !~ /^Z/ {print $1}'
}

parent_pid() {
    sed 's/.*) //' "/proc/$1/stat" | awk '{print $2}'
}

# serve_model.sh records the server's processes (pid, start and parent, one a line) in <name>.members once it
# answers; files from before the parent was recorded have pid and start only.
record_server_members() {
    local group="$1" members_file="$2" member
    for member in $(live_group_members "${group}"); do
        echo "${member} $(process_start_seconds "${member}") $(parent_pid "${member}")"
    done > "${members_file}"
}

# vLLM's CLI (argument 1 or 2 ends in vllm) or a process title such as VLLM::EngineCore, which also overwrites its
# environment.
vllm_command() {
    local argument
    for argument in "${@:1:2}"; do
        [[ "${argument}" == vllm || "${argument}" == */vllm || "${argument}" == VLLM::* ]] && return 0
    done
    return 1
}

# The resource tracker Python's multiprocessing starts beside the API process: `python [flags] -c <its code>`.
resource_tracker_command() {
    local interpreter='(^|/)python[0-9.]*$' code='^from multiprocessing\.resource_tracker import main;main\([0-9]+\)$'
    (( $# >= 3 )) && [[ "$1" =~ ${interpreter} && "${*: -2:1}" == -c && "${*: -1}" =~ ${code} ]]
}

# Whether <pid> is a process of the server whose group is <group>: recorded in <members file> with its start, started
# between the pid file's write and the end of the start's wait, and either a vLLM process or the resource tracker of
# the group's API process (its parent now, or when the members were recorded: once the API process died it is init).
server_member() {
    local member="$1" members_file="$2" written="$3" group="$4" arguments=() started recorded_parent
    mapfile -d '' -t arguments 2>/dev/null < "/proc/${member}/cmdline" || return 1
    started="$(process_start_seconds "${member}")" || return 1
    [[ -f "${members_file}" ]] || return 1
    recorded_parent="$(awk -v member="${member}" -v started="${started}" \
        '$1 == member && $2 == started {print $3; found = 1} END {exit !found}' "${members_file}")" || return 1
    (( started >= written - pid_start_slack_seconds && started <= written + server_start_seconds )) || return 1
    vllm_command "${arguments[@]}" && return 0
    resource_tracker_command "${arguments[@]}" || return 1
    [[ "${recorded_parent}" == "${group}" || "$(parent_pid "${member}")" == "${group}" ]]
}

# What is left of a server whose API process (the group's leader) died, a zombie or gone, while other processes of
# its group live on. Prints the group and returns 0 when every live member is a process of the server (`server_member`,
# against <name>.members beside the pid file); returns 1 when the pid file is stale (from before the boot, its leader
# alive as another process, or nothing of its group left); returns 2, naming the members, when a live member is not
# the server's (or its start never recorded them): then nothing may be signalled.
orphaned_server_group() {
    local pid_file="$1" name="$2" group written state member members foreign=()
    local members_file="${pid_file%.pid}.members"
    written_since_boot "${pid_file}" || return 1
    group="$(cat "${pid_file}")"
    [[ "${group}" =~ ^[0-9]+$ ]] || return 1
    written="$(stat -c %Y "${pid_file}")"
    if [[ -e "/proc/${group}" ]]; then
        state="$(sed 's/.*) //' "/proc/${group}/stat" | awk '{print $1}')"
        [[ "${state}" == Z ]] || return 1
    fi
    members="$(live_group_members "${group}")"
    [[ -n "${members}" ]] || return 1
    for member in ${members}; do
        server_member "${member}" "${members_file}" "${written}" "${group}" || foreign+=("${member}")
    done
    if (( ${#foreign[@]} )); then
        echo "${foreign[*]}"
        return 2
    fi
    echo "${group}"
}
