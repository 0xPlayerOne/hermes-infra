#!/usr/bin/env python3
"""Canonical repository registry shared by infra scripts.

Single source of truth for the nine tracked repositories: display name,
GitHub remote, and local checkout path. Scripts that iterate the repos
(CI/dependabot standardization, branch protections) import from here so a
repo added once shows up everywhere instead of drifting across copies.

Local paths are intentionally machine-specific: this is the operator's
personal infra repo and the checkouts live under ~/Developer.
"""

# Ordered: display name -> (owner/repo, local path)
REPOS = [
    ("pink-binder", "0xPlayerOne/pink-binder", "/Users/amf/Developer/pink-binder"),
    ("v0-portfolio", "0xPlayerOne/v0-portfolio", "/Users/amf/Developer/v0-portfolio"),
    (
        "nifty-contracts-api",
        "NiftyLeague/nifty-contracts-api",
        "/Users/amf/Developer/NiftyLeague/nifty-contracts-api",
    ),
    (
        "nifty-fe-monorepo",
        "NiftyLeague/nifty-fe-monorepo",
        "/Users/amf/Developer/NiftyLeague/nifty-fe-monorepo",
    ),
    (
        "nifty-league-subgraph",
        "NiftyLeague/nifty-league-subgraph",
        "/Users/amf/Developer/NiftyLeague/nifty-league-subgraph",
    ),
    (
        "nifty-smart-contracts",
        "NiftyLeague/nifty-smart-contracts",
        "/Users/amf/Developer/NiftyLeague/nifty-smart-contracts",
    ),
    (
        "PlayFabConfigs",
        "NiftyLeague/PlayFabConfigs",
        "/Users/amf/Developer/NiftyLeague/PlayFabConfigs",
    ),
    ("hermes-infra", "0xPlayerOne/hermes-infra", "/Users/amf/Developer/hermes-infra"),
    ("model-gateway", "0xPlayerOne/model-gateway", "/Users/amf/Developer/model-gateway"),
]

REPO_NAMES = [name for name, _, _ in REPOS]
REPO_REMOTES = {name: remote for name, remote, _ in REPOS}
REPO_PATHS = {name: path for name, _, path in REPOS}
