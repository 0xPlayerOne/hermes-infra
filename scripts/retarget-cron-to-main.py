#!/usr/bin/env python3
"""Retarget Hermes cron prompts from the staging topology to direct-to-main.

Every managed repository is ``git_workflow: direct`` (see each repo's
``.github/code-foundry.yml``), and Code Foundry only enables its staging
reconciliation lane for ``git_workflow: staging-release``. The cron prompts
nevertheless instructed agents to prepare, promote, and release through a
``staging`` branch. That mismatch created stray ``staging`` branches and
opened "Release: staging -> main" PRs that no workflow backs.

Rather than find-and-replacing "staging" with "main" — which produces
incoherent instructions such as "Sync Main with Main" — this replaces whole
staging-shaped sections with direct-to-main equivalents, per job type.

Idempotent. Jobs are matched by base name (everything before " - <repo>") so
every managed repository is covered.

Usage:
    python3 scripts/retarget-cron-to-main.py [--jobs-file PATH] [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

from cron_io import DEFAULT_JOBS_FILE, load_jobs

# --------------------------------------------------------------------------
# Shared blocks
# --------------------------------------------------------------------------

REBASE_BLOCK = re.compile(
    r"^## Rebase Discipline \(MANDATORY before any work\).*?(?=^## |\Z)", re.S | re.M
)
REBASE_BLOCK_MAIN = """## Rebase Discipline (MANDATORY before any work)
1. `git fetch origin && git checkout main && git pull`
2. For each open PR targeting `main`: check whether it needs a rebase. If so:
   `gh pr checkout <N>` -> `git rebase origin/main` -> `git push --force-with-lease`
"""

# Daily Review: Phase 2 "sync staging with main" and Phase 4 "open staging PR"
# are pure staging-lane artifacts. On a direct repo there is nothing to sync
# and the PR that reaches main IS the release.
DAILY_REVIEW_PHASE_2 = re.compile(r"^## PHASE 2 — Sync .*?(?=^## PHASE 3)", re.S | re.M)
DAILY_REVIEW_PHASE_4 = re.compile(r"^## PHASE 4 — Open .*?(?=^## Report Block)", re.S | re.M)

DAILY_REVIEW_PHASE_2_MAIN = """## PHASE 2 — Rebase In-Flight Work on Main

1. `git fetch origin --all --prune`
2. For every open PR targeting `main`, check whether it is behind:
   `git log --oneline <pr-head>..origin/main`
3. **If a PR branch is behind main:** rebase it and force-push with lease:
   - `gh pr checkout <N>`
   - `git rebase origin/main`
   - resolve conflicts (`git add` + `git rebase --continue`) if any
   - `git push --force-with-lease`
   - **Wait for CI** on that PR. If CI fails: fix, push, wait. Iterate until green.
4. This repository merges directly to `main`, so there is no separate
   integration branch to reconcile: a PR that is level with main needs no work.

"""

# Daily Review phase 1 "merge into staging" framing.
DAILY_REVIEW_PHASE_1 = re.compile(r"^## PHASE 1 — Merge ALL Open PRs into Staging", re.M)
DAILY_REVIEW_PHASE_1_MAIN = "## PHASE 1 — Land All Open PRs on Main"

DAILY_REVIEW_PHASE_3 = re.compile(r"^## PHASE 3 — Verify Staging Passes Full CI", re.M)
DAILY_REVIEW_PHASE_3_MAIN = "## PHASE 3 — Verify Main Passes Full CI"

DAILY_REVIEW_INTRO = re.compile(
    r"Your mission: execute ALL 4 phases below in order\. Do NOT stop until Phase 4 is complete\.",
)
DAILY_REVIEW_INTRO_MAIN = (
    "Your mission: execute ALL 3 phases below in order. Do NOT stop until Phase 3 is complete."
)

# Phase 1 step (a): staging->main PRs do not exist on a direct repo.
PHASE1_A = re.compile(r"^   a\. If it's a .*PR \(base:main\), skip it — handle in Phase 4\.$", re.M)
PHASE1_A_MAIN = "   a. If its base is `main`, it is an ordinary change heading for release — treat it like any other PR."

# Phase 1 step (c): closing dependabot PRs and recreating them against staging.
PHASE1_C = re.compile(r"^   c\. \*\*If it's a dependabot PR targeting main\*\*.*$", re.M)
PHASE1_C_MAIN = "   c. Dependabot PRs already target `main` — merge them normally once CI is green."

# Report block: the staging-lane lines.
REPORT_STAGING_LINES = re.compile(r"^(PHASE 2: .*|PHASE 4: .*|STAGING AHEAD OF MAIN: .*)$", re.M)

# --------------------------------------------------------------------------
# Job-type specific rewrites
# --------------------------------------------------------------------------

WEEKLY_MERGE_TASKS = re.compile(
    r"^## Tasks\n.*?(?=^Do NOT spend time fixing CI failures)", re.S | re.M
)
WEEKLY_MERGE_TASKS_MAIN = """## Tasks
1. `git fetch origin && git checkout main && git pull`
2. List all open PRs targeting `main`
3. Merge EVERY open PR into `main` — merge all at once, do NOT wait for CI:
   - For PRs with auto-merge enabled, they'll merge on their own
   - For others: `gh pr merge --squash` (use `--auto` if needed)
