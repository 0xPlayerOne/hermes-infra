# Weekly Guardian Audit Review

**Schedule:** Sunday at 22:00

**Prompt:**

Review the agent safety audit log for anomalies. Read `~/.hermes/guardian.log` and report: (1) any BLOCKED destructive commands (forbidden patterns, protected paths, empty-var traps), (2) any successful destructive commands that ran WITHOUT a snapshot (shouldn't happen — guardian snapshots before all deletes), (3) any unusual volume of commands. If anything looks like an agent went off-script (e.g. repeated blocked attempts, or deletes in protected paths), flag it prominently. This is the human-in-the-loop safety check — the gatekeeper logs everything, this job READS it. Keep the report concise. If the log is clean (only expected blocks, no anomalies), say so in one line.
