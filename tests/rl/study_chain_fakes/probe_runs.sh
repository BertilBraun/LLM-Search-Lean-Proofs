#!/usr/bin/env bash
# The stand-in for deployment/probe_runs.sh: logged with its concurrency and lists; probe_exit holds an exit status to
# end with once (3: a rejected run, 4: servers that kept dying).
source "$(dirname "$0")/fake_common.sh"
[[ "$1" == --foreground ]] || exit 2
shift
log_command "probe_runs.sh PROBE_CONCURRENCY=${PROBE_CONCURRENCY:-unset} $(basename "$1")"
outcome probe || exit 1
if [[ -f "${FAKE_SCENARIO}/probe_exit" ]]; then
    status="$(cat "${FAKE_SCENARIO}/probe_exit")"
    rm "${FAKE_SCENARIO}/probe_exit"
    exit "${status}"
fi
exit 0
