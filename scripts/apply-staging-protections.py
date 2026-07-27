#!/usr/bin/env python3
"""Apply staging branch protections to all repos."""

import json
import subprocess

CWD = "/Users/amf/Developer/pink-binder"

REPOS = [
    ("pink-binder", "0xPlayerOne/pink-binder"),
    ("v0-portfolio", "0xPlayerOne/v0-portfolio"),
    ("nifty-contracts-api", "NiftyLeague/nifty-contracts-api"),
    ("nifty-fe-monorepo", "NiftyLeague/nifty-fe-monorepo"),
    ("nifty-league-subgraph", "NiftyLeague/nifty-league-subgraph"),
    ("nifty-smart-contracts", "NiftyLeague/nifty-smart-contracts"),
    ("PlayFabConfigs", "NiftyLeague/PlayFabConfigs"),
    ("hermes-infra", "0xPlayerOne/hermes-infra"),
    ("model-gateway", "0xPlayerOne/model-gateway"),
]

# Staging protection rules per user's requirements:
# - Allow direct pushes (for small fixes)
# - Allow force pushes (for rebases)
# - No required PR reviews
# - No required status checks enforcement
# - No linear history requirement
# - No admin bypass restriction (admins can push)
# - Allow deletions (for cleanup)

payload = {
    "required_status_checks": {"strict": False, "contexts": [], "enforcement_level": "off"},
    "enforce_admins": False,
    "required_pull_request_reviews": None,
    "required_linear_history": {"enabled": False},
    "allow_force_pushes": {"enabled": True},
    "allow_deletions": {"enabled": True},
    "restrictions": None,
}

with open("/tmp/staging-protection.json", "w") as f:
    json.dump(payload, f)

for name, remote in REPOS:
    print(f"\n--- {name} ({remote}) ---")
    r = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{remote}/branches/staging/protection",
            "--method",
            "PUT",
            "--input",
            "/tmp/staging-protection.json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=CWD,
    )
    if r.returncode == 0:
        print("  ✅ Staging protection applied")
    else:
        err = r.stderr.strip()
        if "Upgrade to GitHub Pro" in err or "403" in err:
            print("  ⚠️  GitHub Free limitation (private repo) - cannot set via API")
        else:
            print(f"  ❌ Failed: {err[:200]}")
