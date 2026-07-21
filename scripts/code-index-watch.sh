#!/bin/bash
# code-index-watch.sh — real-time incremental code indexing via Watchman.
# Watches $DEV_ROOT (or ~/code) for file changes, debounces 60s, runs indexer.py --index.
# The indexer is hash-based incremental (only changed files re-embed), so each
# run is fast (seconds, not minutes) once the initial index exists.

set -u
REPO="${HERMES_INFRA_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${HERMES_INFRA_ENV_FILE:-$REPO/.env}"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi
WATCH_ROOT="${DEV_ROOT:-$HOME/code}"
SCRIPT_DIR="$REPO/code-index"
VENV="${CODE_INDEX_VENV:-$REPO/.venv}/bin/activate"
WATCHMAN="${WATCHMAN_BIN:-$(command -v watchman || true)}"
if [ -z "$WATCHMAN" ]; then
    for candidate in /opt/homebrew/bin/watchman /usr/local/bin/watchman; do
        if [ -x "$candidate" ]; then
            WATCHMAN="$candidate"
            break
        fi
    done
fi
LOG="$REPO/logs/code-index-watch.log"

mkdir -p "$(dirname "$LOG")"
BUSY_FILE="${TMPDIR:-/tmp}/hermes-code-index-busy"
cleanup() { rm -f "$BUSY_FILE"; }
trap cleanup EXIT INT TERM
if [ -z "$WATCHMAN" ]; then
    echo "[$(date)] ERROR: watchman not found" >> "$LOG"
    exit 127
fi
echo "[$(date)] code-index-watcher starting (watching $WATCH_ROOT)" >> "$LOG"

# Ensure TEI (embeddings backend) is up (indexer hard-fails if not)
if ! curl -s --max-time 3 http://localhost:6999/health >/dev/null 2>&1; then
    echo "[$(date)] TEI down — starting it" >> "$LOG"
    launchctl load ~/Library/LaunchAgents/com.hermes.tei.plist 2>/dev/null
    sleep 45  # TEI warms up ~42s on Metal
fi

# Watchman: watch the root, trigger on any file change (debounced 60000ms)
"$WATCHMAN" watch "$WATCH_ROOT" >> "$LOG" 2>&1

# Subscribe to changes. Watchman sends JSON events; we debounce.
"$WATCHMAN" subscribe "$WATCH_ROOT" hermes-code-index '{"fields":["name","size","mtime_ms"]}' 2>>"$LOG" | while read -r line; do
    # Only act on "subscription" events (not watchman ack/state)
    echo "$line" | grep -q '"subscribe"' || continue
    # Debounce: wait 60s of quiet before indexing
    echo "[$(date)] change detected — debouncing 60s" >> "$LOG"
    sleep 60
    # Skip if another run started during debounce (simple guard)
    if [ -f "$BUSY_FILE" ]; then
        echo "[$(date)] already running, skip" >> "$LOG"
        continue
    fi
    (set -o noclobber; : > "$BUSY_FILE") 2>/dev/null || continue
    echo "[$(date)] running indexer --index" >> "$LOG"
    source "$VENV"
    cd "$SCRIPT_DIR"
    python indexer.py --index >> "$LOG" 2>&1 || echo "[$(date)] indexer failed" >> "$LOG"
    rm -f "$BUSY_FILE"
    echo "[$(date)] indexer done" >> "$LOG"
done
