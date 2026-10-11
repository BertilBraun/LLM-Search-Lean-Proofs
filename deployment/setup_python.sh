#!/usr/bin/env bash
# Create or update the repository's .venv from uv.lock (Python 3.12, with the ml extra and the dev group).
#
#   deployment/on_node.sh deployment/setup_python.sh
#
# Idempotent: an up-to-date environment is left untouched. Packages come from the mirror recorded in uv.lock.

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_directory}/.."
source deployment/environment.sh

uv sync --locked --python 3.12 --extra ml

python - <<'EOF'
import torch
import vllm

print(f"torch {torch.__version__} (CUDA {torch.version.cuda}), vllm {vllm.__version__}")
print(f"GPUs: {[torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]}")
EOF
