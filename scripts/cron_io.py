#!/usr/bin/env python3
"""Shared jobs.json I/O for cron prompt maintenance scripts."""

import json
import sys
from pathlib import Path

DEFAULT_JOBS_FILE = Path.home() / ".hermes/profiles/intern/cron/jobs.json"


def load_jobs(path: Path) -> tuple[list, dict]:
    """Load a jobs file and return (jobs_list, original_data).

    Handles both wrapped ``{"jobs": [...], ...}`` structures and bare lists.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "jobs" in data:
        return data["jobs"], data
    return data, data


def save_jobs(path: Path, data: dict) -> None:
    """Write *data* back to *path* with pretty-printed JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_jobs_update(
    jobs_file: Path,
    update_fn,
    *,
    success_msg: str = "Updated {count} jobs",
    missing_msg: str = "Jobs file not found: {path}",
) -> int:
    """Load jobs, apply *update_fn*, save, and print a summary.

    Returns the count of updated jobs, or exits with code 1 if the file is missing.
    """
    if not jobs_file.exists():
        print(missing_msg.format(path=jobs_file), file=sys.stderr)
        sys.exit(1)
    jobs, data = load_jobs(jobs_file)
    count = update_fn(jobs)
    save_jobs(jobs_file, data)
    print(success_msg.format(count=count))
    return count
