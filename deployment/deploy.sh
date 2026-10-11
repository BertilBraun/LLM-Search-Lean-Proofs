#!/usr/bin/env bash
# Push the committed local branch to GitHub and fast-forward the node's checkout to it.
#
#   deployment/deploy.sh
#
# Only commits travel; uncommitted local changes are reported but not deployed. Never edit tracked files on the
# node, or the fast-forward fails.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_directory="${script_directory}/.."

uncommitted="$(git -C "${repository_directory}" status --porcelain --untracked-files=no)"
if [[ -n "${uncommitted}" ]]; then
    echo "Not deployed (uncommitted):" >&2
    echo "${uncommitted}" >&2
fi

branch="$(git -C "${repository_directory}" rev-parse --abbrev-ref HEAD)"
git -C "${repository_directory}" push origin "${branch}"
"${script_directory}/on_node.sh" \
    "git fetch -q origin ${branch} && git checkout -q ${branch} && git pull -q --ff-only origin ${branch} && git log -1 --oneline"
