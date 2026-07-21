#!/usr/bin/env bash
# sync-setup.sh — install dependencies for the second-brain sync scripts.
#
# Usage:
#   chmod +x sync-setup.sh && ./sync-setup.sh
#
# Dependencies derived from imports across all scripts:
#   chromadb    — vector store (sync.py, google_sync.py)
#   pdfplumber  — PDF text extraction (sync.py, google_sync.py)
#   urllib      — standard-library TEI client (sync.py, google_sync.py)
#
# System requirements (not installed by this script):
#   - gh CLI (for GitHub repo sync)
#   - curl (for Google API calls)
#   - TEI embedding server running locally
#   - macOS: osascript (for Apple Notes sync)

set -euo pipefail

echo "==> Installing second-brain sync dependencies..."

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_DIR="${HERMES_INFRA_VENV:-$REPO_ROOT/.venv}"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "ERROR: repo virtualenv not found at $VENV_DIR"
    echo "Run: $REPO_ROOT/code-index/indexer-setup.sh"
    exit 1
fi

"$VENV_DIR/bin/python" -m pip install \
    "chromadb==0.5.23" \
    pdfplumber

echo ""
echo "==> Dependencies installed."
echo ""
echo "==> Next steps:"
echo "  1. Set up Google OAuth credentials:"
echo "     - Place your OAuth client JSON at ~/.hermes/google-oauth.keys.json"
echo "     - Run: python3 google_sync.py --auth <account>"
echo "  2. Ensure gh CLI is authenticated for GitHub sync"
echo "  3. Start TEI on :6999"
echo "  4. Run the sync: python3 sync.py"
