#!/usr/bin/env python3
"""Weekly Knowledge Synthesis — closes the learning loop.

Extracts decision / preference / convention language from recent USER messages
in the Hermes session store (state.db), deduplicates against the always-injected
memory layer (MEMORY.md + USER.md + vault memory-facts/), and writes genuinely
NEW durable facts back into MEMORY.md / USER.md (and the vault memory-facts/ dir
for visualization). Best-effort queues each new fact to the local Hindsight
daemon for conversational recall.

DESIGN NOTE (precision > recall):
  The session store mixes real user-authored messages with agent-injected
  system blocks (skill text, plan-mode bullets, cron boilerplate) that are
  occasionally stored under role='user'. We therefore ONLY match explicit,
  high-confidence user directives — first-person imperatives with a real verb
  object. Broad catch-alls like "always ..." are intentionally excluded because
  they capture injected bullet lists, not user intent.

Run with the repository environment loaded:
    "$HERMES_INFRA_VENV/bin/python" "$HERMES_INFRA_DIR/second-brain/scripts/synthesize.py"

Cron: Sunday nights.
"""

import datetime
import glob
import json
import os
import re
import urllib.request

HERMES = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
STATE_DB = os.path.join(HERMES, "state.db")
MEMORY_MD = os.path.join(HERMES, "MEMORY.md")
USER_MD = os.path.join(HERMES, "USER.md")
VAULT = os.path.expanduser(os.environ.get("SECOND_BRAIN_DIR", "~/second-brain"))
MEM_FACTS_DIR = os.path.join(VAULT, "System", "Hermes", "memory-facts")
HINDSIGHT_URL = "http://127.0.0.1:9177/memories"

LOOKBACK_DAYS = 7

# Lines that indicate a message is agent-injected boilerplate, not user intent.
INJECT_MARKERS = (
    "[IMPORTANT",
    "[Triggering",
    "[Replying to",
    "[OUT-OF-BAND",
    "[Background process",
    "You just executed tool calls",
    "Session restored",
    "✨ Session reset",
    "yo 👋 what's good",
)

# High-confidence patterns. Each must capture a COMPLETE, sensible directive.
# Anchored at start of a (cleaned) user line to avoid mid-list fragments.
PATTERNS = [
    # never commit env files (explicit guard)
    (
        r"^\s*never\s+commit\s+([\w./-]+(?:\s+files?)?)",
        lambda m: (
            f"GUARD: Never commit {m.group(1).strip()}. Enforce in git hooks / agent guardrails."
        ),
        USER_MD,
    ),
    # remove X ... unnecessary / we don't need
    (
        r"^\s*remove\s+([\w./-]+(?:\s+and\s+[\w./-]+)*)\b.*?(unnecessary|not needed|we (?:already|don'?t)|no longer)",
        lambda m: f"CONV-CLEANUP: Remove {m.group(1).strip()} — unnecessary per user.",
        MEMORY_MD,
    ),
    # replace old references of X with Y
    (
        r"^\s*(?:yeah\s+)?any\s+old\s+references?\s+(?:of\s+)?(?:to\s+)?([\w/-]+)\s+should\s+be\s+(?:replaced|removed)",
        lambda m: f"CONV-NAMING: Replace stale '{m.group(1)}' references (user-directed cleanup).",
        MEMORY_MD,
    ),
    # delete the clone / we already have one
    (
        r"^\s*(delete the clone|we already have (?:one|this|that))",
        lambda m: (
            "PREFERENCE-NODEDUP: Do NOT create duplicate repo clones — check the configured source root first; remove redundant clones."
        ),
        USER_MD,
    ),
    # explicit model/LLM direction
    (
        r"^\s*(?:if\s+[\w]+\s+needs\s+an\s+llm|point\s+it\s+at|use|try)\b.*?\b(kilo[ -]?auto[/-]?free|kilo\s+free|hy3|qwen3?[- ]?embedding[\w./:-]*|tei|ollama)\b",
        lambda m: (
            f"DECISION-MODEL: User directed embedding/LLM to use '{m.group(1)}' where applicable."
        ),
        MEMORY_MD,
    ),
    # keep working to get TEI metal working
    (
        r"^\s*keep\s+working\s+to\s+get\s+(tei|[\w]+)\s+metal\s+working",
        lambda m: (
            "INFRA-DIR: Push TEI (Qwen3-Embedding on Metal) to work flawlessly on Apple Silicon — failures are config, not hardware."
        ),
        MEMORY_MD,
    ),
    # explicit first-person preference
    (
        r"^\s*i\s+prefer\s+(.{5,140}?)(?:[.\n]|$)",
        lambda m: f"PREFERENCE: {m.group(1).strip().capitalize()}.",
        USER_MD,
    ),
]


