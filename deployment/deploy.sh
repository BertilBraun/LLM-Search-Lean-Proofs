#!/usr/bin/env bash
# Push the committed local branch to GitHub and fast-forward the node's checkout to it.
#
#   deployment/deploy.sh

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "$(git -C "${script_directory}/.." status --porcelain --untracked-files=no)" ]]; then
    echo "Uncommitted changes to tracked files; commit them before deploying." >&2
    exit 1
fi

branch="$(git -C "${script_directory}/.." rev-parse --abbrev-ref HEAD)"
git -C "${script_directory}/.." push origin "${branch}"
"${script_directory}/on_node.sh" "git fetch origin ${branch} && git checkout ${branch} && git pull --ff-only origin ${branch} && git log -1 --oneline"
