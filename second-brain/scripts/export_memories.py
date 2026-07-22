#!/usr/bin/env python3
"""Second-Brain Exporter — mirrors Hermes' database-backed memories into the
Obsidian vault as markdown, so everything is visualizable.

What it exports:
  - memory-tool facts  -> System/Hermes/memory-facts/<n>.md
  - Hindsight observations -> System/Hermes/hindsight/<id>.md

Live markdown (MEMORY.md, USER.md, skills/) are SYMLINKED — not exported.

Run: python export_memories.py
Cron: wire to daily run after the code-indexer.
"""

import datetime
import glob
import json
import os

VAULT = os.path.expanduser(os.environ.get("SECOND_BRAIN_DIR", "~/second-brain"))
WORK_SECTION = os.environ.get("WORK_SECTION", "Work")
PERSONAL_SECTION = os.environ.get("PERSONAL_SECTION", "Personal")
SPECIAL_SECTION = os.environ.get("SPECIAL_SECTION", "Special")
HERMES_DIR = os.path.join(VAULT, "System", "Hermes")
MEM_FACTS_DIR = os.path.join(HERMES_DIR, "memory-facts")
HINDSIGHT_DIR = os.path.join(HERMES_DIR, "hindsight")


def write_vault_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def export_memory_facts():
    """Dump the `memory` tool store into individual markdown files."""
    os.makedirs(MEM_FACTS_DIR, exist_ok=True)
    mem_root = os.path.expanduser("~/.hermes/memory")
    count = 0
    if os.path.isdir(mem_root):
        for f in glob.glob(os.path.join(mem_root, "*.json")):
            try:
                with open(f, encoding="utf-8") as source:
                    data = json.load(source)
            except Exception:
                continue
            entries = data if isinstance(data, list) else [data]
            for i, e in enumerate(entries):
                content = e.get("content") if isinstance(e, dict) else str(e)
                target = e.get("target", "general") if isinstance(e, dict) else "general"
                fn = os.path.join(
                    MEM_FACTS_DIR, f"{os.path.basename(f).replace('.json', '')}-{i}.md"
                )
                with open(fn, "w", encoding="utf-8") as out:
                    out.write(
                        f"---\ntype: memory-fact\ntarget: {target}\nsource: hermes-memory-tool\ndate: {datetime.date.today()}\n---\n\n{content}\n"
                    )
                count += 1
    return count


def export_hindsight():
    """Export Hindsight observations from the local daemon as markdown."""
    os.makedirs(HINDSIGHT_DIR, exist_ok=True)
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:9177/v1/default/banks/hermes/memories/list?limit=200"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        obs = data if isinstance(data, list) else data.get("memories", [])
        n = 0
        for o in obs:
            oid = o.get("id") or o.get("oid") or f"h{n}"
            text = o.get("content") or o.get("text") or o.get("observation") or ""
            if not text.strip():
                continue
            fn = os.path.join(HINDSIGHT_DIR, f"{oid}.md")
            with open(fn, "w", encoding="utf-8") as out:
                out.write(
                    f"---\ntype: hindsight-observation\nid: {oid}\ndate: {datetime.date.today()}\n---\n\n{text}\n"
                )
            n += 1
        return n
    except Exception as e:
        with open(os.path.join(HINDSIGHT_DIR, "_STATUS.md"), "w", encoding="utf-8") as out:
            out.write(f"Hindsight export skipped: {type(e).__name__}: {e}\n")
        return 0


