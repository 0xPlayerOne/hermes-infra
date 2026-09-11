"""Tests for scripts/retarget-cron-to-main.py.

The script converts Hermes cron prompts from the staging topology to
direct-to-main. The regression it guards against is real: a naive
``staging`` -> ``main`` substitution produced instructions like
"Sync Main with Main", and unscoped per-type rewrites let four job types
overwrite each other's ``## Tasks`` bodies.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mod(load_script):
    """Load the retarget script as a module."""
    return load_script("scripts/retarget-cron-to-main.py")


STAGING_DAILY_REVIEW = """You are a daily code reviewer for {owner}/{name}. Your mission: execute ALL 4 phases below in order.

## CORE RULES (MANDATORY)
1. **NO stopping early.** Complete all 4 phases every run.
2. **Wait for CI.** use `gh run list --branch staging --limit 5`.

## PHASE 0 — Initial Setup
- `git checkout staging && git pull`

## PHASE 1 — Merge ALL Open PRs into Staging
1. List ALL open PRs
2. For each open PR:
   a. If it's a staging→main PR (base:main), skip it — handle in Phase 4.
   b. If its base is NOT staging — note it.
   c. **If it's a dependabot PR targeting main**: close it immediately.
3. AFTER each merge: **wait for CI** on staging to complete.

## PHASE 2 — Sync Staging with Main
1. `git fetch origin --all && git checkout main && git pull && git checkout staging`
2. Check if staging is behind main.

## PHASE 3 — Verify Staging Passes Full CI
1. push a trivial commit to staging to trigger fresh CI

## PHASE 4 — Open staging→main PR
1. gh pr create --base main --head staging --title "Release: staging → main (YYYY-MM-DD)"

## Report Block
STAGING AHEAD OF MAIN: <Y commits>
"""

STAGING_WEEKLY_MERGE = """You are the Weekly Merge agent for {owner}/{name}. This runs Monday at 4AM.

## Tasks
1. git fetch origin && git checkout staging && git pull
2. Rebase staging on main: git rebase origin/main && git push --force-with-lease origin staging
3. List all open PRs targeting staging
4. Merge EVERY open PR into staging — merge all at once, do NOT wait for CI:
8. The release-pr.yml workflow auto-creates the staging→main PR on push.

Do NOT spend time fixing CI failures or test issues. The Weekly Release cron at 5AM handles all of that.

## Rebase Discipline (MANDATORY before any work)
1. git fetch origin && git checkout staging && git pull
3. If staging is BEHIND main: git rebase origin/main
"""

STAGING_WEEKLY_RELEASE = """You are the Weekly Release agent for {owner}/{name}.

## Tasks
1. git fetch origin && git checkout staging && git pull
2. PULL CI AND DEPLOYMENT ERRORS FROM GITHUB: gh run list --branch staging
5. The release-pr.yml workflow auto-promotes the staging→main PR on push to staging.

Do NOT run local tests before pulling CI errors. Start with GitHub CI data.

## Rebase Discipline (MANDATORY before any work)
1. git fetch origin && git checkout staging && git pull
"""

STAGING_WEEKLY_TEST = """You are a test sentinel.

## Tasks
1. git fetch origin && git checkout staging && git pull
3. Check production/staging health
4. Push hot fixes directly to staging
"""

STAGING_DAILY_IMPROVEMENT = """You are a daily improvement agent.

## Tasks
1. git fetch origin && git checkout staging && git pull
2. Scan the codebase for:
   - Dead code to remove
3. For each finding:
   - Open a PR to staging with a clear description of the improvement
4. Output structured summary

