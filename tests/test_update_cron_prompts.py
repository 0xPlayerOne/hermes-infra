"""Tests for scripts/update-cron-prompts.py."""

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


def test_update_jobs_adds_yolo_block(load_script):
    """Every job (except Daily Standup) gets the YOLO rebasing block appended."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    count = module.update_jobs(jobs)

    # Daily Standup should be skipped — no YOLO appended
    standup = [j for j in jobs if "Daily Standup" in j["name"]][0]
    assert module.YOLO_REBASING not in standup["prompt"]

    # All other jobs should contain the YOLO text
    for j in jobs:
        if "Daily Standup" not in j["name"]:
            assert "YOLO Mode" in j["prompt"]

    # Count excludes standup (5 out of 6 should be updated)
    assert count == 5


def test_update_jobs_skips_non_dict(load_script):
    """Non-dict entries in the list are silently skipped."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    jobs.insert(2, "not a dict")
    jobs.insert(4, None)
    count = module.update_jobs(jobs)
    # Still should have updated the valid ones (5)
    assert count == 5


def test_update_jobs_weekly_maint_replaces_section(load_script):
    """Weekly Maint replaces '## Branch Strategy (MANDATORY)' with the new strategy."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    module.update_jobs(jobs)

    maint = [j for j in jobs if "Weekly Maint" in j["name"]][0]
    # Old section should be gone
    assert "## Branch Strategy (MANDATORY)\n- Branch from staging" not in maint["prompt"]
    # New section should be present
    assert "## Branch Strategy (MANDATORY)\n- ALWAYS" in maint["prompt"]


def test_update_jobs_weekly_maint_replaces_sop_start(load_script):
    """Weekly Maint also rewrites the SOP start line."""
    module = load_script("scripts/update-cron-prompts.py")
    job = {
        "name": "Weekly Maint - hermes-infra",
        "prompt": "## Branch Strategy (MANDATORY)\n1. `git fetch origin && git checkout staging && git pull`\n",
    }
    module.update_jobs([job])
    assert "already done by rebase step above" in job["prompt"]


def test_update_jobs_daily_review_replaces_sop(load_script):
    """Daily Review replaces '## SOP' with the new SOP header."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    module.update_jobs(jobs)

    dr = [j for j in jobs if "Daily Review" in j["name"]][0]
    assert "## SOP\n1. Review" not in dr["prompt"]
    assert "REBASE FIRST" in dr["prompt"]


def test_update_jobs_daily_sentinel_replaces_task1(load_script):
    """Daily Sentinel prepends TASK 0 before TASK 1."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    module.update_jobs(jobs)

    ds = [j for j in jobs if "Daily Sentinel" in j["name"]][0]
    assert "TASK 1" in ds["prompt"]
    assert "TASK 0" in ds["prompt"]


def test_update_jobs_weekly_gate_replaces_sop(load_script):
    """Weekly Gate replaces '## SOP' with YOLO + new SOP."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    module.update_jobs(jobs)

    wg = [j for j in jobs if "Weekly Gate" in j["name"]][0]
    assert "## SOP\n1. Gate" not in wg["prompt"]
    assert "YOLO Mode" in wg["prompt"]


def test_update_jobs_no_change_if_section_missing(load_script):
    """If the target section is missing, no replacement happens (YOLO is still appended)."""
    module = load_script("scripts/update-cron-prompts.py")
    job = {
        "name": "Weekly Maint - hermes-infra",
        "prompt": "## Some Other Section\nNo match here.\n",
    }
    original = job["prompt"]
    module.update_jobs([job])
    # YOLO was appended
    assert "YOLO Mode" in job["prompt"]
    # Original content is still there
    assert original in job["prompt"]


def test_update_jobs_is_fully_idempotent(load_script):
    """The function is fully idempotent: after one pass a second pass makes no changes."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    count1 = module.update_jobs(jobs)
    assert count1 == 5

    # Track per-job prompt after first run
    after_first = [j.get("prompt", "") for j in jobs]

    # Second run should find nothing to change
    count2 = module.update_jobs(jobs)
    assert count2 == 0
    after_second = [j.get("prompt", "") for j in jobs]
    assert after_first == after_second

    # Third run — same
    count3 = module.update_jobs(jobs)
    assert count3 == 0
    after_third = [j.get("prompt", "") for j in jobs]
    assert after_second == after_third


def test_update_jobs_writes_to_out_path(load_script, tmp_path):
    """When out= is provided, the updated data is written to that path."""
    module = load_script("scripts/update-cron-prompts.py")
    jobs = sample_jobs()
    out_path = tmp_path / "updated_jobs.json"
    count = module.update_jobs(jobs, out=out_path)

    assert count == 5
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(written) == 6
    # Verify YOLO is in the written data
    assert any(module.YOLO_REBASING in j.get("prompt", "") for j in written)


def test_update_jobs_handles_wrapped_jobs_dict(load_script):
    """When jobs list is wrapped in {'jobs': [...]}, the main() function extracts it."""
    module = load_script("scripts/update-cron-prompts.py")
    # Simulate the wrapped format
    wrapped = {"jobs": sample_jobs()}
    unwrapped = wrapped["jobs"] if isinstance(wrapped, dict) and "jobs" in wrapped else wrapped
    count = module.update_jobs(unwrapped)
    assert count == 5


def test_main_uses_default_path(load_script, tmp_path, monkeypatch):
    """main() reads from DEFAULT_JOBS_FILE when --jobs-file is not provided."""
    module = load_script("scripts/update-cron-prompts.py")
    # Point DEFAULT_JOBS_FILE to a test path
    test_file = tmp_path / "jobs.json"
    monkeypatch.setattr(module, "DEFAULT_JOBS_FILE", test_file)

    # Create the test jobs file (wrapped format like the real one)
    jobs = sample_jobs()
    test_file.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    assert test_file.exists()

    monkeypatch.setattr(sys, "argv", ["update-cron-prompts"])
    module.main()

    # Verify the file was updated — main() writes a list (unwrapped)
    updated = json.loads(test_file.read_text(encoding="utf-8"))
    assert isinstance(updated, list)
    assert len(updated) == 6
    assert "YOLO Mode" in updated[0]["prompt"]


def test_main_uses_cli_arg(load_script, tmp_path, monkeypatch):
    """main() reads from the path given via --jobs-file."""
    module = load_script("scripts/update-cron-prompts.py")
    test_file = tmp_path / "custom_jobs.json"
    jobs = sample_jobs()
    test_file.write_text(json.dumps(jobs), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["update-cron-prompts", "--jobs-file", str(test_file)])
    module.main()

    updated = json.loads(test_file.read_text(encoding="utf-8"))
    assert len(updated) == 6
    assert "YOLO Mode" in updated[0]["prompt"]


def test_main_exits_on_missing_file(load_script, tmp_path, monkeypatch):
    """main() exits with code 1 when the jobs file does not exist."""
    module = load_script("scripts/update-cron-prompts.py")
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(sys, "argv", ["update-cron-prompts", "--jobs-file", str(missing)])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 1


def test_update_jobs_unknown_job_only_gets_yolo(load_script):
    """A job whose base name is not in UPDATES only gets YOLO appended."""
    module = load_script("scripts/update-cron-prompts.py")
    job = {"name": "Some Unknown Job - repo", "prompt": "## Original\nContent\n"}
    original = job["prompt"]
    module.update_jobs([job])
    # YOLO is appended
    assert module.YOLO_REBASING in job["prompt"]
    # Original content is still there
    assert original in job["prompt"]
