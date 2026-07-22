# Code Indexer

**Schedule:** Daily at 05:30

**Prompt:**

Load the global and repo environments with `set -a; source "$HOME/.hermes/.env"; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/code-index/indexer.py" --index`. Report a brief summary: total files indexed, repos added/removed, and errors. The indexer owns TEI health recovery.
