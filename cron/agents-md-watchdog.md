# AGENTS.md Watchdog

**Schedule:** Daily at 05:45

**Prompt:**

Run the AGENTS.md coverage watchdog to keep the `~/Developer` fleet from going agent-blind. Execute: `find ~/Developer -name AGENTS.md -not -path '*/node_modules/*' | head -50`. For each repo without AGENTS.md, report the gap. For each with one, confirm it has non-empty content (>50 chars). Do not write fixes unless asked.
