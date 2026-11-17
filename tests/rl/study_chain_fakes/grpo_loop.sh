#!/usr/bin/env bash
# The stand-in for deployment/grpo_loop.sh: only `servers`, logged; each call's LOOP_CONFIG goes to servers_loop_configs.
source "$(dirname "$0")/fake_common.sh"
log_command "grpo_loop.sh $1"
echo "${LOOP_CONFIG:-unset}" >> "${FAKE_WORKSPACE}/servers_loop_configs"
outcome servers
