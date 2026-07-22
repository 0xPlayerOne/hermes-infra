#!/usr/bin/env python3
"""Second-Brain unified sync orchestrator.

Runs ALL sources into the configured Obsidian vault ($SECOND_BRAIN_DIR) + chroma:
  github/        — repos + READMEs (gh CLI) -> Work/Projects + Personal/Projects
  apple-notes/   — Notes.app (osascript; blank notes auto-skipped) -> routed by folder/keyword
  documents/     — $DOCUMENTS_DIR (PDF text) -> Personal/Documents or Work/Business
  Google Drive/Email/Calendar/Sheets (via google_sync.py API) -> routed by KEYWORD per file:
      configured special keywords -> Special, work keywords -> Work, else -> Personal
  hindsight/     — Hindsight observations (in System/Hermes/)
  memory-facts/  — Hermes memory facts + Hindsight (export_memories.py, in System/Hermes/)

CRITICAL SAFETY: route ALL destructive shell commands through ~/.hermes/guardian.sh --confirm.
"""
import os, re, glob, datetime, subprocess, shutil, time, json
from pathlib import Path

HERMES = Path(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")))
VAULT = os.path.expanduser(os.environ.get("SECOND_BRAIN_DIR", "~/second-brain"))
WORK_SECTION = os.environ.get("WORK_SECTION", "Work")
PERSONAL_SECTION = os.environ.get("PERSONAL_SECTION", "Personal")
SPECIAL_SECTION = os.environ.get("SPECIAL_SECTION", "Special")
CHROMA_DIR = HERMES / "second-brain-chroma"
# Embedding backend: TEI (Qwen/Qwen3-Embedding-0.6B, 1024-dim) on http://localhost:6999/v1
# Ollama is REMOVED (caused Jetsam crash 2026-07-19). Use TEI for all embeddings.
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
TEI_EMBED_URL = os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:6999/v1/embeddings")

# source subdirs in vault
DIRS = {
    "github": os.path.join(VAULT, WORK_SECTION, "Projects"),
    "notes": os.path.join(VAULT, PERSONAL_SECTION, "Notes"),
    "docs": os.path.join(VAULT, PERSONAL_SECTION, "Documents"),
    "personal-drive": os.path.join(VAULT, PERSONAL_SECTION, "Drive"),
    "meetings": os.path.join(VAULT, WORK_SECTION, "Meetings"),
    "calendar": os.path.join(VAULT, WORK_SECTION, "Calendar"),
    "gmail": os.path.join(VAULT, WORK_SECTION, "Email"),
    "sheets": os.path.join(VAULT, WORK_SECTION, "Sheets"),
    "hindsight": os.path.join(VAULT, "System", "Hermes", "hindsight"),
    "memory": os.path.join(VAULT, "System", "Hermes", "memory-facts"),
}

VAULT_SPECIAL = Path(os.path.join(VAULT, SPECIAL_SECTION))
VAULT_WORK = Path(os.path.join(VAULT, WORK_SECTION))

def log(m):
    print(f"[sync] {m}", flush=True)


def write_vault_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


# Routing is centralized in google_sync.py.


class _NullCollection:
    """No-op chroma stand-in used when the real index is corrupt/unavailable.
    Vault files are still written by callers; vector indexing is skipped."""
    def upsert(self, *a, **k):
        pass
    def delete(self, *a, **k):
        pass
    def count(self):
        return 0
    def get(self, *a, **k):
        return {}


def get_col():
    import chromadb
    from chromadb.config import Settings
    try:
        c = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False, allow_reset=True))
        return c.get_or_create_collection(name="second_brain")
    except Exception:
        # corrupt/unavailable index — return null so the Second Brain (vault)
        # still syncs fully; chroma is a separate, repairable layer.
        return _NullCollection()


