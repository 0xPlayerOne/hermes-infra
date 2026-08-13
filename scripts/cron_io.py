#!/usr/bin/env python3
"""Shared jobs.json I/O for cron prompt maintenance scripts."""

import json
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
