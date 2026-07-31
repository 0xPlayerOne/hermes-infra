#!/usr/bin/env python3
"""Apply hardened main branch protections to all 9 repos using REST API."""

import json
import subprocess

from repo_registry import REPO_NAMES, REPO_REMOTES

CWD = "/Users/amf/Developer/pink-binder"

# Per-repo required CI checks (repo registry provides names + remotes).
CHECKS = {
    "pink-binder": [
        "Build, Format, Lint & Type Check",
        "Test",
        "Security Scan",
        "Vercel Preview Comments",
    ],
    "v0-portfolio": ["Build, Format, Lint & Type Check", "Test", "Vercel Preview Comments"],
    "nifty-contracts-api": [
        "Build, Format, Lint & Type Check",
        "CI / Test",
        "Review dependency changes",
        "Vercel Preview Comments",
    ],
    "nifty-fe-monorepo": ["Build, Format, Lint & Type Check", "Test", "Vercel Preview Comments"],
    "nifty-league-subgraph": [
        "Build, Format, Lint & Type Check",
        "Test",
        "Security Scan",
        "CodeQL",
    ],
    "nifty-smart-contracts": ["Build, Format, Lint & Type Check", "Test"],
    "PlayFabConfigs": ["Build, Format, Lint & Type Check", "Test"],
    "hermes-infra": ["rust", "scripts"],
    "model-gateway": ["rust", "security", "dependencies"],
}

REPOS = [(name, REPO_REMOTES[name], CHECKS[name]) for name in REPO_NAMES]


def apply_protection(repo, remote, checks):
    print(f"\n--- {repo} ({remote}) ---")
    print(f"  Required checks: {checks}")

    # Build the full protection payload
    payload = {
        "required_status_checks": {"strict": True, "contexts": checks},
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "require_last_approval_review": False,
            "require_conversation_resolution": True,
        },
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "restrictions": None,
    }

    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{remote}/branches/main/protection",
            "--method",
            "PUT",
            "-H",
            "Content-Type: application/json",
            "-f",
            f"payload={json.dumps(payload)}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=CWD,
    )

    if result.returncode == 0:
        print("  ✅ Main protection applied")
    else:
        print(f"  ❌ Failed: {result.stderr[:300]}")
        return False

    # Apply merge queue (optional)
    mq_payload = {
        "merge_queue": {
            "enabled": True,
            "merge_method": "squash",
            "check_response_timeout_minutes": 30,
            "min_entries_to_merge": 1,
            "max_entries_to_merge": 5,
            "max_entries_to_build": 5,
            "build_timeout_secs": 3600,
            "required": False,
        }
    }

    result2 = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{remote}/merge-queue",
            "--method",
            "PUT",
            "-H",
            "Content-Type: application/json",
            "-f",
            f"payload={json.dumps(mq_payload)}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=CWD,
    )

    if result2.returncode == 0:
        print("  ✅ Merge queue configured (optional)")
    else:
        print(f"  ⚠️  Merge queue: {result2.stderr[:200]}")

    return True


def main():
    for repo, remote, checks in REPOS:
        apply_protection(repo, remote, checks)


if __name__ == "__main__":
    main()
