#!/usr/bin/env python3
"""
Standardize CI workflows + dependabot configs across all 9 repos.
Fixes:
1. Action version pinning (checkout@v7, mise-action@v4)
2. Staging PR skip guard (skip CI when staging PRs into staging)
3. Dependency-type: production restriction (prevents major bumps in grouped PRs)
4. Missing dependabot configs
5. Missing permission/concurrency blocks
"""

import os

from repo_registry import REPO_PATHS

# Canonical repo name -> local checkout path (see repo_registry.py).
REPOS = REPO_PATHS

# ============================================================
# STANDARD CI TEMPLATE for bun/TS repos
# ============================================================
BUN_CI_TEMPLATE = """name: CI

on:
  push:
    branches: [main, staging]
  pull_request:
    branches: [main, staging]

permissions:
  contents: read

concurrency:
  group: ci-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  quality:
    name: Build, Format, Lint & Type Check
    if: github.event_name != 'pull_request' || github.head_ref != 'staging'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: jdx/mise-action@v4
        with:
          cache: true
      - run: bun install --frozen-lockfile
      - name: Format check
        run: bun run format:check
      - name: Lint
        run: bun run lint
      - name: Type check
        run: bun run type:check
      - name: Build
        run: bun run build

  test:
    name: Test
    runs-on: ubuntu-latest
    needs: quality
    steps:
      - uses: actions/checkout@v7
      - uses: jdx/mise-action@v4
        with:
          cache: true
      - run: bun install --frozen-lockfile
      - name: Test
        run: bun run test
"""

# Repos that should use the standard bun CI template
BUN_REPOS = [
    "pink-binder",
    "v0-portfolio",
    "nifty-contracts-api",
    "nifty-fe-monorepo",
    "nifty-league-subgraph",
    "PlayFabConfigs",
]

# Special bun repos: nifty-smart-contracts has Hardhat so needs extra steps
SMART_CONTRACTS_CI = """name: CI

on:
  push:
    branches: [main, staging]

permissions:
  contents: read

concurrency:
  group: ci-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  security:
    name: Security Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: jdx/mise-action@v4
        with:
          cache: true
      - run: bun install --frozen-lockfile
      - name: Install osv-scanner
        run: |
          curl -fsSL https://github.com/google/osv-scanner/releases/latest/download/osv-scanner_linux_amd64 -o /usr/local/bin/osv-scanner
          chmod +x /usr/local/bin/osv-scanner
      - name: Scan lockfile (fails on NEW vulns)
        run: bash scripts/audit.sh

  quality:
    name: Build, Format, Lint & Type Check
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: jdx/mise-action@v4
        with:
          cache: true
      - run: bun install --frozen-lockfile
      - name: Check formatting
        run: bun run format:check
      - name: Lint TypeScript
        run: bun run lint:ts:check
      - name: Lint Solidity
        run: bun run lint:sol
      - name: Compile contracts
        run: bunx hardhat compile
      - name: Type-check
        run: bun run type-check

  test:
    name: Test
    runs-on: ubuntu-latest
    needs: quality
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: jdx/mise-action@v4
        with:
          cache: true
      - run: bun install --frozen-lockfile
      - name: Compile contracts
        run: bunx hardhat compile
      - name: Test with coverage
        run: bun run test:coverage
      - name: Test contract deployment
        run: bunx hardhat run --no-compile --network hardhat src/scripts/deploy_test.ts
"""


# ============================================================
# STANDARD DEPENDABOT CONFIG for npm/bun repos
# ============================================================
# The key pattern: production deps grouped with minor/patch only
# Major production bumps get individual PRs (CI catches failures)
# Dev deps grouped together
def npm_dependabot(labels: bool = False) -> str:
    """Return the standard npm dependabot config.

    *labels* adds the ``dependencies`` / ``ci`` label sets used by
    nifty-smart-contracts. The two historical templates differed only
    by these labels, so they share one builder.
    """
    npm_labels = "    labels:\n      - dependencies\n" if labels else ""
    ga_labels = "    labels:\n      - dependencies\n      - ci\n" if labels else ""
    return f"""version: 2
updates:
  - package-ecosystem: npm
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 10
{npm_labels}    groups:
      production-dependencies:
        dependency-type: production
        update-types:
          - patch
          - minor
      development-dependencies:
        dependency-type: development

  - package-ecosystem: github-actions
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 5
{ga_labels}"""


