#!/usr/bin/env python3
"""Update all cron prompts with rebasing instructions + YOLO mode."""

import json
import sys
from pathlib import Path

# --- Default jobs file ---
DEFAULT_JOBS_FILE = Path.home() / ".hermes/profiles/intern/cron/jobs.json"

# --- YOLO MODE BLOCK (appended to every repo-agent prompt) ---
YOLO_REBASING = """\
## YOLO Mode — NO ASKING, NO CONFIRMATIONS
- You are in YOLO mode. If you find an issue, FIX IT. Period. Do not report it and wait. Do not ask for permission.
- If you need to rebase, rebase. If you need to merge, merge. If you need to fix code, fix code. Just do it.

## Rebase Discipline (MANDATORY before any work)
1. `git fetch origin && git checkout staging && git pull`
2. Check if staging is behind main: `git log origin/main..origin/staging` (shows what staging HAS that main doesn't) AND `git log origin/staging..origin/main` (shows what main HAS that staging doesn't)
3. If staging is BEHIND main: `git rebase origin/main` then `git push --force-with-lease origin staging`
4. For each open PR targeting staging: check if it needs rebase. If so: `gh pr checkout <N>` -> `git rebase origin/staging` -> `git push --force-with-lease`
"""

# --- Modifications per type ---
UPDATES = {
    "Weekly Maint": {
        "old_section": "## Branch Strategy (MANDATORY)",
        "new_strategy": """## Branch Strategy (MANDATORY)
- ALWAYS branch FROM `staging` and PR INTO `staging`.
- NEVER push to main or staging directly (exception: bug-fix push into an open PR's branch).
- Always use `gh pr merge --auto --squash` after checks pass.
- Abandon after 3 failed fix attempts.
- Read changelogs for every major bump.
- BEFORE starting: rebase staging on main (see YOLO Mode below).""",
        "append": None,
        "remove_sop_start": "1. `git fetch origin && git checkout staging && git pull`",
        "replace_sop_top": "1. `git fetch origin && git checkout staging && git pull`  # already done by rebase step above",
    },
    "Daily Review": {
        "old_section": "## SOP",
        "new_strategy": """## SOP

0. **REBASE FIRST: Before reviewing anything** — see YOLO Mode below. Ensure staging is up to date with main, then rebase open PR branches on staging.""",
        "append": None,
        "remove_sop_start": None,
        "replace_sop_top": None,
    },
    "Daily Sentinel": {
        "old_section": "TASK 1",
        "new_strategy": """TASK 0 — Rebase staging on main first (see YOLO Mode below), then:

TASK 1 — Catch drift: run the full test suite. If HEAD changed since last check OR tests fail, flag it immediately. Check for API downtime (if the project has health endpoints, curl them — landing page at port 3000, store at 3001, blog at 3002, admin at 3003).""",
        "append": None,
        "remove_sop_start": None,
        "replace_sop_top": None,
    },
    "Weekly Gate": {
        "old_section": "## SOP",
        "new_strategy": """## YOLO Mode — see below.

## SOP

0. **REBASE FIRST:** Ensure staging is up to date with main (see YOLO Mode below).""",
        "append": None,
        "remove_sop_start": None,
        "replace_sop_top": None,
    },
}


def update_jobs(jobs, *, out=None):
    """Update a list of job dicts in place, returning the count of updated jobs.

    If *out* is provided, the updated data is written to that file path.
    """
    count = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = job.get("name", "")
        base = name.rsplit(" - ", 1)[0] if " - " in name else name

        if base == "Daily Standup":
            continue  # Leave standup alone

        prompt = job.get("prompt", "")
        original = prompt

        # Type-specific modifications FIRST (before YOLO append)
        if base in UPDATES:
            upd = UPDATES[base]
            old = upd.get("old_section")
            new = upd.get("new_strategy")
            if old and new and old in prompt and new not in prompt:
                prompt = prompt.replace(old, new, 1)
            # Only apply SOP line replacement in the core prompt (before YOLO)
            if upd.get("remove_sop_start") and upd.get("replace_sop_top"):
                yolo_marker = "## YOLO Mode"
                core = prompt[: prompt.find(yolo_marker)] if yolo_marker in prompt else prompt
                if upd["remove_sop_start"] in core and upd["replace_sop_top"] not in core:
                    prompt = prompt.replace(upd["remove_sop_start"], upd["replace_sop_top"], 1)

        # Add YOLO + rebasing block once (skip if already appended)
        if YOLO_REBASING.strip() not in prompt:
            prompt += YOLO_REBASING

        if prompt != original:
            job["prompt"] = prompt
            count += 1
            print(f"  ✓ {name}")

    if out is not None:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        print(f"Written to {out}")

    return count


def main():
    jobs_file = (
        Path(sys.argv[sys.argv.index("--jobs-file") + 1])
        if "--jobs-file" in sys.argv
        else DEFAULT_JOBS_FILE
    )

    if not jobs_file.exists():
        print(f"Jobs file not found: {jobs_file}")
        sys.exit(1)

    with open(jobs_file, encoding="utf-8") as f:
        data = json.load(f)

    jobs = data["jobs"] if isinstance(data, dict) and "jobs" in data else data
    count = update_jobs(jobs, out=jobs_file)
    print(f"\nUpdated {count} jobs")


if __name__ == "__main__":
    main()