def write_dashboard(mf, hs):
    dash = os.path.join(VAULT, "DASHBOARD.md")

    # dynamic counts from the vault
    def cnt(sub):
        d = os.path.join(VAULT, sub)
        return len(glob.glob(os.path.join(d, "*.md"))) if os.path.isdir(d) else 0

    sources = [
        (f"{WORK_SECTION}/Calendar/", "Calendar — work"),
        (f"{PERSONAL_SECTION}/Calendar/", "Calendar — personal"),
        (f"{WORK_SECTION}/Email/", "Email — work"),
        (f"{PERSONAL_SECTION}/Email/", "Email — personal"),
        (f"{WORK_SECTION}/Sheets/", "Sheets — work"),
        (f"{PERSONAL_SECTION}/Sheets/", "Sheets — personal"),
        (f"{WORK_SECTION}/Drive/", "Drive — work"),
        (f"{PERSONAL_SECTION}/Drive/", "Drive — personal"),
        (f"{WORK_SECTION}/Meetings/", "Meeting transcripts — work"),
        (f"{PERSONAL_SECTION}/Meetings/", "Meeting transcripts — personal"),
        (f"{WORK_SECTION}/Projects/", "Work repos + READMEs (`languages:` tagged)"),
        (f"{PERSONAL_SECTION}/Projects/", "Personal repos + READMEs (`languages:` tagged)"),
        (f"{WORK_SECTION}/Business/", "Work business knowledge"),
        (f"{SPECIAL_SECTION}/Sheets/", "Special-topic sheets (any account)"),
        (f"{SPECIAL_SECTION}/Notes/", "Special-topic notes (any account)"),
        (f"{PERSONAL_SECTION}/Notes/", "Apple Notes (osascript)"),
        (f"{PERSONAL_SECTION}/Documents/", "Local Documents (PDF text)"),
    ]
    src_lines = "\n".join(f"- `{s}` — {desc}: **{cnt(s)}** files" for s, desc in sources)
    with open(dash, "w", encoding="utf-8") as out:
        out.write(f"""# 🧠 Second Brain — Dashboard

_Generated {datetime.datetime.now().isoformat()}_

## Live (symlinked, always current) — in `System/Hermes/`
- [[System/Hermes/MEMORY]] — agent environment + conventions
- [[System/Hermes/USER]] — who you are
- [[System/Hermes/SOUL]] — agent identity / persona
- [[System/Hermes/skills]] — reusable procedures (folder)

## Agent meta — `System/Hermes/`
- `System/Hermes/hindsight/` — Hindsight observations: **{hs}** files
- `System/Hermes/memory-facts/` — memory-tool facts: **{mf}** files
- Sync scripts: `sync.py`, `google_sync.py`, `export_memories.py`
- Architecture: [[System/Assistant/architecture]] — how the pipeline works

## Synced data sources
{src_lines}

## Vault structure (PARA)
- `Daily/` — daily notes (YYYY-MM-DD.md, append-only)
- `System/Assistant/` — `context.md`, `preferences.md`, `environment.md`, `logs/issues-fixes-log.md`
- `People/` — contacts and relationships
- `Inbox/` — unclassified incoming (file later)
- `{WORK_SECTION}/` — work: Calendar/, Email/, Sheets/, Drive/, Meetings/, Projects/, Business/
- `{PERSONAL_SECTION}/` — personal: Calendar/, Email/, Sheets/, Drive/, Meetings/, Projects/, Notes/, Documents/
- `{SPECIAL_SECTION}/` — configured special-topic content
- `System/Hermes/` — agent meta (symlinks + sync scripts + hindsight/memory-facts)
- Account and keyword routing are configured through the local environment.

## How to use
1. Open this vault in Obsidian.
2. Use **Graph View** to see connections between memories, skills, repos, meetings, people.
3. Daily cron (`Second-Brain Sync` @ 4:40am) re-runs `System/Hermes/sync.py` incrementally.
4. `export_memories.py` regenerates this dashboard + hindsight/memory-facts.
5. MEMORY.md / USER.md / SOUL.md / skills are live symlinks — edit in Hermes or here.
6. Log operational events to `Daily/YYYY-MM-DD.md` ## Log; technical fixes to `System/Assistant/logs/issues-fixes-log.md`.

## Architecture
```
hermes/
  MEMORY.md ──┐
  USER.md   ──┼─ (symlinked, live)
  SOUL.md   ──┘
  skills/       (symlinked, live)
  {WORK_SECTION}/   {PERSONAL_SECTION}/   {SPECIAL_SECTION}/
  People/  System/  Daily/
  System/Hermes/  ── sync scripts + agent meta (MEMORY/USER/SOUL/skills symlinks, hindsight/, memory-facts/)
   Sync scripts in System/Hermes/: sync.py + google_sync.py + export_memories.py
  Data sources (incremental): github/ apple-notes/ documents/ drive/ calendar/ gmail/ sheets/
  └─ (routed into configured work, personal, and special sections)
```
""")


if __name__ == "__main__":
    mf = export_memory_facts()
    hs = export_hindsight()
    write_dashboard(mf, hs)
    print(f"exported: memory-facts={mf} hindsight={hs}")
