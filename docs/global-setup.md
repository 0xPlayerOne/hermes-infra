# Global Hermes Integration

This repository is the source of truth for Hermes infrastructure implementations.

## Repository-owned

- Code indexing: `code-index/indexer.py`, `.venv`, Chroma state under the configured `CHROMA_DIR`
- Embeddings: `hermes-infra tei` (Rust)
- Live indexing: `hermes-infra code-index-watch` (Rust)
- Hindsight service: `hermes-infra hindsight` (Rust)
- Command safety gate: `scripts/guardian.sh`
- MTPLX context synchronization: `hermes-infra mtplx-context-sync` (Rust)
- Second-brain sync and maintenance: `second-brain/scripts/`
- Cron prompt templates: `cron/`
- launchd templates: `launchd/`
- Hermes gateway launchd template: `launchd/ai.hermes.gateway.plist.example`

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

Python dependencies are intentionally split because ChromaDB 0.5.23 and Hindsight 0.8.4 require incompatible `tokenizers` versions:

- `.venv`: code index and second-brain workflows
- `.hindsight-venv`: Hindsight API only
