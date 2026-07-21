#!/usr/bin/env bash
# Monthly development-environment maintenance.

set -u

echo "=== [$(date)] Monthly dev-env maintenance ==="

if ! brew list --pinned 2>/dev/null | grep -q "python@3.11"; then
  echo "ERROR: python@3.11 is NOT pinned. Aborting brew upgrade."
  echo "Re-pin with: brew pin python@3.11"
  exit 1
fi

brew update 2>&1 | tail -3
brew upgrade 2>&1 | tail -15

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.11 || true)}"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: python3.11 not found"
  exit 1
fi
PYV=$("$PYTHON_BIN" --version 2>&1)
echo "python3.11 after upgrade: $PYV"
echo "$PYV" | grep -q "3.11" || exit 1

brew cleanup 2>&1 | tail -3
command -v bun >/dev/null 2>&1 && bun pm cache gc 2>&1 | tail -3 || true
command -v uv >/dev/null 2>&1 && uv cache clean 2>&1 | tail -3 || true

echo "=== Monthly maintenance complete ==="
