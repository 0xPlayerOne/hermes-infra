#!/usr/bin/env bash
set -euo pipefail

# indexer-setup.sh — bootstrap the code-indexer Python environment.
# Creates a venv at ~/Developer/hermes-infra/code-index-venv and installs chromadb.
# Safe to re-run: skips venv creation if it already exists.

VENV_DIR="$HOME/Developer/hermes-infra/code-index-venv"

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
pip install --upgrade pip setuptools wheel
pip install chromadb

echo "==> done. activate with: source $VENV_DIR/bin/activate"
