#!/usr/bin/env bash
# Push the committed local branch to GitHub and fast-forward the node's checkout to it.
#
#   deployment/deploy.sh
#
# Only commits travel; uncommitted local changes are reported but not deployed. Never edit tracked files on the
# node, or the fast-forward fails. The node's own connection to GitHub is unreliable, so the commits are shipped
# as a git bundle over SSH instead of being fetched there.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_directory="${script_directory}/.."

uncommitted="$(git -C "${repository_directory}" status --porcelain --untracked-files=no)"
if [[ -n "${uncommitted}" ]]; then
    echo "Not deployed (uncommitted):" >&2
    echo "${uncommitted}" >&2
fi

branch="$(git -C "${repository_directory}" rev-parse --abbrev-ref HEAD)"
git -C "${repository_directory}" push -q origin "${branch}" || echo "GitHub push failed; deploying to the node anyway." >&2

node_head="$("${script_directory}/on_node.sh" "git rev-parse HEAD")"
local_head="$(git -C "${repository_directory}" rev-parse "${branch}")"
if [[ "${node_head}" == "${local_head}" ]]; then
    echo "Node already at $(git -C "${repository_directory}" log -1 --oneline "${branch}")"
    exit 0
fi

bundle_file="$(mktemp)"
trap 'rm -f "${bundle_file}"' EXIT
if git -C "${repository_directory}" cat-file -e "${node_head}^{commit}" 2>/dev/null; then
    git -C "${repository_directory}" bundle create -q "${bundle_file}" "${node_head}..${branch}"
else
    git -C "${repository_directory}" bundle create -q "${bundle_file}" "${branch}"
fi

"${script_directory}/on_node.sh" \
    "cat > /tmp/deploy-\$\$.bundle && git checkout -q ${branch} && git pull -q --ff-only /tmp/deploy-\$\$.bundle ${branch}; status=\$?; rm -f /tmp/deploy-\$\$.bundle; git log -1 --oneline; exit \${status}" \
    < "${bundle_file}"