def get_recent_user_messages():
    import sqlite3

    if not os.path.exists(STATE_DB):
        return []
    cutoff = datetime.datetime.utcnow().timestamp() - LOOKBACK_DAYS * 86400
    con = sqlite3.connect(STATE_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT content FROM messages WHERE role='user' AND timestamp > ? AND length(content) > 20 ORDER BY timestamp ASC",
        (cutoff,),
    )
    msgs = [r["content"] for r in cur.fetchall()]
    con.close()
    return msgs


def clean_message(msg):
    lines = []
    for ln in msg.splitlines():
        if any(ln.startswith(m) for m in INJECT_MARKERS):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def extract_candidates(messages):
    out = []
    seen_norm = set()
    for msg in messages:
        clean = clean_message(msg)
        if len(clean) < 15:
            continue
        for pat, fmt, target in PATTERNS:
            for m in re.finditer(pat, clean, re.IGNORECASE | re.MULTILINE):
                fact = fmt(m)
                # quality gate: no dangling fragments
                if len(fact) < 25 or fact.rstrip().endswith(".."):
                    continue
                norm = re.sub(r"\s+", " ", fact).strip().lower()
                if norm in seen_norm:
                    continue
                seen_norm.add(norm)
                out.append((fact, target, clean[:120]))
    return out


def load_existing_facts():
    existing = set()
    for path in (MEMORY_MD, USER_MD):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as source:
                lines = source.read().splitlines()
            for line in lines:
                s = line.strip().lstrip("§").strip()
                if s:
                    existing.add(re.sub(r"\s+", " ", s).lower()[:120])
    if os.path.isdir(MEM_FACTS_DIR):
        for f in glob.glob(os.path.join(MEM_FACTS_DIR, "*.md")):
            try:
                with open(f, encoding="utf-8") as source:
                    body = source.read().split("---", 2)[-1]
                for line in body.splitlines():
                    s = line.strip()
                    if s:
                        existing.add(re.sub(r"\s+", " ", s).lower()[:120])
            except Exception:
                continue
    return existing


def is_new(fact, existing):
    return re.sub(r"\s+", " ", fact).strip().lower()[:120] not in existing


def append_fact(path, fact):
    with open(path, encoding="utf-8") as source:
        txt = source.read()
    if not txt.endswith("\n"):
        txt += "\n"
    txt = txt.rstrip("\n") + f"\n§\n{fact}\n"
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as output:
        output.write(txt)
    os.replace(tmp, path)


def write_memory_fact_file(fact):
    os.makedirs(MEM_FACTS_DIR, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "-", fact[:40].lower()).strip("-") or "fact"
    fn = os.path.join(MEM_FACTS_DIR, f"synth-{datetime.date.today()}-{safe}.md")
    n = 1
    while os.path.exists(fn):
        fn = fn.replace(".md", f"-{n}.md")
        n += 1
    with open(fn, "w", encoding="utf-8") as output:
        output.write(
            f"---\ntype: memory-fact\nsource: weekly-synthesis\ndate: {datetime.date.today()}\n---\n\n{fact}\n"
        )


def queue_hindsight(fact):
    payload = json.dumps({"content": fact, "type": "observation"}).encode()
    req = urllib.request.Request(
        HINDSIGHT_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status in (200, 201)
    except Exception:
        return False


def main():
    messages = get_recent_user_messages()
    candidates = extract_candidates(messages)
    existing = load_existing_facts()

    new_facts = []
    for fact, target, _src in candidates:
        if is_new(fact, existing):
            new_facts.append((fact, target))
            existing.add(re.sub(r"\s+", " ", fact).strip().lower()[:120])

    hs_ok = hs_fail = 0
    for fact, target in new_facts:
        append_fact(target, fact)
        write_memory_fact_file(fact)
        if queue_hindsight(fact):
            hs_ok += 1
        else:
            hs_fail += 1

    print(f"USER messages scanned (last {LOOKBACK_DAYS}d): {len(messages)}")
    print(f"candidate facts extracted: {len(candidates)}")
    print(f"NEW durable facts synthesized: {len(new_facts)}")
    for fact, target in new_facts:
        print(f"  + [{os.path.basename(target)}] {fact}")
    print(f"Hindsight queued: {hs_ok} ok / {hs_fail} failed (daemon may be unreachable)")


if __name__ == "__main__":
    main()
