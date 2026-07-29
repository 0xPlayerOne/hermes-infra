#!/usr/bin/env python3
"""
mise_toml_gen.py — generate a repo-local .mise.toml from detected stack.

Mirrors the agentic-dev-constitution stack detection. Each repo gets ONLY the
tools it actually needs, pinned to the versions already on the global toolchain
(Node 24.18.0, Python 3.11.15, Rust 1.97.1) so `mise install` is a no-op when
those are already global — but declares the pin for reproducibility.

Usage:
  mise_toml_gen.py <repo> [--write]   # print (or --write) the .mise.toml
"""
import sys
from pathlib import Path

from stack_detect import detect_signals, primary_lang

# Pinned versions (must match global toolchain)
NODE = "24.18.0"
PY = "3.11.15"
RUST = "1.97.1"


def toml_for(stack: str) -> str:
    lines = ["[tools]", ""]
    if stack in ("typescript", "solidity", "mixed-ts-py"):
        lines.append(f'node = "{NODE}"')
    if stack in ("python", "mixed-ts-py"):
        lines.append(f'python = "{PY}"')
    if stack == "rust":
        lines.append(f'rust = "{RUST}"')
    # Unity/C# and unknown: no mise-managed tools (Unity uses its own editor;
    # Azure Functions uses global dotnet). Leave tools empty.
    if len(lines) == 2:
        lines.append("# no mise-managed tools for this stack (Unity/dotnet/C# use globals)")
    lines.append("")
    lines.append("[settings]")
    lines.append("experimental = true")
    lines.append("")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    write = "--write" in args
    args = [a for a in args if a != "--write"]
    if not args:
        print("usage: mise_toml_gen.py <repo> [--write]", file=sys.stderr)
        sys.exit(1)
    repo = Path(args[0]).resolve()
    if not repo.is_dir():
        print(f"ERROR: {repo} not a dir", file=sys.stderr)
        sys.exit(1)
    stack = primary_lang(detect_signals(repo))
    content = toml_for(stack)
    if write:
        out = repo / ".mise.toml"
        if out.exists():
            print(f"SKIP (exists): {out}")
        else:
            out.write_text(content)
            print(f"WROTE: {out}  [{stack}]")
    else:
        print(f"# {repo.name} -> {stack}")
        print(content)


if __name__ == "__main__":
    main()
