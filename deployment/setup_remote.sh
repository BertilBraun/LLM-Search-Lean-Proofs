#!/usr/bin/env bash
# Provision a node: clone (or fast-forward) the repository, then install the Python and Lean environments.
#
#   deployment/remote_command.sh <node> 'bash -s' < deployment/setup_remote.sh
#
# Idempotent: re-running it on a provisioned node only pulls and re-syncs.

set -euo pipefail

repository_url="${LEAN_SEARCH_REPOSITORY_URL:-https://github.com/BertilBraun/LLM-Search-Lean-Proofs.git}"
repository_directory="${LEAN_SEARCH_ROOT:-/workspace/LLM-Search-Lean-Proofs}"
repository_ref="${LEAN_SEARCH_REPOSITORY_REF:-master}"

for required_command in git curl; do
    if ! command -v "${required_command}" >/dev/null 2>&1; then
        echo "Required command is unavailable: ${required_command}" >&2
        exit 1
    fi
done

if [[ -d "${repository_directory}/.git" ]]; then
    git -C "${repository_directory}" fetch origin "${repository_ref}"
    git -C "${repository_directory}" checkout "${repository_ref}"
    git -C "${repository_directory}" pull --ff-only origin "${repository_ref}"
else
    mkdir -p "$(dirname "${repository_directory}")"
    git clone --branch "${repository_ref}" "${repository_url}" "${repository_directory}"
fi

cd "${repository_directory}"
source deployment/environment.sh

deployment/setup_python.sh
deployment/setup_lean.sh

echo "Node provisioned at revision $(git rev-parse --short HEAD)."