4. Run dependency update: `bun update` (bun repos) or `cargo update` (Rust repos) to catch anything Dependabot might have missed
5. Commit: `git add -A && git commit -m 'chore(deps): weekly update' --no-verify`
6. `git push origin main --no-verify`
7. Output: which PRs were merged, whether bun/cargo update ran, and the resulting commit range.

"""

WEEKLY_RELEASE_TASKS = re.compile(
    r"^## Tasks\n.*?(?=^Do NOT run local tests before pulling CI errors)", re.S | re.M
)
WEEKLY_RELEASE_TASKS_MAIN = """## Tasks
1. `git fetch origin && git checkout main && git pull`
2. PULL CI AND DEPLOYMENT ERRORS FROM GITHUB:
   - `gh run list --branch main --limit 5 --status failure --json name,conclusion,url,databaseId`
   - `gh run view <failed_run_id> --log --job <failed_job>` (to get specific failure logs)
   - Check deployment status in GitHub Actions
   - Collect ALL error logs into one picture of what's broken
3. DIAGNOSE AND FIX: Based on the CI/deployment errors:
   - Fix breaking dependency changes (update imports, types, configs)
   - Fix test failures, type errors, lint issues
   - Fix deployment failures
   - If an upgrade is truly unrecoverable: revert that specific change, create a detailed GitHub issue
4. RUN THE FULL TEST SUITE LOCALLY: After fixing what you can from the CI errors:
   - Run tests, lint, type-check, build per AGENTS.md
   - If tests still fail -> iterate: fix -> re-run -> until green
   - Max 3 attempts per fix before fallback to revert+issue
5. Push fixes to `main` (via a PR if the branch is protected).
6. Output structured summary: CI errors found, fixes applied, issues created (if any), local test results, and the resulting commit SHA

"""

WEEKLY_MERGE_INTRO = re.compile(
    r"^You are the Weekly Merge agent for \{owner\}/\{name\}\..*$", re.M
)
WEEKLY_MERGE_INTRO_MAIN = (
    "You are the Weekly Merge agent for {owner}/{name}. This runs Monday at 4AM and lands "
    "the open PR queue on `main` before the Weekly Release agent at 5AM."
)
WEEKLY_RELEASE_INTRO = re.compile(
    r"^You are the Weekly Release agent for \{owner\}/\{name\}\..*$", re.M
)
WEEKLY_RELEASE_INTRO_MAIN = (
    "You are the Weekly Release agent for {owner}/{name}. This runs Monday at 5AM against "
    "a `main` branch that the Weekly Merge agent has just updated (and possibly broken)."
)

DAILY_IMPROVEMENT_TASKS = re.compile(r"^## Tasks\n.*?(?=^## YOLO Mode)", re.S | re.M)
DAILY_IMPROVEMENT_TASKS_MAIN = """## Tasks
1. `git fetch origin && git checkout main && git pull`
2. Scan the codebase for:
   - Code that needs refactoring (duplication, complexity, outdated patterns)
   - Dead code to remove (unused imports, functions, variables, exports, files)
   - Performance improvement opportunities (slow queries, N+1 issues, bundle size, render optimization)
