#!/usr/bin/env bash
# Run a command on the node from inside the repository checkout, with deployment/environment.sh loaded.
#
#   deployment/on_node.sh 'pytest tests/lean'
#   deployment/on_node.sh 'python experiments/phase0_statement_check.py --split valid'
#
# The node address comes from $LEAN_SEARCH_NODE or the untracked file deployment/.node_address
# (HOST:PORT, e.g. 221.6.203.117:50812).

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node_address="${LEAN_SEARCH_NODE:-$(cat "${script_directory}/.node_address")}"
repository_directory="${LEAN_SEARCH_ROOT:-/workspace/LLM-Search-Lean-Proofs}"

[[ $# -ge 1 ]] || { echo "Usage: on_node.sh <command>" >&2; exit 2; }

exec "${script_directory}/remote_command.sh" "${node_address}" \
    "cd ${repository_directory} && source deployment/environment.sh && $*"
