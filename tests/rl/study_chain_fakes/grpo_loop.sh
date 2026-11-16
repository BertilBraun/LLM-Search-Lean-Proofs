#!/usr/bin/env bash
# The stand-in for deployment/grpo_loop.sh: only `servers`, logged.
source "$(dirname "$0")/fake_common.sh"
log_command "grpo_loop.sh $1"
outcome servers