3. For each finding:
   - Fix it directly on a feature branch
   - Open a PR **targeting `main`** with a clear description of the improvement
4. Output structured summary: files refactored, dead code removed, performance wins, PRs opened
"""

# --------------------------------------------------------------------------
# Generic residual cleanup (runs last, only for leftovers)
# --------------------------------------------------------------------------

# Only unambiguous shell/target phrasings. Deliberately NO catch-all
# `staging` -> `main`, which corrupts prose ("no staging branch to reconcile"
# became "no main branch to reconcile").
GENERIC_REWRITES = [
    (re.compile(r"origin/staging"), "origin/main"),
    (re.compile(r"--branch staging\b"), "--branch main"),
    (re.compile(r"--head staging\b"), "--head main"),
    (re.compile(r"\bgit checkout staging\b"), "git checkout main"),
    (re.compile(r"\bgit push origin staging\b"), "git push origin main"),
    (re.compile(r"\bPRs targeting staging\b"), "PRs targeting main"),
    (re.compile(r"\bPRs into staging\b"), "PRs into main"),
    (re.compile(r"\bPR to staging\b"), "PR to main"),
    (re.compile(r"\bRebase staging on main\b"), "Rebase the working branch on main"),
    (re.compile(r"\bstaging→main\b"), "direct-to-main"),
    (re.compile(r"\bstaging->main\b"), "direct-to-main"),
    # Bare `staging` in shell commands and pipeline prose. These are explicit
    # (not a catch-all) so authored explanations survive intact.
    (re.compile(r"git branch --merged staging"), "git branch --merged main"),
    (re.compile(r'grep -v "\\\*\\\\\|staging\\\\\|main"'), 'grep -v "\\*\\|main"'),
    (re.compile(r"origin/main\.\.staging"), "origin/main..HEAD"),
    (re.compile(r"\bbase is NOT staging\b"), "base is NOT main"),
    (re.compile(r"\bon staging to complete\b"), "on main to complete"),
    (re.compile(r"\buntil staging CI is green\b"), "until main CI is green"),
    (re.compile(r"\bIf staging CI fails\b"), "If main CI fails"),
    (re.compile(r"commit directly to staging"), "commit directly to main"),
    (re.compile(r"trivial commit to staging"), "trivial commit to main"),
    (re.compile(r"\bto staging to trigger\b"), "to main to trigger"),
    (re.compile(r"production/staging health"), "production health"),
    (re.compile(r"Push hot fixes directly to staging"), "Push hot fixes directly to main"),
]


# Literal (non-regex) replacements, applied first. Escaping these as regex
# patterns is error-prone because the strings contain backslashes and pipes.
LITERAL_REPLACEMENTS = [
    ('grep -v "\\*\\|staging\\|main"', 'grep -v "\\*\\|main"'),
]


def rewrite_prompt(prompt: str, job_base: str = "") -> str:
    """Return *prompt* retargeted at main with the staging lane removed.

    *job_base* is the job name before " - <repo>"; the per-type section rewrites
    are gated on it because several job types share a `## Tasks` heading and
    would otherwise overwrite each other's bodies.
    """
    if not isinstance(prompt, str) or not prompt:
        return prompt

    text = prompt
    for literal, replacement in LITERAL_REPLACEMENTS:
        text = text.replace(literal, replacement)

    # Drop lines that only exist to orchestrate the staging lane.
    text = "\n".join(
        line
        for line in text.split("\n")
        if "release-pr.yml workflow auto-creates" not in line
        and "release-pr.yml workflow auto-promotes" not in line
    )

    # --- Daily Review ---
    if job_base == "Daily Review":
        text = DAILY_REVIEW_INTRO.sub(DAILY_REVIEW_INTRO_MAIN, text)
        text = DAILY_REVIEW_PHASE_1.sub(DAILY_REVIEW_PHASE_1_MAIN, text)
        text = DAILY_REVIEW_PHASE_2.sub(DAILY_REVIEW_PHASE_2_MAIN, text)
        text = DAILY_REVIEW_PHASE_3.sub(DAILY_REVIEW_PHASE_3_MAIN, text)
        # Phase 4 (open the staging->main PR) has no equivalent: drop it entirely.
        text = DAILY_REVIEW_PHASE_4.sub("", text)
        text = PHASE1_A.sub(PHASE1_A_MAIN, text)
        text = PHASE1_C.sub(PHASE1_C_MAIN, text)

    # --- Weekly Merge / Weekly Release ---
    if job_base == "Weekly Merge":
        text = WEEKLY_MERGE_INTRO.sub(WEEKLY_MERGE_INTRO_MAIN, text)
    elif job_base == "Weekly Release":
        text = WEEKLY_RELEASE_INTRO.sub(WEEKLY_RELEASE_INTRO_MAIN, text)
    if job_base == "Weekly Merge":
        text = WEEKLY_MERGE_TASKS.sub(WEEKLY_MERGE_TASKS_MAIN, text)
    elif job_base == "Weekly Release":
        text = WEEKLY_RELEASE_TASKS.sub(WEEKLY_RELEASE_TASKS_MAIN, text)

    # --- Daily Improvement ---
    elif job_base == "Daily Improvement":
        text = DAILY_IMPROVEMENT_TASKS.sub(DAILY_IMPROVEMENT_TASKS_MAIN, text)

    # --- Shared rebase preamble ---
    if "## Rebase Discipline" in text:
        text = REBASE_BLOCK.sub(REBASE_BLOCK_MAIN, text)

    # --- Report block lines ---
    text = REPORT_STAGING_LINES.sub("", text)

    # --- Residual generic pass (catches stragglers only) ---
    for pattern, replacement in GENERIC_REWRITES:
        text = pattern.sub(replacement, text)

    # Tidy: collapse blank-line runs and drop a dangling "Phase 4" mention.
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    text = text.replace("ALL 4 phases below", "ALL 3 phases below")
    text = text.replace("Complete all 4 phases every run", "Complete all 3 phases every run")
    text = text.replace("skipped <N> main→main", "skipped <N> non-main-base")
    text = text.replace("skipped <N> direct-to-main", "skipped <N> non-main-base")
    # Drop the now-empty "handle in Phase 4" trace if any survives.
    text = text.replace(" — handle in Phase 4.", ".")
    return text


def update_jobs(jobs, *, out=None, dry_run=False):
    """Retarget every job prompt. Returns the count of changed jobs."""
    count = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = job.get("name", "")
        if name.rsplit(" - ", 1)[0] == "Daily Standup":
            continue  # never touches a branch

        original = job.get("prompt", "")
        base = name.rsplit(" - ", 1)[0] if " - " in name else name
        updated = rewrite_prompt(original, base)
        if updated != original:
            count += 1
            print(f"  ✓ {name}")
            if not dry_run:
                job["prompt"] = updated

    if out is not None and not dry_run:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        print(f"Written to {out}")

    return count


def _resolve_jobs_file(argv) -> Path:
    if "--jobs-file" not in argv:
        return DEFAULT_JOBS_FILE
    idx = argv.index("--jobs-file")
    if idx + 1 >= len(argv):
        print("ERROR: --jobs-file requires a path argument", file=sys.stderr)
        sys.exit(1)
    return Path(argv[idx + 1])


def main() -> int:
    argv = sys.argv[1:]
    jobs_file = _resolve_jobs_file(argv)
    dry_run = "--dry-run" in argv

    if not Path(jobs_file).exists():
        print(f"Jobs file not found: {jobs_file}", file=sys.stderr)
        return 1

    jobs, _ = load_jobs(Path(jobs_file))
    print(f"{'Would retarget' if dry_run else 'Retargeting'} jobs in {jobs_file}")
    count = update_jobs(jobs, out=Path(jobs_file), dry_run=dry_run)
    print(f"\n{'Would update' if dry_run else 'Updated'} {count} jobs")

    # Verify against the *rewritten* text, not the possibly-unmutated job dicts.
    remaining = []
    for job in jobs:
        jn = job.get("name", "")
        jb = jn.rsplit(" - ", 1)[0] if " - " in jn else jn
        rewritten = rewrite_prompt(job.get("prompt", "") or "", jb)
        if re.search(r"staging", rewritten, re.I):
            remaining.append(job.get("name", "?"))
    if remaining:
        print(f"\nWARNING: {len(remaining)} job(s) still mention staging:")
        for name in remaining:
            print(f"  - {name}")
        return 1
    print("No staging references remain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
