# Weekly Knowledge Synthesis

**Schedule:** Sunday at 23:00

**Prompt:**

Run the weekly knowledge synthesis to make the agent GROW over time. Activate the configured code-index virtualenv and run: `cd "$SECOND_BRAIN_DIR/System/Hermes" && python3 synthesize.py` — this extracts decision/preference language from recent USER messages in the Hermes session store, deduplicates, and writes new durable facts into MEMORY.md + USER.md (the always-injected layer) AND queues them to Hindsight for conversational recall. This closes the learning loop: conversations -> durable memory -> faster future context. Report how many facts were synthesized. Runs Sunday nights.
