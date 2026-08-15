#!/usr/bin/env python3
"""
agents_md_watchdog.py — keeps the configured source root AGENTS.md coverage at 100%.

For every git repo under the configured source root that lacks a root AGENTS.md, it:
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

from stack_detect import detect_signals, primary_lang


def resolve_path(value):
    """Expand shell-style environment variables and a leading home marker."""
    return os.path.expanduser(os.path.expandvars(value))


REPO_ROOT = Path(os.environ.get("HERMES_INFRA_DIR", Path(__file__).resolve().parents[1]))
DEV = Path(resolve_path(os.environ.get("DEV_ROOT", "~/Developer")))
STAMPER = REPO_ROOT / "scripts" / "repo_standardize.py"
MISGEN = REPO_ROOT / "scripts" / "mise_toml_gen.py"


def curl_ok(url: str, timeout: int = 5) -> str:
    try:
        out = subprocess.run(
            [
                "curl",
                "-sf",
                "--max-time",
                str(timeout),
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        code = out.stdout.strip()
        if out.returncode != 0 or not code.isdigit() or code != "200":
            return f"unreachable/failed (http={code})"
        return f"healthy (http={code})"
    except Exception as exc:
        return f"error: {exc}"


def infra_health() -> tuple[str, str]:
    if os.environ.get("WATCHDOG_INFRA_CHECKS") != "1":
        return "skipped", "skipped"
    return (
        curl_ok("http://127.0.0.1:7331/healthz"),
        curl_ok("http://127.0.0.1:7331/readyz"),
    )


def git_roots(dev: Path):
    roots = []
    for root, dirs, _files in os.walk(dev):
        if ".git" in dirs:
            roots.append(Path(root))
            dirs[:] = []  # don't descend into sub-repos
    return sorted(roots)


def main():
    cortana_state, retrieval_state = infra_health()
    print(f"INFRA: Cortana={cortana_state}; Retrieval={retrieval_state}")

    roots = git_roots(DEV)
    gaps = []
    stamped = []
    for r in sorted(roots, key=lambda p: p.name):
        agents = r / "AGENTS.md"
        # skip if a hand-written AGENTS.md exists in a direct subdir (nested case)
        if agents.exists():
            continue
        # also skip if any immediate subdir has its own AGENTS.md (dispatcher pattern)
        try:
            nested = any((r / d / "AGENTS.md").exists() for d in os.listdir(r) if (r / d).is_dir())
        except PermissionError:
            continue
        if nested:
            # e.g. NiftyRoyaleFork has NiftyRoyale/AGENTS.md — already covered
            continue
        gaps.append(r)
        # IMMEDIATE FALLBACK STAMP — only for stacks the detector gets RIGHT.
        # C# is ambiguous (Unity vs Azure Functions vs plain .NET) — do NOT auto-stamp
        # it, or we write a wrong manual. TS/Py/Solidity/Rust detection is reliable.
        sig = detect_signals(r)
        lang = primary_lang(sig)
        if lang in ("typescript", "python", "solidity", "rust", "mixed-ts-py") and STAMPER.exists():
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