def embed(texts):
    """Embed a list of texts via TEI (Qwen/Qwen3-Embedding-0.6B, 1024-dim).
    Batches with short retry; returns list (None per text on failure)."""
    import urllib.request, json, time
    out_embs = []
    BATCH = 32  # TEI handles larger batches efficiently
    for i in range(0, len(texts), BATCH):
        group = texts[i:i + BATCH]
        embs = None
        for attempt in range(3):
            try:
                payload = json.dumps({"model": EMBED_MODEL, "input": group}).encode()
                req = urllib.request.Request(TEI_EMBED_URL, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.load(resp)
                    embs = [d["embedding"] for d in data["data"]]
                    if embs:
                        break
            except Exception as e:
                if attempt == 0:
                    log(f"[embed] attempt failed ({e}); retrying...")
                time.sleep(2)
        if embs:
            out_embs.extend(embs)
        else:
            out_embs.extend([None] * len(group))
    return out_embs


def _ensure_tei():
    """Pre-flight: verify TEI embed endpoint is healthy before sync starts."""
    import urllib.request, json
    try:
        payload = json.dumps({"model": EMBED_MODEL, "input": ["health"]}).encode()
        req = urllib.request.Request(TEI_EMBED_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
            if data.get("data") and len(data["data"][0].get("embedding", [])) == 1024:
                log("[tei] healthy — 1024-dim embeddings ready")
                return True
    except Exception as e:
        log(f"[tei] health check failed: {e}")
    return False


def embed_and_store(col, source, title, body, vault_md=None, vault_dir=None):
    if vault_md:
        d = vault_dir or DIRS.get(source, VAULT)
        os.makedirs(d, exist_ok=True)
        safe = "".join(c for c in title if c.isalnum() or c in " -_.")[:60]
        write_vault_file(os.path.join(d, f"{safe}.md"), vault_md)
    chunks = [body[i:i + 1500] for i in range(0, len(body), 1200)]
    chunks = [c for c in chunks if c.strip()]
    if not chunks:
        return
    embs = embed(chunks)
    ids, docs, metas, good_embs = [], [], [], []
    base = f"{source}:{title}"
    for i, (ch, e) in enumerate(zip(chunks, embs)):
        if e is None:
            continue
        cid = f"{base}#{i}"
        ids.append(cid); docs.append(ch); good_embs.append(e)
        metas.append({"source": source, "title": title, "chunk": i})
    if ids:
        try:
            col.upsert(ids=ids, documents=docs, embeddings=good_embs, metadatas=metas)
        except Exception as e:
            # chroma may be corrupt/unavailable — vault file is already written,
            # so the Second Brain is complete; skip the vector index silently.
            log(f"  [chroma] upsert skipped: {type(e).__name__}")


# ---------- GitHub ----------
def _gh_api(path, jq=None):
    cmd = ["gh", "api", path, "--paginate"]
    if jq:
        cmd += ["--jq", jq]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return res.stdout if res.returncode == 0 else None
    except Exception:
        return None


def _gh_languages(owner, name):
    """Fetch repo languages as a comma-separated string (e.g. 'TypeScript, Solidity')."""
    raw = _gh_api(f"repos/{owner}/{name}/languages", jq="keys | join(\", \")")
    return (raw or "").strip()


def sync_github(col):
    log("GitHub: fetching repos + metadata + READMEs + markdown docs")
    today = datetime.date.today().isoformat()
    # User repos plus an optional configured work organization, excluding archived.
    names = []
    work_owner = os.environ.get("WORK_GITHUB_OWNER", "").strip()
    sources = ["user/repos?affiliation=owner,collaborator"]
    if work_owner:
        sources.append(f"orgs/{work_owner}/repos?per_page=100")
    for src in sources:
        raw = _gh_api(src, jq=".[] | select(.archived | not) | .full_name")
        if raw:
            names += [n for n in raw.split("\n") if n.strip()]
    if not names:
        log("  GitHub: no repos (gh auth?)")
        return
    n = 0
    for idx, owner_name in enumerate(names[:80], 1):
        try:
            owner, name = owner_name.split("/", 1)
            # Route by configured special/work keywords, then account ownership.
            import google_sync as _gs
            _route = _gs.route_text(name, "")
            if _route == "special":
                vdir = os.path.join(VAULT, SPECIAL_SECTION, "Projects")
            elif owner == work_owner or _route == "work":
                vdir = os.path.join(VAULT, WORK_SECTION, "Projects")
            else:
                vdir = os.path.join(VAULT, PERSONAL_SECTION, "Projects")
            # incremental: skip if already synced today
            safe = "".join(c for c in name if c.isalnum() or c in " -_.")[:60]
            existing = os.path.join(vdir, f"{safe}.md")
            if os.path.exists(existing) and f"date: {today}" in open(existing, encoding="utf-8").read():
                continue
            readme = _gh_api(f"repos/{owner}/{name}/readme", jq=".content")
            if not readme:
                continue
            import base64
            try:
                body = base64.b64decode(readme).decode("utf-8", "ignore")[:2500]
            except Exception:
                body = ""
            if not body.strip():
                continue
            langs = _gh_languages(owner, name)
            vault_md = (f"---\nsource: github\ntitle: {name}\nrepo: {owner_name}\n"
                        f"languages: {langs}\n"
                        f"date: {today}\n---\n\n{body}\n")
            embed_and_store(col, "github", name, body, vault_md=vault_md, vault_dir=vdir)
            n += 1
            if idx % 10 == 0:
                log(f"  GitHub: {idx} repos processed, {n} with READMEs")
        except Exception:
            continue
    log(f"  GitHub: {n} repos synced (with READMEs + markdown)")


# ---------- Apple Notes ----------
def sync_apple_notes(col):
    log("Apple Notes: via osascript plaintext (hard-kill guarded)")
    try:
        cnt_res = subprocess.run(
            ["timeout", "30", "osascript", "-e", 'tell application "Notes" to count notes'],
            capture_output=True, text=True, timeout=40)
        if cnt_res.returncode != 0:
            log(f"  Apple Notes failed: {cnt_res.stderr[:80]}")
            return
        try:
            count = int(cnt_res.stdout.strip())
        except Exception:
            count = 0
        n = 0
        for i in range(1, min(count, 100) + 1):
            # fetch plaintext + folder name for this note
            script = (f'tell application "Notes"\n'
                      f'  set n to note {i}\n'
                      f'  set ptext to plaintext of n\n'
                      f'  try\n'
                      f'    set fldr to name of container of n\n'
                      f'  on error\n'
                      f'    set fldr to ""\n'
                      f'  end try\n'
                      f'  return ptext & "\\n---FOLDER---" & fldr\n'
                      f'end tell')
            proc = None
            try:
                proc = subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    start_new_session=True)
                try:
                    out, _ = proc.communicate(timeout=8)
                    text = out
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), 15)
                    except Exception:
                        pass
                    proc.wait(timeout=5)
                    text = ""
            except Exception:
                text = ""
            if "---FOLDER---" in text:
                body_raw, folder = text.split("---FOLDER---", 1)
                folder = folder.strip()
            else:
                body_raw, folder = text, ""
            lines = body_raw.split("\n", 1)
            title = lines[0].strip()[:60] or f"note-{i}"
            body = lines[1] if len(lines) > 1 else body_raw
            # skip blank/attachment-only notes
            if not body.strip() or body.strip() in ("￼",):
                continue
            today = datetime.date.today().isoformat()
            # Route folder, title, and content through the canonical router.
            import google_sync as _gs
            route = _gs.route_text(f"{folder} {title}", body[:3000])
            notes_dir = (VAULT_SPECIAL / "Notes") if route == "special" else \
                        (VAULT_WORK / "Notes") if route == "work" else \
                        (os.path.join(VAULT, PERSONAL_SECTION, "Notes", folder.replace("/", "-").strip())
                         if folder else os.path.join(VAULT, PERSONAL_SECTION, "Notes"))
            # incremental: skip if already synced today
            safe = "".join(c for c in title if c.isalnum() or c in " -_.")[:60]
            existing = os.path.join(notes_dir, f"{safe}.md")
            if os.path.exists(existing):
                try:
                    if f"date: {today}" in open(existing, encoding="utf-8").read():
                        continue  # up-to-date today
                except Exception:
                    pass
            vault_md = (
                f"---\nsource: notes\ntitle: {title}\n"
                f"folder: {folder}\ndate: {today}\n---\n\n{body}\n"
            )
            embed_and_store(col, "notes", title, body, vault_md=vault_md, vault_dir=notes_dir)
            n += 1
        log(f"  Apple Notes: {n} synced")
    except Exception as e:
        log(f"  Apple Notes failed: {e}")


