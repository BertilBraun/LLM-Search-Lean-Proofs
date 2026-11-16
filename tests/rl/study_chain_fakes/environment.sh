# The stand-in for deployment/environment.sh: the workspace and the node's CPU lists under the test's directory.
export LEAN_SEARCH_RUNS="${FAKE_WORKSPACE}/runs"
export LEAN_SEARCH_DATA="${FAKE_WORKSPACE}/data"
export LEAN_SEARCH_CHECKPOINTS="${FAKE_WORKSPACE}/checkpoints"
export BACKGROUND_CPU_LIST=48-95,144-191
export TRAINING_CPU_LIST=0-47,96-143
if [[ -n "${FAKE_BACKGROUND_CPUS:-}" ]]; then
    export BACKGROUND_CPUS="${FAKE_BACKGROUND_CPUS}"
fi
export PATH="${FAKE_BIN}:${PATH}"
mkdir -p "${LEAN_SEARCH_RUNS}" "${LEAN_SEARCH_DATA}" "${LEAN_SEARCH_CHECKPOINTS}"
