#!/usr/bin/env bash
# Start the local Hindsight API using repository-owned service configuration.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENV_FILE="${HERMES_INFRA_ENV_FILE:-$REPO_ROOT/.env}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

if [ -f "$HERMES_HOME/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$HERMES_HOME/.env"
    set +a
fi

SECRET_ENV_FILE="${HINDSIGHT_SECRET_ENV_FILE:-$HERMES_HOME/hindsight.env}"
HINDSIGHT_BIN="${HINDSIGHT_BIN:-$HERMES_HOME/hermes-agent/venv/bin/hindsight-api}"

if [ -f "$SECRET_ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SECRET_ENV_FILE"
    set +a
fi

: "${HINDSIGHT_LLM_API_KEY:?Set HINDSIGHT_LLM_API_KEY in the global Hermes environment}"

export HINDSIGHT_API_HOST="${HINDSIGHT_API_HOST:-127.0.0.1}"
export HINDSIGHT_API_PORT="${HINDSIGHT_API_PORT:-9177}"
export HINDSIGHT_API_LOG_LEVEL="${HINDSIGHT_API_LOG_LEVEL:-info}"
export HINDSIGHT_API_LLM_PROVIDER="${HINDSIGHT_API_LLM_PROVIDER:-openai}"
export HINDSIGHT_API_LLM_API_KEY="$HINDSIGHT_LLM_API_KEY"
export HINDSIGHT_API_LLM_BASE_URL="${HINDSIGHT_API_LLM_BASE_URL:-https://openrouter.ai/api/v1}"
export HINDSIGHT_API_LLM_MODEL="${HINDSIGHT_API_LLM_MODEL:-openrouter/free}"
export HINDSIGHT_API_LLM_STRICT_SCHEMA="${HINDSIGHT_API_LLM_STRICT_SCHEMA:-false}"
export HINDSIGHT_API_EMBEDDINGS_PROVIDER="${HINDSIGHT_API_EMBEDDINGS_PROVIDER:-openai}"
export HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY="${HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY:-tei}"
TEI_URL="${TEI_EMBED_URL:-http://127.0.0.1:6999/v1/embeddings}"
export HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL="${HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL:-${TEI_URL%/embeddings}}"
export HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL="${HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL:-${EMBED_MODEL:-Qwen/Qwen3-Embedding-0.6B}}"
export HINDSIGHT_API_EMBEDDINGS_DIM="${HINDSIGHT_API_EMBEDDINGS_DIM:-1024}"
export HINDSIGHT_API_RERANKER_PROVIDER="${HINDSIGHT_API_RERANKER_PROVIDER:-rrf}"
export HINDSIGHT_PROFILE="${HINDSIGHT_PROFILE:-hermes}"

exec "$HINDSIGHT_BIN" --host "$HINDSIGHT_API_HOST" --port "$HINDSIGHT_API_PORT" --log-level "$HINDSIGHT_API_LOG_LEVEL"