# ---------- Local Documents (PDF extraction) ----------
def extract_pdf(fp, max_chars=6000):
    """Extract text from a PDF via pdfplumber (falls back to placeholder on failure)."""
    try:
        import pdfplumber
        chunks = []
        with pdfplumber.open(fp) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
                if sum(len(c) for c in chunks) >= max_chars:
                    break
        text = "\n".join(chunks).strip()
        return text[:max_chars] if text else f"[PDF: {os.path.basename(fp)} — no extractable text]"
    except Exception as e:
        return f"[PDF: {os.path.basename(fp)} — extraction failed: {type(e).__name__}]"


def sync_documents(col):
    log("Local Documents: scanning + PDF extraction")
    docs_root = os.path.expanduser(os.environ.get("DOCUMENTS_DIR", "~/Documents"))
    exts = {".md", ".txt", ".pdf", ".docx", ".rtf", ".pages"}
    n = 0
    for root, dirs, files in os.walk(docs_root):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules"}]
        for f in files:
            if os.path.splitext(f)[1].lower() not in exts:
                continue
            fp = os.path.join(root, f)
            if os.path.getsize(fp) > 500_000:
                continue
            try:
                if f.endswith(".pdf"):
                    body = extract_pdf(fp)
                elif f.endswith((".docx", ".rtf", ".pages")):
                    body = f"[Binary: {f} — text extraction not supported]"
                else:
                    body = open(fp, errors="ignore").read()[:6000]
            except Exception:
                continue
            title = os.path.splitext(f)[0]
            vault_md = (
                f"---\nsource: docs\ntitle: {title}\nfile: {f}\n"
                f"date: {datetime.date.today().isoformat()}\n---\n\n{body}\n"
            )
            # Route work-keyword documents to Work/Business; otherwise Personal/Documents.
            import google_sync as _gs
            _route = _gs.route_text(title, body[:3000])
            _vdir = os.path.join(VAULT, WORK_SECTION, "Business") if _route == "work" else DIRS["docs"]
            embed_and_store(col, "docs", title, body, vault_md=vault_md, vault_dir=_vdir)
            n += 1
            if n >= 200:
                break
        if n >= 200:
            break
    log(f"  Documents: {n} synced")


