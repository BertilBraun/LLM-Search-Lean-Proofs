#!/usr/bin/env bash
# The stand-in for deployment/arm_loop.sh: logged with its kind and arm; holds the run's lock as the real one does (fd 9
# on <run>.lock, inherited by the detached loop; a second start while it is held fails), takes FAKE_ARM_LOOP_SECONDS
# (0) as the real one's init and server starts take minutes, then starts fake_loop.sh detached (an arm 16 phases with
# stages of FAKE_ARM_STAGE_SECONDS, 0 by default; a smoke run 1 phase with stages of FAKE_STAGE_SECONDS), its pid in
# loop.pid, unless the run finished. fail_arm_loop makes it fail before starting anything.
source "$(dirname "$0")/fake_common.sh"
[[ "$1" == --kind && "$3" == --mode && -f "$4" ]] || exit 2
kind="$2"
arm="$(basename "$5" .toml)"
log_command "arm_loop.sh ${kind} ${arm}"
outcome arm_loop || exit 1
if [[ "${kind}" == smoke ]]; then
    name="followup_smoke_${arm}" phases=1 seconds="${FAKE_STAGE_SECONDS:-0.3}"
else
    name="followup_${arm}" phases=16 seconds="${FAKE_ARM_STAGE_SECONDS:-0}"
fi
run="${LEAN_SEARCH_RUNS}/${name}"
[[ -f "${run}/finished.json" ]] && exit 0
exec 9> "${run}.lock"
flock -n 9 || { log_command "arm_loop.sh refused: ${name} locked"; exit 1; }
sleep "${FAKE_ARM_LOOP_SECONDS:-0}"
mkdir -p "${run}"
nohup bash "$(dirname "$0")/fake_loop.sh" grpo_loop.py "${run}" "${phases}" "${seconds}" "${FAKE_SCENARIO}" \
    --config "${LEAN_SEARCH_RUNS}/followup_configs/${name}/loop.toml" >> "${run}/loop.out" 2>&1 < /dev/null &
echo $! > "${run}/loop.pid"
