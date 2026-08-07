#!/usr/bin/env python3
"""
stack_detect.py — repository stack detection (shared module).

Single source of truth for detecting a repo's primary language(s) and stack
signals. Used by repo_standardize.py, mise_toml_gen.py, and agents_md_watchdog.py.

Usage:
    from stack_detect import detect_signals, primary_lang, detect_stack
    sig = detect_signals("/path/to/repo")
    lang = primary_lang(sig)
    # or all-in-one:
    lang, sig = detect_stack("/path/to/repo")
"""

import os
from pathlib import Path

IGNORED_DIRS = frozenset(
    {
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
    }
)


def detect_signals(path: Path) -> dict:
    """Walk a repo and return a dict of stack signal counts."""
    sig = {
        "ts": 0,
        "py": 0,
        "rust": 0,
        "cs": 0,
        "sol": 0,
        "unity": False,
        "bun_lock": False,
        "npm_lock": False,
        "uv": False,
        "cargo": False,
        "sol_tool": None,
    }
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for f in files:
            p = f.lower()
            if p.endswith(".sol"):
                sig["sol"] += 1
            elif p in ("foundry.toml", "hardhat.config.ts", "hardhat.config.js"):
                # Solidity toolchain configs identify the tool even though they
                # are not .sol files; detect them separately so sol_tool works.
                sig["sol_tool"] = p
            elif p == "package.json":
                sig["ts"] += 1
                if "Assets" in root.split(os.sep):
                    sig["unity"] = True
            elif p in ("pyproject.toml", "requirements.txt"):
                sig["py"] += 1
            elif p == "cargo.toml":
                sig["rust"] += 1
                sig["cargo"] = True
            elif p.endswith(".cs"):
                sig["cs"] += 1
            elif p in {"bun.lockb", "bun.lock"}:
                sig["bun_lock"] = True
            elif p == "package-lock.json":
                sig["npm_lock"] = True
            elif p == "uv.lock":
                sig["uv"] = True
            elif p.endswith(".csproj"):
                sig["cs"] += 1
    return sig


def primary_lang(sig: dict) -> str:
    """Return the primary language name from stack signals."""
    if sig["rust"] > 0:
        return "rust"
    if sig["sol"] > 0:
        return "solidity"
    if sig["unity"] or (sig["cs"] > sig["ts"] and sig["cs"] > 0):
        return "unity-cs"
    if sig["ts"] > 0 and sig["py"] == 0:
        return "typescript"
    if sig["py"] > 0 and sig["ts"] == 0:
        return "python"
    if sig["ts"] > 0 and sig["py"] > 0:
        return "mixed-ts-py"
    if sig["cs"] > 0:
        return "unity-cs"
    return "unknown"


def detect_stack(path: Path) -> tuple[str, dict]:
    """Convenience: detect signals and return (language, signals)."""
    sig = detect_signals(path)
    return primary_lang(sig), sig