# ---------- Google (via google_sync.py) ----------
def sync_google_drive(col):
    log("Google Drive: via google_sync.py — configured keyword routing per file")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "google_sync", os.path.join(os.path.dirname(__file__), "google_sync.py"))
        gs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gs)
        for acc in gs.ACCOUNTS:
            if not gs.get_creds(acc):
                log(f"  google {acc}: no creds (skip)")
                continue
            if acc == gs.WORK_ACCOUNT:
                base_dir = gs.VAULT_WORK_DRIVE
            elif acc == gs.SPECIAL_ACCOUNT:
                base_dir = gs.VAULT_SPECIAL_DRIVE
            else:
                base_dir = gs.VAULT_PERS_DRIVE
            gs.sync(acc, drive_vault_dir=base_dir, drive_source="google-drive")
            try:
                dlist = gs.gapi_get(
                    "https://www.googleapis.com/drive/v3/drives?pageSize=10",
                    gs.get_creds(acc), acc, f"{acc}/drives")
                for d in (dlist or {}).get("drives", []):
                    gs.sync(acc, drive_vault_dir=base_dir, drive_source="google-drive",
                            drive_id=d["id"])
            except Exception as e:
                log(f"  google {acc} shared drives skip: {e}")
            # Calendar & Gmail still route by account (they don't have file-level keyword routing)
            cal_dir = gs.VAULT_CALENDAR if acc == gs.WORK_ACCOUNT else gs.VAULT_PERS_CALENDAR if acc == gs.PERSONAL_ACCOUNT else gs.VAULT_SPECIAL_CAL
            mail_dir = gs.VAULT_GMAIL if acc == gs.WORK_ACCOUNT else gs.VAULT_PERS_EMAIL if acc == gs.PERSONAL_ACCOUNT else gs.VAULT_SPECIAL_MAIL
            gs.sync_calendar(acc, vault_dir=cal_dir, source="google-calendar")
            gs.sync_gmail(acc, vault_dir=mail_dir, source="google-gmail")
            # Sheets are synced during Drive walk (see _drive_walk) — no separate call needed
    except Exception as e:
        log(f"  Google Drive skipped: {e}")


