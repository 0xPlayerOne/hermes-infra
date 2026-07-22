# Hindsight Setup

The repository owns the Hindsight launcher and launchd template. Runtime state remains outside Git:

- Hindsight/PostgreSQL data: `$HERMES_HOME/hindsight`
- Hermes Hindsight settings: `$HERMES_HOME/hindsight/config.json`
- LLM credential: `HINDSIGHT_LLM_API_KEY` in `$HERMES_HOME/.env` or the configured secret env file
- Service logs: `$HERMES_INFRA_DIR/logs/hindsight-api.log`

The Rust launcher loads the repository `.env`, the global Hermes `.env`, the persisted Hindsight provider settings, and then replaces itself with the installed Hindsight API process. It uses local TEI for embeddings. The Hindsight LLM must be configured explicitly through one OpenAI-compatible endpoint; Hermes `model.default` and `fallback_providers` are not automatically inherited by the separate Hindsight process.

## Install

```bash
set -a; source .env; set +a
cargo build --release
./scripts/setup-python.sh
cp launchd/com.hermes.hindsight.plist.example "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist"
```

Replace `/path/to/hermes-infra` in the copied plist with the absolute repository path. Ensure `HINDSIGHT_LLM_API_KEY`, `HINDSIGHT_API_LLM_BASE_URL`, and `HINDSIGHT_API_LLM_MODEL` are configured in `$HERMES_HOME/.env` or `$HERMES_HOME/hindsight/config.json`, then reload:

```bash
launchctl unload "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist" 2>/dev/null || true
launchctl load "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist"
```

Do not commit Hindsight data, API keys, or generated launchd plists.
