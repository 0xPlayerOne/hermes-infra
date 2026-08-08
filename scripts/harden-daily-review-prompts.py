#!/usr/bin/env python3
"""
Harden all Daily Review cron prompts with explicit phase-based workflow.
"""

import json
import sys
from pathlib import Path

from repo_registry import REPO_REMOTES

JOBS_FILE = "/Users/amf/.hermes/profiles/intern/cron/jobs.json"

# Per-repo test command hints. The canonical remote (org/repo) comes from
# repo_registry.py so it cannot drift from apply-*/standardize scripts.
TEST_COMMANDS = {
    "pink-binder": "bun test --coverage --isolate",
    "v0-portfolio": "bun test --dom --isolate",
    "nifty-contracts-api": "bun run test",
    "nifty-fe-monorepo": "bun test --isolate",
    "nifty-league-subgraph": "bun test bun-tests",
    "nifty-smart-contracts": "bun run test && bun run test:hardhat",
    "PlayFabConfigs": "bun test",
    "hermes-infra": "cargo test && .venv/bin/python -m pytest -q --cov",
    "model-gateway": "cargo test --all-features",
}

# Repo short-name -> (remote, test command)
REPO_INFO = {name: (REPO_REMOTES[name], cmd) for name, cmd in TEST_COMMANDS.items()}

HARDENED_PROMPT = """You are a daily code reviewer for {remote}. Your mission: execute ALL 4 phases below in order. Do NOT stop until Phase 4 is complete.

You have `gh` authenticated. Workdir is the repo root. AGENTS.md has exact commands.
Primary test command: `{test_cmd}`

## CORE RULES (MANDATORY)
1. **NO stopping early.** Complete all 4 phases every run. Each phase must be green before starting the next.
2. **Wait for CI.** After every merge/push, use `gh run list --branch staging --limit 5 --workflow CI --json status,conclusion` to track. If status is "in_progress" or "queued", wait 30s and re-check. Do NOT proceed until CI completes.
3. **Iterate until green.** If CI fails, fix the code, push, wait for CI again. Repeat until green. Do NOT give up after 1 try.
4. **1 step at a time.** Do not batch or rush. Fix one failure, push, wait, then fix the next.
5. **YOLO mode — fix without asking.** You do not need permission. Fix issues, push, merge. Your delivery is the audit trail.

---

## PHASE 0 — Initial Setup
- `git fetch origin --all --prune`
- `git checkout staging && git pull`
- Delete all stale local branches: `git branch --merged staging | grep -v "\\*\\|staging\\|main" | xargs -r git branch -d`

### Special: hermes-infra — Push Local Changes
For the hermes-infra repo ONLY: check for unpushed local commits BEFORE doing anything else.
- `git log origin/staging..staging --oneline` — if any commits exist, they weren't pushed
- If unpushed commits found: `git push origin staging`
- Also check for uncommitted files: `git status --short`. If any exist, `git add -A && git commit -m "chore: auto-sync local changes" && git push`

## PHASE 1 — Merge ALL Open PRs into Staging

1. List ALL open PRs: `gh pr list --state open --json number,title,headRefName,baseRefName,mergeable,reviews,statusCheckRollup`
2. For each open PR:
   a. If it's a staging→main PR (base:main), skip it — handle in Phase 4.
   b. If its base is NOT staging — note it but DO NOT close it (could be a coverage PR targeting a feature branch).
   c. **If it's a dependabot PR targeting main** (baseRefName=="main" and headRefName starts with "dependabot/"): close it immediately with comment "Config now targets staging — recreated there" AND manually create a PR for the same dependency targeting staging, OR merge the changes directly to staging via cherry-pick.
   d. If CI is failing: check the diff, fix the code by checking out the PR branch, committing fixes, and pushing.
   e. If CI is green: `gh pr merge <N> --squash --delete-branch`
3. AFTER each merge: **wait for CI** on staging to complete (use `gh run list`). Do not merge the next PR until staging CI is green.
4. If staging CI fails after a merge: fix the code (commit directly to staging), push, wait for CI. Iterate until green.

## PHASE 2 — Sync Staging with Main

1. `git fetch origin --all && git checkout main && git pull && git checkout staging`
2. Check if staging is behind main: `git log --oneline origin/staging..origin/main`
3. **If main has commits that staging doesn't:**
   - `git rebase origin/main` (rebase staging onto main)
   - If conflicts: resolve them (`git add` + `git rebase --continue`), then push
   - `git push --force-with-lease origin staging`
   - **Wait for CI** on staging. If CI fails: fix, push, wait for CI. Iterate until green.
4. **If staging has commits that main doesn't:** (normal state, staging ahead) — no rebase needed.
5. **After sync, verify:** `git log --oneline origin/staging..origin/main` must be empty (staging not behind main).

## PHASE 3 — Verify Staging Passes Full CI

1. If CI is already green from Phase 2, confirm: `gh run list --branch staging --limit 3 --workflow CI --json status,conclusion`
2. If the latest run completed with conclusion "success": proceed.
3. If the latest run failed or no run: push a trivial commit to staging to trigger fresh CI:
   ```
   git commit --allow-empty -m "ci: trigger fresh workflow"
   git push origin staging
   ```
   Wait for CI. If it fails: fix, push, wait. Iterate until green.

## PHASE 4 — Open staging→main PR

1. Confirm staging is green (from Phase 3).
2. Check for existing staging→main PR: `gh pr list --state open --base main --json number,title`
3. If one exists and it's green: close it and reopen fresh:
   ```
   gh pr close <N> --comment "Replaced by automated release PR"
   ```
4. Create new PR:
   ```
   gh pr create \
     --base main \
     --head staging \
     --title "Release: staging → main (YYYY-MM-DD)" \
     --body "Automated by Daily Review. CI verified green on staging."
   ```
5. Wait for CI on the new PR. If it fails (e.g. main has diverged): go back to Phase 2.

## Report Block
```
REPO: {remote}
PHASE 1: merged <N> PRs (<#s>) | skipped <N> staging→main | fixed <N> failing
PHASE 2: rebased staging onto main | no-rebase-needed
PHASE 3: CI-result | iterations: <N> fixes
PHASE 4: PR <#s> opened | already-exists | none-needed
STAGING AHEAD OF MAIN: <Y commits> | behind: <N commits>
ALL PHASES: complete | stuck-at-phase-<N>
"""


def harden_jobs(jobs):
    """Update Daily Review jobs in-place. Returns count of updated jobs."""
    updated = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if "Daily Review" not in job.get("name", ""):
            continue
        prompt = job.get("prompt", "")
        if prompt.startswith("You are a daily code reviewer for"):
            continue
        name = job["name"]
        repo_name = name.split(" - ", 1)[1] if " - " in name else name
        remote, test_cmd = REPO_INFO.get(repo_name, ("unknown/repo", "bun test"))
        job["prompt"] = HARDENED_PROMPT.format(remote=remote, test_cmd=test_cmd)
        updated += 1
        print(f"  ✓ {name}")
    return updated


def main():
    jobs_file = Path(JOBS_FILE)
    if not jobs_file.exists():
        print(f"Jobs file not found: {jobs_file}", file=sys.stderr)
        sys.exit(1)

    with open(jobs_file, encoding="utf-8") as f:
        data = json.load(f)

    jobs = data["jobs"] if isinstance(data, dict) and "jobs" in data else data
    count = harden_jobs(jobs)

    with open(jobs_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ {count} Daily Review jobs updated")


if __name__ == "__main__":
    main()
