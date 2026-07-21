# Weekly Knowledge Synthesis

**Schedule:** Sunday at 23:00

**Prompt:**

Run the weekly knowledge synthesis to make the agent GROW over time. Load the repo environment with `set -a; source "$HERMES_INFRA_DIR/.env"; set +a`, then run `"$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/second-brain/scripts/synthesize.py"` — this extracts decision/preference language from recent USER messages in the Hermes session store, deduplicates, and writes new durable facts into MEMORY.md + USER.md (the always-injected layer) AND queues them to Hindsight for conversational recall. This closes the learning loop: conversations -> durable memory -> faster future context. Report how many facts were synthesized. Runs Sunday nights.
