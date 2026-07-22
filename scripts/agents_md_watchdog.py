#!/usr/bin/env python3
"""
agents_md_watchdog.py — keeps the configured source root AGENTS.md coverage at 100%.

Runs after the Code Indexer cron. For every git repo under the configured source root that
lacks a root AGENTS.md, it:
  1. drops a constitution-stamp immediately via repo_standardize.py (so the repo
     is never agent-blind, even before a full deep-scan),
  2. prints the gap list to stdout (the cron delivers this; a subagent or the
     user can later run the full 2-stage deep-scan via the agents-md-generation
     skill).

Repos with a hand-written nested AGENTS.md (e.g. NiftyRoyale) are skipped.
Repos already stamped by this script are left alone (idempotent).

Usage: agents_md_watchdog.py [--deep]   (--deep is reserved for the full model
deep-scan workflow; normal cron runs only perform deterministic coverage checks)
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("HERMES_INFRA_DIR", Path(__file__).resolve().parents[1]))
DEV = Path(os.path.expanduser(os.environ.get("DEV_ROOT", "~/code")))
STAMPER = REPO_ROOT / "scripts" / "repo_standardize.py"
MISGEN = REPO_ROOT / "scripts" / "mise_toml_gen.py"


def git_roots(dev: Path):
    roots = []
    for root, dirs, _files in os.walk(dev):
        if ".git" in dirs:
            roots.append(Path(root))
            dirs[:] = []  # don't descend into sub-repos
    return sorted(roots)


def detect_stack(r: Path) -> str:
    """Lightweight stack detection — mirrors repo_standardize.py logic.
    Returns one of: typescript, python, rust, solidity, unity-cs, mixed-ts-py, unknown."""
    ts = py = sol = cs = 0
    unity = False
    for root, dirs, files in os.walk(r):
        dirs[:] = [
            d
            for d in dirs
            if d
            not in (
                "node_modules",
                ".git",
                "target",
                "__pycache__",
                "dist",
                "build",
                ".next",
                "out",
                "Library",
                "bin",
                "obj",
            )
        ]
        for f in files:
            p = f.lower()
            if p.endswith(".sol"):
                sol += 1
            elif p == "package.json":
                ts += 1
                if "Assets" in root.split(os.sep):
                    unity = True
            elif p in ("pyproject.toml", "requirements.txt"):
                py += 1
            elif p == "cargo.toml":
                return "rust"
            elif p.endswith(".csproj") or p.endswith(".cs"):
                cs += 1
    if sol > 0:
        return "solidity"
    if unity or (cs > ts and cs > 0):
        return "unity-cs"
    if ts > 0 and py == 0:
        return "typescript"
    if py > 0 and ts == 0:
        return "python"
    if ts > 0 and py > 0:
        return "mixed-ts-py"
    if cs > 0:
        return "unity-cs"
    return "unknown"


def main():
    roots = git_roots(DEV)
    gaps = []
    stamped = []
    for r in sorted(roots, key=lambda p: p.name):
        agents = r / "AGENTS.md"
        # skip if a hand-written AGENTS.md exists in a direct subdir (nested case)
        if agents.exists():
            continue
        # also skip if any immediate subdir has its own AGENTS.md (dispatcher pattern)
        nested = any((r / d / "AGENTS.md").exists() for d in os.listdir(r) if (r / d).is_dir())
        if nested:
            # e.g. NiftyRoyaleFork has NiftyRoyale/AGENTS.md — already covered
            continue
        gaps.append(r)
        # IMMEDIATE FALLBACK STAMP — only for stacks the detector gets RIGHT.
        # C# is ambiguous (Unity vs Azure Functions vs plain .NET) — do NOT auto-stamp
        # it, or we write a wrong manual. TS/Py/Solidity/Rust detection is reliable.
        sig = detect_stack(r)
        if sig in ("typescript", "python", "solidity", "rust", "mixed-ts-py") and STAMPER.exists():
            subprocess.run(
                [sys.executable, str(STAMPER), "--force", str(r)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            stamped.append(r)
        # C# / Unity / unknown -> leave for a real deep-scan (agents-md-generation skill)

        # Also drop a .mise.toml for reproducible toolchain (Node/Python/Rust pins)
        if MISGEN.exists():
            subprocess.run(
                [sys.executable, str(MISGEN), str(r), "--write"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    if not gaps:
        print("AGENTS.md coverage: 100% — no gaps found.")
        return
    print(f"AGENTS.md gaps found: {len(gaps)}")
    for r in gaps:
        print(f"  - {r.relative_to(DEV)}  (stamped: {'yes' if r in stamped else 'no'})")
    print("\nTo deep-scan, use the agents-md-generation skill per repo.")


if __name__ == "__main__":
    main()
