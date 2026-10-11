#!/usr/bin/env bash
# Copy an experiment's summary from the node into the local results/ directory for committing.
#
#   deployment/fetch_results.sh phase0_environment
#
# Experiments never write into the node's checkout (it only fast-forwards). Each run writes everything meant to be
# committed into $LEAN_SEARCH_RUNS/<run>/summary/; this mirrors that directory to results/<run>/.

set -euo pipefail

[[ $# -eq 1 ]] || { echo "Usage: fetch_results.sh <run name>" >&2; exit 2; }

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run_name="$1"
local_directory="${script_directory}/../results/${run_name}"

mkdir -p "${local_directory}"
"${script_directory}/on_node.sh" "tar czf - -C \"\${LEAN_SEARCH_RUNS}/${run_name}/summary\" ." | tar xzf - -C "${local_directory}"
ls -la "${local_directory}"
