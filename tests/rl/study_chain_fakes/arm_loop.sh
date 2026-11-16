#!/usr/bin/env bash
# The stand-in for deployment/arm_loop.sh: the shared sampling run ends at once (finished.json), stops on its health
# check (health_stop in the scenario), or leaves a dead loop behind for the next `dead_loops` calls.
source "$(dirname "$0")/fake_common.sh"
log_command "arm_loop.sh $*"
run="${LEAN_SEARCH_RUNS}/followup_shared_sampling"
mkdir -p "${run}/trees" "${LEAN_SEARCH_RUNS}/followup_configs/followup_shared_sampling"
touch "${LEAN_SEARCH_RUNS}/followup_configs/followup_shared_sampling/loop.toml"
outcome sampling || exit 1
if [[ -f "${FAKE_SCENARIO}/health_stop" ]]; then
    echo '{"phase": 1, "reason": "held-out valid Lean below 0.7 of v0"}' > "${run}/health_stop.json"
    exit 0
fi
if outcome dead_loop; then
    echo '{"last_phase": 0, "generated_tokens": 48000000, "lost_tokens": 0, "finished_at": "now"}' > "${run}/finished.json"
else
    # A loop that died after its start: a pid no process has.
    echo 999999999 > "${run}/loop.pid"
fi
