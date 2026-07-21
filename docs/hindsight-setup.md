# Hindsight Setup

The repository owns the Hindsight launcher and launchd template. Runtime state remains outside Git:

- Hindsight/PostgreSQL data: `$HERMES_HOME/hindsight`
- Hermes Hindsight settings: `$HERMES_HOME/hindsight/config.json`
- LLM credential: `HINDSIGHT_LLM_API_KEY` in `$HERMES_HOME/.env`
- Service logs: `$HERMES_INFRA_DIR/logs/hindsight-api.log`

The launcher loads the repository `.env`, the global Hermes `.env`, and then starts the installed Hindsight binary. It configures Hindsight's LLM through the OpenAI-compatible OpenRouter endpoint and uses local TEI for embeddings.

## Install

```bash
set -a; source .env; set +a
cp launchd/com.hermes.hindsight.plist.example "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist"
```

Replace `/path/to/hermes-infra` in the copied plist with the absolute repository path. Ensure `HINDSIGHT_LLM_API_KEY` is set in `$HERMES_HOME/.env`, then reload:

```bash
launchctl unload "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist" 2>/dev/null || true
launchctl load "$HERMES_LAUNCH_AGENTS_DIR/com.hermes.hindsight.plist"
```

Do not commit Hindsight data, API keys, or generated launchd plists.
