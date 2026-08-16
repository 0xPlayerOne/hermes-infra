"""Tests for scripts/harden-daily-review-prompts.py."""

import json
import sys

import pytest


def sample_jobs():
    """Return a list of sample cron job dicts matching the expected format."""
    return [
        {
            "name": "Weekly Maint - hermes-infra",
            "prompt": "## Branch Strategy (MANDATORY)\n- Branch from staging\n- PR into staging\n",
        },
        {
            "name": "Daily Review - pink-binder",
            "prompt": "## SOP\n1. Review open PRs\n2. Merge if green\n",
        },
        {
            "name": "Daily Sentinel - model-gateway",
            "prompt": "TASK 1 — Catch drift: run tests.\nTASK 2 — Report findings.\n",
        },
        {
            "name": "Weekly Gate - hermes-infra",
            "prompt": "## SOP\n1. Gate review\n2. Approve\n",
        },
        {
            "name": "Daily Standup - team",
            "prompt": "## Standup\nWhat did you do?\n",
        },
        {
            "name": "Custom Job - unknown",
            "prompt": "## Custom\nDo the thing.\n",
        },
    ]


def test_harden_jobs_updates_daily_review(load_script):
    """Daily Review jobs get the hardened prompt injected."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = sample_jobs()
    count = module.harden_jobs(jobs)

    # Only the Daily Review job should be updated
    assert count == 1

    dr = [j for j in jobs if "Daily Review" in j["name"]][0]
    assert "You are a daily code reviewer for" in dr["prompt"]
    assert "0xPlayerOne/pink-binder" in dr["prompt"]
    assert "bun test --coverage --isolate" in dr["prompt"]
    assert "## PHASE 0" in dr["prompt"]
    assert "## PHASE 4" in dr["prompt"]


def test_harden_jobs_preserves_non_daily_review(load_script):
    """Non-Daily-Review jobs are left untouched."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = sample_jobs()
    original_prompts = {j["name"]: j["prompt"] for j in jobs}
    module.harden_jobs(jobs)

    for job in jobs:
        if "Daily Review" not in job["name"]:
            assert job["prompt"] == original_prompts[job["name"]]


def test_harden_jobs_skips_non_dict_entries(load_script):
    """Non-dict entries in the list are silently skipped."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = sample_jobs()
    jobs.insert(2, "not a dict")
    jobs.insert(4, None)

    count = module.harden_jobs(jobs)
    assert count == 1


def test_harden_jobs_unknown_repo_uses_fallback(load_script):
    """A Daily Review job whose repo is not in REPO_INFO gets fallback values."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = [{"name": "Daily Review - some-unknown-repo", "prompt": "old"}]
    module.harden_jobs(jobs)

    assert jobs[0]["prompt"].startswith("You are a daily code reviewer for")
    assert "unknown/repo" in jobs[0]["prompt"]
    assert "bun test" in jobs[0]["prompt"]


def test_test_commands_keys_match_registry(load_script):
    """TEST_COMMANDS keys must equal repo_registry.REPO_REMOTES (single source)."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    registry = load_script("scripts/repo_registry.py")
    assert set(module.TEST_COMMANDS) == set(registry.REPO_REMOTES)


def test_harden_jobs_repo_name_without_dash(load_script):
    """If the job name has no ' - ', the full name is used as the repo key."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = [{"name": "Daily Review", "prompt": "old"}]
    module.harden_jobs(jobs)

    assert jobs[0]["prompt"].startswith("You are a daily code reviewer for")
    assert "unknown/repo" in jobs[0]["prompt"]


def test_harden_jobs_multiple_daily_reviews(load_script):
    """All Daily Review jobs in the list are updated."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = [
        {"name": "Daily Review - pink-binder", "prompt": "old1"},
        {"name": "Daily Review - hermes-infra", "prompt": "old2"},
        {"name": "Daily Review - model-gateway", "prompt": "old3"},
    ]
    count = module.harden_jobs(jobs)

    assert count == 3
    assert "0xPlayerOne/pink-binder" in jobs[0]["prompt"]
    assert "0xPlayerOne/hermes-infra" in jobs[1]["prompt"]
    assert "0xPlayerOne/model-gateway" in jobs[2]["prompt"]


def test_harden_jobs_is_idempotent(load_script):
    """Running harden_jobs twice does not change already-hardened prompts."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = [{"name": "Daily Review - pink-binder", "prompt": "old"}]

    first = module.harden_jobs(jobs)
    assert first == 1
    first_prompt = jobs[0]["prompt"]

    second = module.harden_jobs(jobs)
    assert second == 0
    assert jobs[0]["prompt"] == first_prompt


def test_main_reads_and_writes_file(load_script, tmp_path, monkeypatch):
    """main() reads JOBS_FILE, hardens Daily Review jobs, and writes back."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    test_file = tmp_path / "jobs.json"
    monkeypatch.setattr(module, "JOBS_FILE", test_file)

    jobs = [
        {"name": "Daily Review - pink-binder", "prompt": "old"},
        {"name": "Weekly Maint - hermes-infra", "prompt": "old2"},
    ]
    test_file.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["harden-daily-review-prompts"])
    module.main()

    updated = json.loads(test_file.read_text(encoding="utf-8"))
    assert isinstance(updated, dict)
    assert "jobs" in updated
    assert len(updated["jobs"]) == 2
    assert "0xPlayerOne/pink-binder" in updated["jobs"][0]["prompt"]
    assert updated["jobs"][1]["prompt"] == "old2"


def test_main_handles_unwrapped_jobs_list(load_script, tmp_path, monkeypatch):
    """main() handles a jobs file that is a bare list (no 'jobs' wrapper)."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    test_file = tmp_path / "jobs.json"
    monkeypatch.setattr(module, "JOBS_FILE", test_file)

    jobs = [{"name": "Daily Review - model-gateway", "prompt": "old"}]
    test_file.write_text(json.dumps(jobs), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["harden-daily-review-prompts"])
    module.main()

    updated = json.loads(test_file.read_text(encoding="utf-8"))
    assert isinstance(updated, list)
    assert "0xPlayerOne/model-gateway" in updated[0]["prompt"]


def test_main_exits_on_missing_file(load_script, tmp_path, monkeypatch):
    """main() exits with code 1 when the jobs file does not exist."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(module, "JOBS_FILE", missing)

    monkeypatch.setattr(sys, "argv", ["harden-daily-review-prompts"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1


def test_harden_jobs_count_matches_updated(load_script, capsys):
    """harden_jobs returns the same count as the number of jobs it prints."""
    module = load_script("scripts/harden-daily-review-prompts.py")
    jobs = [
        {"name": "Daily Review - pink-binder", "prompt": "old1"},
        {"name": "Daily Review - hermes-infra", "prompt": "old2"},
        {"name": "Weekly Maint - hermes-infra", "prompt": "old3"},
    ]
    count = module.harden_jobs(jobs)
    captured = capsys.readouterr()

    assert count == 2
    assert captured.out.count("✓") == 2
    assert "pink-binder" in captured.out
    assert "hermes-infra" in captured.out
