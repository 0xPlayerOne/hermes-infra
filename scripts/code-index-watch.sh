#!/bin/bash
# code-index-watch.sh — real-time incremental code indexing via Watchman.
# Watches ~/Developer for file changes, debounces 60s, runs indexer.py --index.
# The indexer is hash-based incremental (only changed files re-embed), so each
# run is fast (seconds, not minutes) once the initial index exists.

set -u
REPO="$HOME/Developer/hermes-infra"
WATCH_ROOT="$HOME/Developer"
SCRIPT_DIR="$REPO/code-index"
VENV="$HOME/.hermes/code-index-venv/bin/activate"
WATCHMAN="/opt/homebrew/bin/watchman"
LOG="$REPO/logs/code-index-watch.log"

mkdir -p "$(dirname "$LOG")"
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
    if [ -f /tmp/code-index-busy ]; then
        echo "[$(date)] already running, skip" >> "$LOG"
        continue
    fi
    touch /tmp/code-index-busy
    echo "[$(date)] running indexer --index" >> "$LOG"
    source "$VENV"
    cd "$SCRIPT_DIR"
    python indexer.py --index >> "$LOG" 2>&1
    rm -f /tmp/code-index-busy
    echo "[$(date)] indexer done" >> "$LOG"
done
