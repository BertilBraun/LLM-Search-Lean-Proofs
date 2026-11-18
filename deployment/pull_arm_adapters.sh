#!/usr/bin/env bash
# On the PC (Git Bash): fetches the arms' LoRA adapters the node's arms driver copied for it (deployment/arms_chain.sh,
# $state/adapters/<arm>: phase 8 and the final checkpoint, policy and value, with manifest.sha256), once per arm.
#
#   NODE_SSH="ssh -i ~/.ssh/vast-ssh -p <port> -o ConnectTimeout=12 -o BatchMode=yes root@<host>" \
#       deployment/pull_arm_adapters.sh <live directory> <adapters directory>
#
# <live directory> is the results pull's copy of the node's /workspace (node_backup/2026-11-15/live): an arm is fetched
# once its manifest arrived there (runs/arms_chain/adapters/<arm>/manifest.sha256; the results pull leaves the weights
# out). Each arm goes to <adapters directory>/<arm>/ through a partial directory, is checked with sha256sum -c against
# its manifest and only then renamed into place with a `verified` file; an arm already verified with the same manifest
# is skipped, so the results pull loop may call this after every pull. Exits 1 if a fetch or check failed (the partial
# copy is removed; the next call tries again). NODE_ADAPTERS overrides the node's directory.
set -uo pipefail
[[ $# -eq 2 && -n "${NODE_SSH:-}" ]] || { sed -n '2,15p' "$0" >&2; exit 2; }
live="$1"
adapters="$2"
node_adapters="${NODE_ADAPTERS:-/workspace/runs/arms_chain/adapters}"
mkdir -p "${adapters}"
status=0
shopt -s nullglob
for manifest in "${live}"/runs/arms_chain/adapters/*/manifest.sha256; do
    arm="$(basename "$(dirname "${manifest}")")"
    target="${adapters}/${arm}"
    if [[ -f "${target}/verified" ]] && cmp -s "${manifest}" "${target}/manifest.sha256"; then
        continue
    fi
    partial="${adapters}/.${arm}.partial"
    rm -rf "${partial}"
    mkdir -p "${partial}"
    # shellcheck disable=SC2086
    if ! timeout 3600 ${NODE_SSH} "tar -C '${node_adapters}/${arm}' -cf - ." | tar -xf - -C "${partial}"; then
        echo "$(date -u +%FT%TZ) fetching arm ${arm}'s adapters failed" >&2
        rm -rf "${partial}"
        status=1
        continue
    fi
    if ! (cd "${partial}" && sha256sum --quiet -c manifest.sha256) || ! cmp -s "${manifest}" "${partial}/manifest.sha256"; then
        echo "$(date -u +%FT%TZ) arm ${arm}'s adapters do not match the manifest" >&2
        rm -rf "${partial}"
        status=1
        continue
    fi
    [[ -e "${target}" ]] && mv "${target}" "${target}.replaced_$(date -u +%Y%m%dT%H%M%SZ)"
    date -u +%FT%TZ > "${partial}/verified"
    mv "${partial}" "${target}"
    echo "$(date -u +%FT%TZ) arm ${arm}'s adapters verified in ${target}"
done
exit "${status}"
