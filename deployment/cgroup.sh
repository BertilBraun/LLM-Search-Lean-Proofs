#!/usr/bin/env bash
# Sourced by environment.sh. CGROUP_ROOT (default /sys/fs/cgroup) points it at another tree.

# The cgroup's CPU quota in whole cores (at least 1), from cgroup v2's cpu.max or v1's cpu/cpu.cfs_quota_us and
# cpu/cpu.cfs_period_us; prints nothing when unlimited.
cgroup_quota_cores() {
    local root="${CGROUP_ROOT:-/sys/fs/cgroup}" quota period
    if [[ -r "${root}/cpu.max" ]]; then
        read -r quota period < "${root}/cpu.max"
        [[ "${quota}" != max ]] || return 0
    elif [[ -r "${root}/cpu/cpu.cfs_quota_us" ]]; then
        read -r quota < "${root}/cpu/cpu.cfs_quota_us"
        read -r period < "${root}/cpu/cpu.cfs_period_us"
        (( quota != -1 )) || return 0
    else
        return 0
    fi
    echo $(( quota / period > 0 ? quota / period : 1 ))
}

# The CPUs the cgroup's cpuset allows (v2 cpuset.cpus.effective, v1 cpuset/cpuset.cpus), else all the host's, as a
# CPU list: never the caller's affinity, which a pinned caller has narrowed.
cgroup_allowed_cpus() {
    local root="${CGROUP_ROOT:-/sys/fs/cgroup}" cpus=""
    if [[ -r "${root}/cpuset.cpus.effective" ]]; then
        cpus="$(< "${root}/cpuset.cpus.effective")"
    elif [[ -r "${root}/cpuset/cpuset.cpus" ]]; then
        cpus="$(< "${root}/cpuset/cpuset.cpus")"
    fi
    echo "${cpus:-0-$(( $(nproc --all) - 1 ))}"
}