NPM_DEPENDABOT = npm_dependabot(labels=False)
# nifty-smart-contracts - same npm pattern, plus dependency labels
NPM_SC_DEPENDABOT = npm_dependabot(labels=True)

# PlayFabConfigs uses bun ecosystem
BUN_DEPENDABOT = """version: 2

updates:
  - package-ecosystem: bun
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 10
    labels:
      - dependencies
    groups:
      production-dependencies:
        dependency-type: production
        update-types:
          - patch
          - minor
      development-dependencies:
        dependency-type: development

  - package-ecosystem: github-actions
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 5
    labels:
      - dependencies
    groups:
      github-actions:
        patterns:
          - '*'
"""

# hermes-infra (pip + cargo)
HERMES_INFRA_DEPENDABOT = """version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 10
    target-branch: staging
    labels:
      - dependencies
      - python
    groups:
      python-dependencies:
        dependency-type: production
        update-types:
          - patch
          - minor

  - package-ecosystem: cargo
    directory: /
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 10
    target-branch: staging
    labels:
      - dependencies
      - rust
    groups:
      rust-dependencies:
        patterns:
          - '*'
        update-types:
          - patch
          - minor

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 5
    target-branch: staging
    labels:
      - dependencies
      - ci
"""

# model-gateway (cargo only)
MODEL_GATEWAY_DEPENDABOT = """version: 2
updates:
  - package-ecosystem: cargo
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 10
    labels:
      - dependencies
      - rust
    groups:
      rust-dependencies:
        patterns:
          - '*'
        update-types:
          - patch
          - minor

  - package-ecosystem: github-actions
    directory: /
    target-branch: staging
    schedule:
      interval: weekly
      day: monday
    open-pull-requests-limit: 5
    labels:
      - dependencies
      - ci
"""


def write_file(name, relative_path, content, kind):
    """Write *content* under a repo checkout, creating parent directories."""
    path = os.path.join(REPOS[name], relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.lstrip("\n"))
    print(f"  ✓ {name}: {kind} written ({len(content)} chars)")


def write_ci(name, content):
    write_file(name, ".github/workflows/ci.yml", content, "CI")


def write_dependabot(name, content):
    write_file(name, ".github/dependabot.yml", content, "dependabot")


if __name__ == "__main__":
    # ============================================================
    # CI UPDATES
    # ============================================================
    print("=== CI Workflows ===")

    for name in BUN_REPOS:
        write_ci(name, BUN_CI_TEMPLATE)

    # nifty-smart-contracts has special Hardhat/Solidity needs
    write_ci("nifty-smart-contracts", SMART_CONTRACTS_CI)

    # hermes-infra and model-gateway have different stacks - don't standardize CI
    # but DO update action versions
    print("  ✓ hermes-infra: CI unchanged (Rust/Python stack)")
    print("  ✓ model-gateway: CI unchanged (Rust stack)")

    # ============================================================
    # DEPENDABOT UPDATES
    # ============================================================
    print("\n=== Dependabot ===")

    # npm repos (bun-managed but npm ecosystem works for dependabot)
    for name in [
        "pink-binder",
        "v0-portfolio",
        "nifty-contracts-api",
        "nifty-fe-monorepo",
        "nifty-league-subgraph",
    ]:
        write_dependabot(name, NPM_DEPENDABOT)

    # nifty-smart-contracts npm with labels
    write_dependabot("nifty-smart-contracts", NPM_SC_DEPENDABOT)

    # PlayFabConfigs uses bun ecosystem
    write_dependabot("PlayFabConfigs", BUN_DEPENDABOT)

    # hermes-infra (pip + cargo)
    write_dependabot("hermes-infra", HERMES_INFRA_DEPENDABOT)

    # model-gateway - ADD dependabot (was missing)
    write_dependabot("model-gateway", MODEL_GATEWAY_DEPENDABOT)

    print("\n✅ All CI + dependabot configs written")
