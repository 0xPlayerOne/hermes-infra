# AGENTS.md Watchdog

**Schedule:** Daily at 05:45

**Prompt:**

Load the global and repo environments with `set -a; source "$HOME/.hermes/.env"; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/scripts/agents_md_watchdog.py"`. Report the coverage and any gaps. Do not write fixes unless asked.
