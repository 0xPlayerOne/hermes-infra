# Global Hermes Integration

This repository is the source of truth for Hermes infrastructure implementations.

## Repository-owned

- Code indexing: `code-index/indexer.py`, `.venv`, Chroma state under the configured `CHROMA_DIR`
- Embeddings: `scripts/tei-launch.sh`
- Live indexing: `scripts/code-index-watch.sh`
- Hindsight service: `scripts/hindsight-launch.sh`
- Command safety gate: `scripts/guardian.sh`
- MTPLX context synchronization: `scripts/mtplx-context-sync.py`
- Second-brain sync and maintenance: `second-brain/scripts/`
- Cron prompt templates: `cron/`
- launchd templates: `launchd/`

Global Hermes paths are compatibility links or runtime state only:

- `~/.hermes/scripts/` links to `scripts/`
- `~/.hermes/code-index/indexer.py` links to `code-index/indexer.py`
- `~/Developer/second-brain/System/Hermes/*.py` links to `second-brain/scripts/`
- `~/.hermes/.env` holds machine-local settings and secrets
- `~/.hermes/code-index/` and `~/.hermes/hindsight/` hold runtime state
- `~/.mtplx/` and `~/Library/Application Support/MTPLX/` hold MTPLX model/settings state

## Verification

```bash
set -a; source .env; set +a
"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/code-index/indexer.py" --status
curl -fsS http://127.0.0.1:6999/health
curl -fsS http://127.0.0.1:9177/health
```

Do not edit implementation files in `~/.hermes` or the second-brain vault. Update this repository and reload the affected launchd service.
