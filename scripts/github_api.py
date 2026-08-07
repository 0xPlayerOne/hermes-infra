#!/usr/bin/env python3
"""Shared GitHub API helpers for infra scripts."""

import json
import subprocess


def gh_api_put(endpoint: str, payload: dict, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a PUT request against the GitHub API via `gh`.

    Returns the CompletedProcess so callers can inspect returncode,
    stdout, and stderr.
    """
    return subprocess.run(
        [
            "gh",
            "api",
            endpoint,
            "--method",
            "PUT",
            "-H",
            "Content-Type: application/json",
            "-f",
            f"payload={json.dumps(payload)}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
