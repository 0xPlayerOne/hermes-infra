#!/usr/bin/env bash
# Create the Python environment for Hermes maintenance and tests.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${HERMES_INFRA_VENV:-$REPO_ROOT/.venv}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required" >&2
    exit 127
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    uv venv --python 3.11 "$VENV_DIR"
fi

uv pip install --python "$VENV_DIR/bin/python" --requirement "$REPO_ROOT/requirements-dev.txt"
echo "Python environment ready: $VENV_DIR"
