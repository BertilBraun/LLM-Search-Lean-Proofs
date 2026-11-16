#!/usr/bin/env bash
# The stand-in for deployment/stop_model.sh, logged; fail_stop makes it refuse as the real one does for a pid file
# whose process group has foreign members.
source "$(dirname "$0")/fake_common.sh"
log_command "stop_model.sh $*"
outcome stop
