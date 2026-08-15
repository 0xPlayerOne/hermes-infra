# Global Hermes integration

This repository owns Hermes-specific guardrails, fleet maintenance, gateway supervision, MTPLX
context synchronization, and the Cortana retrieval integration.

## Repository-owned

- Cortana retrieval instructions: `skills/cortana/SKILL.md`
- Command safety gate: `scripts/guardian.sh`
- AGENTS.md fleet audit and standardization: `scripts/agents_md_watchdog.py` and related scripts
- MTPLX context synchronization: `hermes-infra mtplx-context-sync`
- Hermes gateway and MTPLX launchd templates: `launchd/`
- Non-ingestion Hermes cron prompt templates: `cron/`

## Cortana-owned

Cortana is the source of truth for knowledge connectors, code indexing, Qwen embeddings, the
canonical evidence store, hybrid retrieval, MCP, HTTP/UI access, backups, and sync scheduling.
Runtime state lives under `~/.config/cortana` and `~/.local/share/cortana`.

Global Hermes configuration should contain only:

- the installed `cortana` skill;
- a Cortana MCP entry using the installed binary and absolute config path; and
- no TEI, Chroma, code-index, second-brain, or Hindsight launch job.

See [`cortana-integration.md`](cortana-integration.md) for the exact boundary and verification.

## Verification

```bash
cortana doctor
cortana service status
hermes mcp list
curl -fsS http://127.0.0.1:7331/readyz
"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/scripts/install_launchd.py" --check
```

Use `install_launchd.py --install` only after reviewing rendered changes. It writes machine-local
plists under `$HERMES_LAUNCH_AGENTS_DIR` and bootstraps them with launchd.
