#!/usr/bin/env bash
# sync-setup.sh — install dependencies for the second-brain sync scripts.
#
# Usage:
#   chmod +x sync-setup.sh && ./sync-setup.sh
#
# Dependencies derived from imports across all scripts:
#   chromadb    — vector store (sync.py, google_sync.py)
#   pdfplumber  — PDF text extraction (sync.py, google_sync.py)
#   ollama      — embedding model client (sync.py, google_sync.py)
#
# System requirements (not installed by this script):
#   - gh CLI (for GitHub repo sync)
#   - curl (for Google API calls)
#   - TEI or Ollama embedding server running locally
#   - macOS: osascript (for Apple Notes sync)

set -euo pipefail

echo "==> Installing second-brain sync dependencies..."

# Ensure pip is available
if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
    echo "ERROR: pip not found. Install Python 3 and pip first."
    exit 1
fi

PIP="$(command -v pip3 || command -v pip)"

"$PIP" install \
    chromadb \
    pdfplumber \
    ollama

echo ""
echo "==> Dependencies installed."
echo ""
echo "==> Next steps:"
echo "  1. Set up Google OAuth credentials:"
echo "     - Place your OAuth client JSON at ~/.hermes/google-oauth.keys.json"
echo "     - Run: python3 google_sync.py --auth <account>"
echo "  2. Ensure gh CLI is authenticated for GitHub sync"
echo "  3. Start your embedding backend (TEI on :6999 or Ollama on :11434)"
echo "  4. Run the sync: python3 sync.py"
