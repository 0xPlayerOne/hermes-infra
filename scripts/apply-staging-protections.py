#!/usr/bin/env python3
"""Apply staging branch protections to all repos."""

import json
import subprocess
import sys

from repo_registry import REPO_NAMES, REPO_REMOTES

REPOS = [(name, REPO_REMOTES[name]) for name in REPO_NAMES]

# Staging protection rules per user's requirements:
# - Allow direct pushes (for small fixes)
# - Allow force pushes (for rebases)
# - No required PR reviews
# - No required status checks enforcement
# - No linear history requirement
# - No admin bypass restriction (admins can push)
# - Allow deletions (for cleanup)

PAYLOAD = {
    "required_status_checks": {"strict": False, "contexts": [], "enforcement_level": "off"},
    "enforce_admins": False,
    "required_pull_request_reviews": None,
    "required_linear_history": {"enabled": False},
    "allow_force_pushes": {"enabled": True},
    "allow_deletions": {"enabled": True},
    "restrictions": None,
}


def main() -> int:
    for name, remote in REPOS:
        print(f"\n--- {name} ({remote}) ---")
        r = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{remote}/branches/staging/protection",
                "--method",
                "PUT",
                "-H",
                "Content-Type: application/json",
                "-f",
                f"payload={json.dumps(PAYLOAD)}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            print("  ✅ Staging protection applied")
        else:
            err = r.stderr.strip()
            if "Upgrade to GitHub Pro" in err or "403" in err:
                print("  ⚠️  GitHub Free limitation (private repo) - cannot set via API")
            else:
                print(f"  ❌ Failed: {err[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
