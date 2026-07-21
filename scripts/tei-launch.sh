#!/bin/bash
# Safe TEI launcher with memory monitoring
# Kills TEI if RSS exceeds MEMORY_LIMIT_BYTES

set -euo pipefail

TEI_BIN="/opt/homebrew/bin/text-embeddings-router"
MODEL="Qwen/Qwen3-Embedding-0.6B"
PORT=6999
# 2GB memory limit (conservative for M-series with 64GB total)
MEMORY_LIMIT_BYTES=$((2 * 1024 * 1024 * 1024))
MONITOR_INTERVAL=10
LOG="$HOME/Developer/hermes-infra/logs/tei.log"

# Low batch limits to prevent memory spikes
MAX_BATCH_TOKENS=512
MAX_BATCH_REQUESTS=16
MAX_CONCURRENT_REQUESTS=16

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Find TEI PID by port
find_tei_pid() {
    lsof -nP -iTCP:$PORT -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | head -1
}

# Check if TEI RSS exceeds limit
check_memory() {
    local pid
    pid=$(find_tei_pid)
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
        local rss
        rss=$(ps -p "$pid" -o rss= 2>/dev/null | tr -d ' ')
        if [ -n "$rss" ] && [ "$rss" -gt "$((MEMORY_LIMIT_BYTES / 1024))" ]; then
            log "MEMORY LIMIT EXCEEDED: PID $pid RSS=${rss}KB > limit=$((MEMORY_LIMIT_BYTES / 1024))KB"
            log "Killing TEI (PID $pid)..."
            kill -9 "$pid" 2>/dev/null || true
            return 1
        fi
    fi
    return 0
}

# Cleanup
cleanup() {
    log "Shutdown signal received, cleaning up..."
    local pid
    pid=$(find_tei_pid)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    log "TEI stopped cleanly."
    exit 0
}
trap cleanup SIGTERM SIGINT SIGHUP

log "Starting TEI with memory protection (limit=${MEMORY_LIMIT_BYTES} bytes)"

# Start TEI in background
"$TEI_BIN" \
    --model-id "$MODEL" \
    --dtype float16 \
    --port "$PORT" \
    --max-batch-tokens "$MAX_BATCH_TOKENS" \
    --max-batch-requests "$MAX_BATCH_REQUESTS" \
    --max-concurrent-requests "$MAX_CONCURRENT_REQUESTS" &
TEI_PID=$!

log "TEI started as PID $TEI_PID"

# Wait for TEI to be ready
for i in $(seq 1 60); do
    if curl -sS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        log "TEI healthy after ${i}s"
        break
    fi
    sleep 1
done

# Monitor loop
while kill -0 "$TEI_PID" 2>/dev/null; do
    if ! check_memory; then
        log "TEI killed due to memory limit. Exiting."
        exit 1
    fi
    sleep "$MONITOR_INTERVAL"
done

wait "$TEI_PID" 2>/dev/null
EXIT_CODE=$?
log "TEI exited with code $EXIT_CODE"
exit "$EXIT_CODE"
