#!/usr/bin/env -S /Users/amf/.hermes/hermes-agent/venv/bin/python3
"""
Update all cron prompts with rebasing instructions + YOLO mode.
"""

import json, sys, re

JOBS_FILE = "/Users/amf/.hermes/profiles/intern/cron/jobs.json"

with open(JOBS_FILE) as f:
    data = json.load(f)

jobs = data["jobs"] if isinstance(data, dict) and "jobs" in data else data

# --- YOLO MODE BLOCK (appended to every repo-agent prompt) ---
YOLO_REBASING = """
## YOLO Mode — NO ASKING, NO CONFIRMATIONS
- You are in YOLO mode. If you find an issue, FIX IT. Period. Do not report it and wait. Do not ask for permission.
- If you need to rebase, rebase. If you need to merge, merge. If you need to fix code, fix code. Just do it.

## Rebase Discipline (MANDATORY before any work)
1. `git fetch origin && git checkout staging && git pull`
2. Check if staging is behind main: `git log origin/main..origin/staging` (shows what staging HAS that main doesn't) AND `git log origin/staging..origin/main` (shows what main HAS that staging doesn't)
3. If staging is BEHIND main: `git rebase origin/main` then `git push --force-with-lease origin staging`
4. For each open PR targeting staging: check if it needs rebase. If so: `gh pr checkout <N>` → `git rebase origin/staging` → `git push --force-with-lease`
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

    # Add YOLO + rebasing block
    prompt += YOLO_REBASING

    # Type-specific modifications
    if base in UPDATES:
        upd = UPDATES[base]
        old = upd.get("old_section")
        new = upd.get("new_strategy")
        if old and new and old in prompt:
            prompt = prompt.replace(old, new, 1)
        if upd.get("remove_sop_start") and upd["remove_sop_start"] in prompt:
            prompt = prompt.replace(upd["remove_sop_start"], upd["replace_sop_top"], 1)

    if prompt != original:
        job["prompt"] = prompt
        count += 1
        print(f"  ✓ {name}")

print(f"\nUpdated {count} jobs")

with open(JOBS_FILE, "w") as f:
    json.dump(data, f, indent=2)

print("Written to jobs.json")