## YOLO Mode — NO ASKING, NO CONFIRMATIONS
"""

STAGING_STANDUP = """## Standup
What did you do?
"""


def _case(mod, name, prompt):
    return mod.rewrite_prompt(prompt, name.rsplit(" - ", 1)[0])


@pytest.mark.parametrize(
    "name,prompt",
    [
        ("Daily Review - pink-binder", STAGING_DAILY_REVIEW),
        ("Weekly Merge - pink-binder", STAGING_WEEKLY_MERGE),
        ("Weekly Release - pink-binder", STAGING_WEEKLY_RELEASE),
        ("Weekly Test - pink-binder", STAGING_WEEKLY_TEST),
        ("Daily Improvement - pink-binder", STAGING_DAILY_IMPROVEMENT),
    ],
)
def test_removes_every_staging_reference(mod, name, prompt):
    """No prompt may keep a staging reference of any kind."""
    out = _case(mod, name, prompt)
    assert not re.search(r"staging", out, re.I), [
        line for line in out.split("\n") if "staging" in line.lower()
    ]


@pytest.mark.parametrize(
    "name,prompt",
    [
        ("Daily Review - pink-binder", STAGING_DAILY_REVIEW),
        ("Weekly Merge - pink-binder", STAGING_WEEKLY_MERGE),
        ("Weekly Release - pink-binder", STAGING_WEEKLY_RELEASE),
        ("Weekly Test - pink-binder", STAGING_WEEKLY_TEST),
        ("Daily Improvement - pink-binder", STAGING_DAILY_IMPROVEMENT),
    ],
)
def test_is_idempotent(mod, name, prompt):
    """Re-running must not change anything the second time."""
    once = _case(mod, name, prompt)
    twice = mod.rewrite_prompt(once, name.rsplit(" - ", 1)[0])
    assert once == twice


def test_daily_review_phase_four_is_dropped(mod):
    """The staging->main PR phase has no equivalent on a direct repo."""
    out = _case(mod, "Daily Review - pink-binder", STAGING_DAILY_REVIEW)
    assert "PHASE 4" not in out
    assert "PHASE 3" in out


def test_daily_review_targets_main(mod):
    """Branch, CI, and PR instructions all point at main."""
    out = _case(mod, "Daily Review - pink-binder", STAGING_DAILY_REVIEW)
    assert "git checkout main" in out
    assert "--branch main" in out
    assert "## PHASE 1 — Land All Open PRs on Main" in out


def test_no_incoherent_self_reference(mod):
    """The naive substitution produced 'Sync Main with Main'; guard against it."""
    out = _case(mod, "Daily Review - pink-binder", STAGING_DAILY_REVIEW)
    assert "Main with Main" not in out
    assert "main onto main" not in out.lower()


def test_weekly_tasks_are_not_cross_contaminated(mod):
    """Several job types share a `## Tasks` heading.

    Unscoped rewrites let the four bodies overwrite one another, so each type
    must retain its own signature step.
    """
    merge = _case(mod, "Weekly Merge - pink-binder", STAGING_WEEKLY_MERGE)
    release = _case(mod, "Weekly Release - pink-binder", STAGING_WEEKLY_RELEASE)
    improvement = _case(mod, "Daily Improvement - pink-binder", STAGING_DAILY_IMPROVEMENT)

    assert "Merge EVERY open PR" in merge
    assert "PULL CI AND DEPLOYMENT ERRORS" in release
    assert "Scan the codebase for" in improvement
    # None of them may contain another type's signature.
    assert "Scan the codebase for" not in merge
    assert "Merge EVERY open PR" not in release


def test_standup_is_untouched(mod):
    """Daily Standup never touches a branch."""
    out = _case(mod, "Daily Standup - intern", STAGING_STANDUP)
    assert out == STAGING_STANDUP


def test_dependabot_instruction_no_longer_closes_prs(mod):
    """The old prompt closed dependabot PRs and recreated them against staging."""
    out = _case(mod, "Daily Review - pink-binder", STAGING_DAILY_REVIEW)
    assert "close it immediately" not in out
    assert "already target" in out


def test_update_jobs_reports_count_and_writes(mod, tmp_path):
    """update_jobs writes the file and reports how many jobs changed."""
    jobs = [
        {"name": "Daily Review - pink-binder", "prompt": STAGING_DAILY_REVIEW},
        {"name": "Daily Standup - intern", "prompt": STAGING_STANDUP},
    ]
    out = tmp_path / "jobs.json"
    count = mod.update_jobs(jobs, out=out)
    assert count == 1
    assert out.exists()
    assert "staging" not in out.read_text().lower()
