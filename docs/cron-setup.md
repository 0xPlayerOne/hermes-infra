# Cron Setup — Hermes Automated Jobs

Hermes Agent runs scheduled jobs via its built-in cron scheduler. Jobs are defined
in `$HOME/.hermes/cron/jobs.json`. Each job has a name, prompt, schedule (cron expression),
and optional delivery target (local or Discord channel).

## Prerequisites

- Hermes Agent installed and configured
- Hermes daemon running (`hermes daemon start`)

## Job Listing

| Job | Schedule | Description |
|-----|----------|-------------|
| Weekly Guardian Audit Review | Sunday 22:00 | Reviews agent safety logs for anomalies |
| Daily Standup | Configure per profile | Profile-specific standup → `$STANDUP_CHANNEL` |
| Hourly APFS Snapshot | Every hour | `tmutil snapshot` for backup safety |
| AGENTS.md Watchdog | Daily 05:45 | Audit AGENTS.md coverage across repos |

See `cron/` directory for full prompt text of each job.

## Adding a Job

```bash
hermes cron add \
  --name "My Job" \
  --schedule "0 9 * * *" \
  --prompt "Your prompt here" \
  --deliver local
```

## Managing Jobs

```bash
# List all jobs
hermes cron list

# Show job details
hermes cron show <job-id>

# Pause/resume a job
hermes cron pause <job-id>
hermes cron resume <job-id>

# Remove a job
hermes cron remove <job-id>

# Run a job immediately (ad-hoc)
hermes cron run <job-id>
```

## Delivery Targets

- `local` — output logged to the Hermes session store only
- `discord:<channel-id>` — output posted to the specified Discord channel

## Cron Expression Format

Standard 5-field cron:

```
┌─ minute (0-59)
│ ┌─ hour (0-23)
│ │ ┌─ day of month (1-31)
│ │ │ ┌─ month (1-12)
│ │ │ │ ┌─ day of week (0-6, Sunday=0)
│ │ │ │ │
* * * * *
```

Examples:
- `0 8 * * *` — every day at 08:00
- `0 23 * * 0` — every Sunday at 23:00
- `0 * * * *` — every hour on the hour

## Cortana boundary

Do not add knowledge ingestion, code indexing, embedding, or memory-provider jobs here. Cortana
owns those schedules through its service manager. The AGENTS.md watchdog reports Cortana health
but remains independent of embedding availability.

## Logs

Cron job output is logged to:
- Hermes session store (queryable via `hermes sessions`)
- `$HOME/.hermes/logs/` for Hermes gateway and agent-level logs
