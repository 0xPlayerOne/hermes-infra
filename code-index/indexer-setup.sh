#!/usr/bin/env bash
set -euo pipefail

# indexer-setup.sh — bootstrap the code-indexer Python environment.
# Creates a venv at $CODE_INDEX_VENV (or this repo's .venv) and installs dependencies.
# Safe to re-run: skips venv creation if it already exists.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${CODE_INDEX_VENV:-$REPO_ROOT/.venv}"

echo "==> code-index venv setup"
echo "    venv: $VENV_DIR"

if [ -d "$VENV_DIR" ]; then
    echo "    venv already exists — skipping creation"
else
    echo "    creating venv..."
    python3 -m venv "$VENV_DIR"
fi

echo "    activating venv + installing chromadb..."
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install "chromadb==0.5.23" pdfplumber

echo "==> done. activate with: source $VENV_DIR/bin/activate"