# ---------- Hindsight ----------
def sync_hindsight(col):
    log("Hindsight: via local daemon API")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:9177/memories?limit=200")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        obs = data if isinstance(data, list) else data.get("memories", [])
        n = 0
        for o in obs:
            oid = o.get("id") or o.get("oid") or f"h{n}"
            text = o.get("content") or o.get("text") or o.get("observation") or ""
            if not text.strip():
                continue
            write_vault_file(
                os.path.join(DIRS["hindsight"], f"{oid}.md"),
                f"---\ntype: hindsight-observation\nid: {oid}\ndate: {datetime.date.today()}\n---\n\n{text}\n")
            n += 1
        log(f"  Hindsight: {n} observations")
    except Exception as e:
        with open(os.path.join(DIRS["hindsight"], "_STATUS.md"), "w") as out:
            out.write(f"Hindsight export skipped: {type(e).__name__}: {e}\n")
        log(f"  Hindsight skipped: {e}")


# ---------- Memory facts (delegate) ----------
def _sync_memory_facts(col=None):
    log("Memory facts: via export_memories.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "export_memories", os.path.join(os.path.dirname(__file__), "export_memories.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.export_memory_facts()
        mod.export_hindsight()
        log("  Memory facts: exported")
    except Exception as e:
        log(f"  Memory facts errored: {e}")


def _pause_hindsight_daemon():
    subprocess.run(["launchctl", "unload",
                    os.path.expanduser(os.environ.get(
                        "HERMES_LAUNCH_AGENTS_DIR", "~/Library/LaunchAgents")) +
                    "/com.hermes.hindsight.plist"],
                   capture_output=True)
    subprocess.run(["pkill", "-f", "hindsight-api"], capture_output=True)


def _resume_hindsight_daemon():
    subprocess.run(["launchctl", "load",
                    os.path.expanduser(os.environ.get(
                        "HERMES_LAUNCH_AGENTS_DIR", "~/Library/LaunchAgents")) +
                    "/com.hermes.hindsight.plist"],
                   capture_output=True)


def _ensure_symlinks():
    """Link live Hermes sources into the vault's hermes/ subfolder so Obsidian
    sees them. These are NOT generated — they mirror ~/.hermes/MEMORY.md,
    USER.md, SOUL.md, skills/. They live under System/Hermes/ to keep the vault root
    clean (data folders only at root)."""
    hermes_dir = os.path.join(VAULT, "System", "Hermes")
    os.makedirs(hermes_dir, exist_ok=True)
    # determine active profile base
    profile = os.environ.get("HERMES_PROFILE")
    if profile:
        pbase = os.path.expanduser(f"~/.hermes/profiles/{profile}")
        if os.path.isdir(pbase):
            base = pbase
        else:
            base = os.path.expanduser("~/.hermes")
    else:
        base = os.path.expanduser("~/.hermes")
    links = {
        "MEMORY.md": os.path.join(base, "MEMORY.md"),
        "USER.md": os.path.join(base, "USER.md"),
        "SOUL.md": os.path.join(base, "SOUL.md"),
        "skills": os.path.join(base, "skills"),
    }
    for name, target in links.items():
        if not os.path.exists(target):
            continue
        dst = os.path.join(hermes_dir, name)
        if os.path.lexists(dst) and not os.path.islink(dst):
            try:
                os.remove(dst)
            except Exception:
                continue
        try:
            if os.path.islink(dst):
                os.unlink(dst)
            os.symlink(target, dst)
        except FileExistsError:
            pass


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="sync only one source")
    args = ap.parse_args()

    os.makedirs(VAULT, exist_ok=True)
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)

    # ensure live symlinks (MEMORY.md, USER.md, skills/) always present
    _ensure_symlinks()

    # Pre-flight the TEI endpoint before starting a potentially long sync.
    _ensure_tei()

    pause = args.source in (None, "github", "notes", "docs")
    if pause:
        _pause_hindsight_daemon()

    sources = {
        "github": sync_github,
        "notes": sync_apple_notes,
        "docs": sync_documents,
        "drive": sync_google_drive,
        "hindsight": sync_hindsight,
        "memory": _sync_memory_facts,
    }
    try:
        col = get_col()
        if args.source:
            if args.source not in sources:
                raise SystemExit(f"unknown source: {args.source}")
            sources[args.source](col)
        else:
            for name, fn in sources.items():
                try:
                    fn(col)
                except Exception as e:
                    log(f"  {name} errored: {e}")
    finally:
        if pause:
            _resume_hindsight_daemon()
    log("SYNC DONE")


if __name__ == "__main__":
    main()
