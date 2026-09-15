"""Tests for scripts/retarget-cron-to-main.py.

The script converts Hermes cron prompts from the staging topology to
direct-to-main. The regression it guards against is real: a naive
``staging`` -> ``main`` substitution produced instructions like
"Sync Main with Main", and unscoped per-type rewrites let four job types
overwrite each other's ``## Tasks`` bodies.
"""

import json
import re
import sys
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


# ── rewrite_prompt edge cases (lines 211-212) ─────────────────────────────

def test_rewrite_prompt_rejects_none(mod):
    """Non-string input is returned unchanged."""
    assert mod.rewrite_prompt(None) is None


def test_rewrite_prompt_rejects_empty(mod):
    """Empty string input is returned unchanged."""
    assert mod.rewrite_prompt("") == ""


def test_rewrite_prompt_rejects_non_string(mod):
    """Non-string input (e.g. int) is returned unchanged."""
    assert mod.rewrite_prompt(42) == 42


# ── update_jobs edge cases ────────────────────────────────────────────────

def test_update_jobs_skips_non_dict_entries(mod):
    """Non-dict entries in the jobs list are silently skipped (line 278)."""
    jobs = [
        {"name": "Weekly Merge - repo", "prompt": STAGING_WEEKLY_MERGE},
        "not-a-dict",
        None,
        {"name": "Daily Standup - repo", "prompt": STAGING_STANDUP},
    ]
    count = mod.update_jobs(jobs)
    assert count == 1  # only Weekly Merge changed; Standup + non-dicts skipped


def test_update_jobs_no_changes_returns_zero(mod):
    """Already-main prompts (no staging) don't increment the counter."""
    jobs = [
        {"name": "Weekly Merge - repo", "prompt": STAGING_STANDUP},  # no staging, won't change
    ]
    count = mod.update_jobs(jobs)
    assert count == 0


def test_update_jobs_dry_run_no_file(mod, tmp_path):
    """dry_run=True modifies in memory but does NOT write the output file."""
    jobs = [{"name": "Weekly Merge - repo", "prompt": STAGING_WEEKLY_MERGE}]
    out = tmp_path / "jobs.json"
    count = mod.update_jobs(jobs, out=out, dry_run=True)
    assert count == 1
    assert not out.exists()  # file should NOT be written in dry-run mode


# ── _resolve_jobs_file (lines 300-307) ────────────────────────────────────

def test_resolve_jobs_file_default(mod):
    """Without --jobs-file, returns DEFAULT_JOBS_FILE."""
    result = mod._resolve_jobs_file([])
    assert isinstance(result, Path)
    assert result == mod.DEFAULT_JOBS_FILE


def test_resolve_jobs_file_with_flag(mod, tmp_path):
    """With --jobs-file, returns the specified path."""
    custom = tmp_path / "my-jobs.json"
    result = mod._resolve_jobs_file(["--jobs-file", str(custom)])
    assert result == custom


def test_resolve_jobs_file_missing_arg(mod):
    """--jobs-file without a path argument exits with code 1."""
    with pytest.raises(SystemExit) as exc_info:
        mod._resolve_jobs_file(["--jobs-file"])
    assert exc_info.value.code == 1


# ── main() entry point (lines 310-342) ───────────────────────────────────

def test_main_missing_jobs_file(mod, monkeypatch, capsys):
    """main() returns 1 and prints error when jobs file doesn't exist."""
    monkeypatch.setattr(mod, "load_jobs", lambda p: ([], {}))
    monkeypatch.setattr(Path, "exists", lambda self: False)
    rc = mod.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "Jobs file not found" in captured.err


def test_main_dry_run(mod, tmp_path, monkeypatch, capsys):
    """main() with --dry-run: processes jobs, reports would-be changes, returns 0."""
    jobs_file = tmp_path / "jobs.json"
    jobs_data = [
        {"name": "Weekly Merge - repo", "prompt": STAGING_WEEKLY_MERGE},
    ]
    jobs_file.write_text(json.dumps(jobs_data), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["retarget-cron-to-main.py", "--jobs-file", str(jobs_file), "--dry-run"])
    monkeypatch.setattr(mod, "load_jobs", lambda p: (jobs_data, jobs_data))

    rc = mod.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "Would retarget" in captured.out
    assert "Would update 1 jobs" in captured.out
    assert "No staging references remain." in captured.out


def test_main_success(mod, tmp_path, monkeypatch, capsys):
    """main() normal execution: writes jobs file, verifies no staging refs, returns 0."""
    jobs_file = tmp_path / "jobs.json"
    jobs_data = [
        {"name": "Weekly Merge - repo", "prompt": STAGING_WEEKLY_MERGE},
        {"name": "Daily Standup - repo", "prompt": STAGING_STANDUP},
    ]
    jobs_file.write_text(json.dumps(jobs_data), encoding="utf-8")

    # Track what load_jobs returns and what update_jobs writes
    loaded_data = [dict(j) for j in jobs_data]

    monkeypatch.setattr(sys, "argv", ["retarget-cron-to-main.py", "--jobs-file", str(jobs_file)])
    monkeypatch.setattr(mod, "load_jobs", lambda p: (loaded_data, loaded_data))

    rc = mod.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "Retargeting jobs" in captured.out
    assert "Updated 1 jobs" in captured.out
    assert "No staging references remain." in captured.out


def test_main_staging_remains(mod, tmp_path, monkeypatch, capsys):
    """main() returns 1 when staging references survive the rewrite."""
    jobs_file = tmp_path / "jobs.json"
    # A prompt that survives the rewrite still mentioning staging (edge case)
    bad_prompt = "This prompt still has staging references and won't be fully rewritten"
    jobs_data = [{"name": "Weekly Merge - repo", "prompt": bad_prompt}]

    jobs_file.write_text(json.dumps(jobs_data), encoding="utf-8")
    assert jobs_file.exists(), "jobs file must exist before calling main()"

    monkeypatch.setattr(sys, "argv", ["retarget-cron-to-main.py", "--jobs-file", str(jobs_file)])
    monkeypatch.setattr(mod, "load_jobs", lambda p: (jobs_data, jobs_data))
    # Also make rewrite_prompt not remove "staging" so the verification catches it
    monkeypatch.setattr(mod, "rewrite_prompt", lambda prompt, job_base="": prompt)

    rc = mod.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "still mention staging" in captured.out
