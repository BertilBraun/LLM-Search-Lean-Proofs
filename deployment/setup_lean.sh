#!/usr/bin/env bash
# Install elan, the pinned Lean toolchain, Mathlib (prebuilt cache, else a source build) and the REPL for lean/.
#
#   deployment/setup_lean.sh
#
# Idempotent. Pins live in lean/lean-toolchain and lean/lake-manifest.json. GitHub release downloads are checked
# against the SHA-256 sums below and go through $LEAN_SEARCH_GITHUB_PROXY when set (e.g. https://ghfast.top/ where
# they are throttled). Lake packages are shallow-fetched at their manifest revisions, because Lake itself would clone
# the full Mathlib history. Needs git, curl, python3 and zstd.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${script_directory}/environment.sh"

lean_directory="${LEAN_SEARCH_ROOT}/lean"
github_proxy="${LEAN_SEARCH_GITHUB_PROXY:-}"

elan_version="v4.2.4"
elan_sha256="42b94d4244e8353142c456ec0e4ca6528fd898a6c604d4059f494e706e431f63"
declare -A toolchain_sha256=(
    ["v4.9.0-rc1"]="a6c521a9329aa03fb167e45df8e30be83a5512fc6f74f9c3edf67019a0705068"
)

for required_command in git curl python3 zstd; do
    if ! command -v "${required_command}" >/dev/null 2>&1; then
        echo "Required command is unavailable: ${required_command}" >&2
        exit 1
    fi
done

download_verified() {
    local url="$1" sha256="$2" output="$3"
    curl -fsSL --retry 5 --retry-all-errors -o "${output}.part" "${github_proxy}${url}"
    echo "${sha256}  ${output}.part" | sha256sum --check --quiet
    mv "${output}.part" "${output}"
}

install_elan() {
    if [[ -x "${HOME}/.elan/bin/elan" ]]; then
        return
    fi
    local temporary_directory
    temporary_directory="$(mktemp -d)"
    download_verified \
        "https://github.com/leanprover/elan/releases/download/${elan_version}/elan-x86_64-unknown-linux-gnu.tar.gz" \
        "${elan_sha256}" "${temporary_directory}/elan.tar.gz"
    tar xzf "${temporary_directory}/elan.tar.gz" -C "${temporary_directory}"
    "${temporary_directory}/elan-init" -y --default-toolchain none --no-modify-path
    rm -rf "${temporary_directory}"
}

install_toolchain() {
    local toolchain version directory temporary_directory
    toolchain="$(tr -d '[:space:]' < "${lean_directory}/lean-toolchain")"
    version="${toolchain#leanprover/lean4:}"
    directory="${HOME}/.elan/toolchains/$(echo "${toolchain}" | sed 's|/|--|; s|:|---|')"
    if [[ -x "${directory}/bin/lean" ]]; then
        return
    fi
    [[ -n "${toolchain_sha256[${version}]:-}" ]] || { echo "No checksum pinned for ${toolchain}" >&2; exit 1; }
    temporary_directory="$(mktemp -d)"
    download_verified \
        "https://github.com/leanprover/lean4/releases/download/${version}/lean-${version#v}-linux.tar.zst" \
        "${toolchain_sha256[${version}]}" "${temporary_directory}/lean.tar.zst"
    tar --zstd -xf "${temporary_directory}/lean.tar.zst" -C "${temporary_directory}"
    mkdir -p "$(dirname "${directory}")"
    mv "${temporary_directory}/lean-${version#v}-linux" "${directory}"
    rm -rf "${temporary_directory}"
}

fetch_packages() {
    mkdir -p "${lean_directory}/.lake/packages"
    python3 -c '
import json, sys
for package in json.load(open(sys.argv[1]))["packages"]:
    print(package["name"], package["url"], package["rev"])
' "${lean_directory}/lake-manifest.json" | while read -r name url revision; do
        local directory="${lean_directory}/.lake/packages/${name}"
        if [[ "$(git -C "${directory}" rev-parse HEAD 2>/dev/null)" == "${revision}" ]]; then
            continue
        fi
        echo "Fetching ${name} at ${revision}"
        rm -rf "${directory}"
        git init -q "${directory}"
        git -C "${directory}" remote add origin "${github_proxy}${url}"
        git -C "${directory}" fetch -q --depth 1 origin "${revision}"
        git -C "${directory}" checkout -q --detach FETCH_HEAD
    done
}

build_project() {
    cd "${lean_directory}"
    # Re-running `cache get` would rewrite .olean files that running REPLs have memory-mapped.
    if lake build --no-build Mathlib repl >/dev/null 2>&1; then
        return
    fi
    lake exe cache get || echo "Mathlib cache unavailable; building Mathlib from source." >&2
    LEAN_NUM_THREADS="${LEAN_SEARCH_CPU_COUNT}" lake build Mathlib repl
}

smoke_test() {
    cd "${lean_directory}"
    local response
    response="$(printf '{"cmd": "import Mathlib\\nexample : (2 : ℕ) + 2 = 4 := by norm_num"}\n\n' \
        | lake env stdbuf -oL .lake/packages/REPL/.lake/build/bin/repl)"
    if [[ "${response}" != *'"env": 0'* || "${response}" == *'"severity": "error"'* ]]; then
        echo "REPL smoke test failed: ${response}" >&2
        exit 1
    fi
    echo "REPL smoke test passed."
}

install_elan
install_toolchain
fetch_packages
build_project
smoke_test
echo "Lean $(cd "${lean_directory}" && lean --version)"
