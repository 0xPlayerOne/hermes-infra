# Code Indexer

**Schedule:** Daily at 05:30

**Prompt:**

Load the repo environment with `set -a; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/code-index/indexer.py" --index`. Report a brief summary: total files indexed, repos added/removed, and errors. The indexer owns TEI health recovery.
