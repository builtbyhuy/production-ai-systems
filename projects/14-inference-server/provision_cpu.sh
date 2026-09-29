#!/bin/sh
# Reproduce the recorded Python 3.12 CPU package versions in a new isolated environment.
# This explicit provisioning command downloads pinned dependencies; the demo never installs them.
# The vLLM wheel is SHA256-pinned. Other wheels are version-pinned, not fully hash-locked.
set -eu
p14_project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
p14_environment=${1:-"$p14_project_dir/.venv"}
if [ -e "$p14_environment" ]; then
  echo "Refusing to replace an existing environment: $p14_environment" >&2
  exit 2
fi
uv venv --python 3.12 "$p14_environment"
uv pip sync --python "$p14_environment/bin/python" --index-strategy unsafe-best-match \
  "$p14_project_dir/runtime-cpu.lock.txt"
uv pip check --python "$p14_environment/bin/python"
printf 'Set PAIS_VLLM_PYTHON=%s/bin/python to use this runtime.\n' "$p14_environment"
