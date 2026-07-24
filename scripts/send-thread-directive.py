#!/usr/bin/env -S /Users/amf/.hermes/hermes-agent/venv/bin/python3
"""
send-thread-directive.py — Post a directive as Ye to one or all maintenance threads.

USAGE:
  # All 9 threads (default)
  python3 ~/.hermes/profiles/intern/scripts/send-thread-directive.py "Your message here"

  # Single repo thread
  python3 ~/.hermes/profiles/intern/scripts/send-thread-directive.py "Message" --repo pink-binder

  # Multiple specific repos
  python3 ~/.hermes/profiles/intern/scripts/send-thread-directive.py "Message" --repo pink-binder --repo hermes-infra

The message is prefixed with <@1528604968301494282> (Intern @mention) so
Intern's DISCORD_ALLOW_BOTS=mentions gate admits it.

Requires Ye's global DISCORD_BOT_TOKEN in ~/.hermes/.env.
Uses the gateway venv's Python (>=3.10) for discord_tool.py.
"""

import argparse
import json
import os
import sys

# --- Repo registry ---
# Thread ID -> (org/name, local_path)
THREADS = {
    "1528842363269681304": ("0xPlayerOne/pink-binder", "~/Developer/pink-binder"),
    "1528842513941790741": ("0xPlayerOne/v0-portfolio", "~/Developer/v0-portfolio"),
    "1528842540399464730": (
        "NiftyLeague/nifty-contracts-api",
        "~/Developer/NiftyLeague/nifty-contracts-api",
    ),
    "1528842520723853312": (
        "NiftyLeague/nifty-fe-monorepo",
        "~/Developer/NiftyLeague/nifty-fe-monorepo",
    ),
    "1528842546925797447": (
        "NiftyLeague/nifty-league-subgraph",
        "~/Developer/NiftyLeague/nifty-league-subgraph",
    ),
    "1528842534300946462": (
        "NiftyLeague/nifty-smart-contracts",
        "~/Developer/NiftyLeague/nifty-smart-contracts",
    ),
    "1528842526960910396": ("NiftyLeague/PlayFabConfigs", "~/Developer/NiftyLeague/PlayFabConfigs"),
    "1529478098435706880": ("0xPlayerOne/hermes-infra", "~/Developer/hermes-infra"),
    "1529478099962433647": ("0xPlayerOne/model-gateway", "~/Developer/model-gateway"),
}

# Map repo short-name to thread ID
REPO_TO_THREAD = {name.split("/")[1]: tid for tid, (name, _) in THREADS.items()}

INTERN_MENTION = "<@1528604968301494282>"
SIGNATURE = "\n\n-- **Ye** (directive)"


def resolve_token():
    """Read Ye's global Discord bot token."""
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        print("ERROR: ~/.hermes/.env not found", file=sys.stderr)
        sys.exit(1)
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("DISCORD_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
                if token:
                    return token
    print("ERROR: DISCORD_BOT_TOKEN not found in ~/.hermes/.env", file=sys.stderr)
    sys.exit(1)


def send_directive(token, channel_id, message):
    """Send a single directive message as Ye via discord_tool.py."""
    sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))
    os.environ["DISCORD_BOT_TOKEN"] = token
    from tools.discord_tool import discord_core

    raw = discord_core(action="send_message", channel_id=channel_id, content=message)
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return parsed.get("message_id", "unknown")


def main():
    parser = argparse.ArgumentParser(description="Post a directive as Ye to repo threads")
    parser.add_argument("message", type=str, help="The directive body text")
    parser.add_argument(
        "--repo",
        action="append",
        dest="repos",
        help="Send to specific repo(s) only (omit for all 9)",
    )
    parser.add_argument(
        "--no-mention", action="store_true", help="Skip Intern @mention prefix (not recommended)"
    )
    parser.add_argument("--no-signature", action="store_true", help="Skip Ye signature footer")
    args = parser.parse_args()

    # Determine target threads
    if args.repos:
        targets = {}
        for r in args.repos:
            if r in REPO_TO_THREAD:
                tid = REPO_TO_THREAD[r]
                targets[tid] = THREADS[tid]
            else:
                print(f"WARNING: Unknown repo '{r}'. Skipping.", file=sys.stderr)
                print(f"  Known repos: {', '.join(sorted(REPO_TO_THREAD.keys()))}", file=sys.stderr)
        if not targets:
            print("ERROR: No valid repos specified.", file=sys.stderr)
            sys.exit(1)
    else:
        targets = dict(THREADS)

    # Build message
    msg_parts = []
    if not args.no_mention:
        msg_parts.append(INTERN_MENTION)
    msg_parts.append("")
    msg_parts.append(args.message)
    if not args.no_signature:
        msg_parts.append(SIGNATURE)
    full_msg = "\n".join(msg_parts)

    # Resolve token once
    token = resolve_token()

    # Send
    success = 0
    fail = 0
    for ch_id, (repo_name, _local_path) in targets.items():
        try:
            msg_id = send_directive(token, ch_id, full_msg)
            print(f"OK  {repo_name:45} msg_id={msg_id}")
            success += 1
        except Exception as e:
            print(f"FAIL {repo_name:45} {e}", file=sys.stderr)
            fail += 1

    print(f"\nSent to {success} thread(s)", end="")
    if fail:
        print(f", {fail} failed", file=sys.stderr)
    else:
        print()

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
