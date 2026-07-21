# AGENTS.md Watchdog

**Schedule:** Daily at 05:45

**Prompt:**

Load the repo environment with `set -a; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/scripts/agents-md-watchdog"`. Report the coverage and any gaps. Do not write fixes unless asked.
