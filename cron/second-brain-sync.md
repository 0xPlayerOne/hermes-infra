# Second-Brain Sync

**Schedule:** Daily at 04:40

**Prompt:**

Load the global and repo environments with `set -a; source "$HOME/.hermes/.env"; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/second-brain/scripts/sync.py"`.

SAFETY: Route ALL downstream messages through the Hermes agent after the sync. Read the vault state, reconcile with GitHub, update indices, and report diffs/changes. Do not hallucinate changes.
