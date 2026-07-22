#!/usr/bin/env python3
"""Google sync for the Second Brain.

Syncs (via Google REST API + curl, avoiding httplib2 TLS stalls):
  - Google Drive accounts route into configured work, personal, and special sections.
  - Google Calendar (both) -> calendar/
  - Gmail metadata (both)        -> gmail/
  - Google Sheets (both)         -> sheets/

Auth: OAuth tokens in ~/.hermes/google-tokens/{account}.json (refreshed on expiry).
"""

import datetime
import json
import os
import re
import subprocess
import time
from datetime import UTC
from pathlib import Path
from urllib.parse import quote as urlquote
from urllib.parse import urlencode

import chromadb
from chromadb.config import Settings

HERMES = Path(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")))
CREDS_FILE = (
    HERMES / "google-oauth.keys.json"
    if os.path.exists(HERMES / "google-oauth.keys.json")
    else HERMES / "gcp-oauth.keys.json"
)
TOKEN_DIR = HERMES / "google-tokens"
VAULT_ROOT = Path(os.path.expanduser(os.environ.get("SECOND_BRAIN_DIR", "~/second-brain")))
WORK_SECTION = os.environ.get("WORK_SECTION", "Work")
PERSONAL_SECTION = os.environ.get("PERSONAL_SECTION", "Personal")
SPECIAL_SECTION = os.environ.get("SPECIAL_SECTION", "Special")
VAULT_DIR = VAULT_ROOT / PERSONAL_SECTION / "Drive"
VAULT_PERSONAL = VAULT_ROOT / PERSONAL_SECTION
VAULT_WORK = VAULT_ROOT / WORK_SECTION
VAULT_SPECIAL = VAULT_ROOT / SPECIAL_SECTION
VAULT_MEETINGS = VAULT_ROOT / "meetings"
# Work account
VAULT_CALENDAR = VAULT_WORK / "Calendar"
VAULT_GMAIL = VAULT_WORK / "Email"
VAULT_SHEETS = VAULT_WORK / "Sheets"
VAULT_WORK_DRIVE = VAULT_WORK / "Drive"
VAULT_WORK_MEETINGS = VAULT_WORK / "Meetings"
VAULT_WORK_PROJECTS = VAULT_WORK / "Projects"
VAULT_WORK_BUSINESS = VAULT_WORK / "Business"
# Personal account
VAULT_PERSONAL_BASE = VAULT_PERSONAL
VAULT_PERS_CALENDAR = VAULT_PERSONAL / "Calendar"
VAULT_PERS_EMAIL = VAULT_PERSONAL / "Email"
VAULT_PERS_SHEETS = VAULT_PERSONAL / "Sheets"
VAULT_PERS_DRIVE = VAULT_PERSONAL / "Drive"
VAULT_PERS_MEETINGS = VAULT_PERSONAL / "Meetings"
VAULT_PERS_NOTES = VAULT_PERSONAL / "Notes"
VAULT_PERS_DOCS = VAULT_PERSONAL / "Documents"
VAULT_PERS_PROJECTS = VAULT_PERSONAL / "Projects"
# Special account/topic
VAULT_SPECIAL_CAL = VAULT_SPECIAL / "Calendar"
VAULT_SPECIAL_MAIL = VAULT_SPECIAL / "Email"
VAULT_SPECIAL_MEET = VAULT_SPECIAL / "Meetings"
VAULT_SPECIAL_SHEETS = VAULT_SPECIAL / "Sheets"
VAULT_SPECIAL_DRIVE = VAULT_SPECIAL / "Drive"
VAULT_SPECIAL_NOTES = VAULT_SPECIAL / "Notes"
VAULT_SPECIAL_DOCS = VAULT_SPECIAL / "Documents"
VAULT_SPECIAL_PROJECTS = VAULT_SPECIAL / "Projects"
CHROMA_DIR = HERMES / "second-brain-chroma"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
WORK_ACCOUNT = os.environ.get("GOOGLE_WORK_ACCOUNT", "work")
PERSONAL_ACCOUNT = os.environ.get("GOOGLE_PERSONAL_ACCOUNT", "personal")
SPECIAL_ACCOUNT = os.environ.get("GOOGLE_SPECIAL_ACCOUNT", "special")
ACCOUNTS = list(dict.fromkeys([WORK_ACCOUNT, PERSONAL_ACCOUNT, SPECIAL_ACCOUNT]))

# ============================================================================
# Canonical routing. Keywords are configured in the local environment.
# ============================================================================
WORK_KEYS = [
    item.strip()
    for item in os.environ.get("WORK_ROUTE_KEYWORDS", "work,business").split(",")
    if item.strip()
]
SPECIAL_KEYS = [
    item.strip()
    for item in os.environ.get("SPECIAL_ROUTE_KEYWORDS", "special").split(",")
    if item.strip()
]

_WORK_RE = re.compile("|".join(map(re.escape, WORK_KEYS)), re.I)
_SPECIAL_RE = re.compile("|".join(map(re.escape, SPECIAL_KEYS)), re.I)


def is_special(name):
    return bool(_SPECIAL_RE.search(name or ""))


def is_work(name, text=""):
    return bool(_WORK_RE.search(name or "")) or bool(_WORK_RE.search(text or ""))


def route_text(name, text=""):
    """Return special, work, or personal according to configured keywords."""
    if is_special(name) or is_special(text):
        return "special"
    if is_work(name, text):
        return "work"
    return "personal"


def log(m):
    print(f"[google] {m}", flush=True)


class _NullCollection:
    """No-op chroma stand-in when the index is corrupt/unavailable.
    Vault files are still written; vector indexing is skipped."""

    def upsert(self, *a, **k):
        pass

    def delete(self, *a, **k):
        pass

    def count(self):
        return 0

    def get(self, *a, **k):
        return {}


def get_col():
    try:
        c = chromadb.PersistentClient(
            path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False, allow_reset=True)
        )
        return c.get_or_create_collection(name="second_brain")
    except Exception:
        return _NullCollection()


def embed(texts):
    """Best-effort embeddings through the same TEI service as the indexer."""
    import urllib.request

    try:
        url = os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:6999/v1/embeddings")
        req = urllib.request.Request(
            url,
            data=json.dumps({"model": EMBED_MODEL, "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.load(response)
        return [item["embedding"] for item in data.get("data", [])]
    except Exception:
        return [None] * len(texts)


def gapi_get(url, creds, account, label="api", raw=False):
    """GET a Google API URL with Bearer auth. Returns parsed JSON (default) or
    raw bytes (raw=True) for binary downloads like Drive media."""
    token = creds.get("token") or creds.get("access_token")
    if not token:
        log(f"  {label}: missing access token")
        return None
    cmd = ["curl", "-sS", "-f", "-m", "60", "-H", f"Authorization: Bearer {token}", url]
    for attempt in range(3):
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=70)
            if res.returncode != 0:
                return None
            if raw:
                return res.stdout
            body = res.stdout.decode("utf-8", "ignore").strip()
            if not body:
                return None
            return json.loads(body)
        except Exception as e:
            log(f"  {label} GET err ({attempt}): {type(e).__name__}")
            time.sleep(1)
    return None


def load_creds(account):
    p = TOKEN_DIR / f"{account}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_creds(account, creds):
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    (TOKEN_DIR / f"{account}.json").write_text(json.dumps(creds, indent=2), encoding="utf-8")


def refresh_token(account, creds):
    """Refresh the access token using the refresh_token."""
    # try to locate client id/secret from the token file or keys file
    cid = creds.get("client_id") or creds.get("installed", {}).get("client_id")
    csec = creds.get("client_secret") or creds.get("installed", {}).get("client_secret")
    rt = creds.get("refresh_token")
    if not (cid and csec and rt) and CREDS_FILE.exists():
        # fall back to keys file
        ks = json.loads(CREDS_FILE.read_text())
        cid = cid or ks.get("client_id") or ks.get("installed", {}).get("client_id")
        csec = csec or ks.get("client_secret") or ks.get("installed", {}).get("client_secret")
    if not (cid and csec and rt):
        return creds
    data = {
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rt,
        "grant_type": "refresh_token",
    }
    try:
        res = subprocess.run(
            [
                "curl",
                "-s",
                "-m",
                "30",
                "-X",
                "POST",
                "https://oauth2.googleapis.com/token",
                "-H",
                "Content-Type: application/x-www-form-urlencoded",
                "--data",
                urlencode(data),
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        tok = json.loads(res.stdout)
        if "access_token" in tok:
            creds["token"] = tok["access_token"]
            if "expires_in" in tok:
                creds["expiry"] = (
                    datetime.datetime.utcnow() + datetime.timedelta(seconds=int(tok["expires_in"]))
                ).isoformat()
            save_creds(account, creds)
            log(f"  {account}: token refreshed")
    except Exception as e:
        log(f"  {account}: refresh failed: {e}")
    return creds


def get_creds(account):
    creds = load_creds(account)
    if not creds:
        return None
    # refresh if expired
    exp = creds.get("expiry")
    if exp:
        try:
            exp_dt = datetime.datetime.fromisoformat(exp.replace("Z", "+00:00"))
            now = datetime.datetime.now(UTC)
            if exp_dt.tzinfo is None:
                now = now.replace(tzinfo=None)
            if exp_dt < now:
                creds = refresh_token(account, creds)
        except Exception:
            creds = refresh_token(account, creds)
    return creds


def store(col, account, title, body, gdoc_id, source="google-drive", vault_dir=None, folder=None):
    vdir = Path(vault_dir) if vault_dir else VAULT_DIR
    vdir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in title if c.isalnum() or c in " -_.")[:60]
    if folder and folder != "(root)":
        slug = "".join(c for c in folder if c.isalnum() or c in "-_")[:80]
        name = f"{account}-{slug}-{safe}.md"
    else:
        name = f"{account}-{safe}.md"
    path = vdir / name
    # incremental: skip if already synced today with same content
    today = datetime.date.today().isoformat()
    if path.exists():
        try:
            existing = path.read_text()
            if f"date: {today}" in existing and body.strip() and body.strip() in existing:
                return  # already up-to-date today
        except Exception:
            pass
    fmatter = f"---\nsource: {source}\naccount: {account}\ngdoc_id: {gdoc_id}\ndate: {today}\n"
    if folder:
        fmatter += f"folder: {folder}\n"
    fmatter += f"---\n\n{body}\n"
    path.write_text(fmatter)
    # embed
    chunks = [body[i : i + 1500] for i in range(0, len(body), 1200)]
    chunks = [c for c in chunks if c.strip()]
    if not chunks:
        return
    embs = embed(chunks)
    ids, docs, metas, good_embs = [], [], [], []
    for i, (ch, e) in enumerate(zip(chunks, embs, strict=False)):
        if e is None:
            continue
        ids.append(f"{source}:{account}:{gdoc_id}#{i}")
        docs.append(ch)
        good_embs.append(e)
        metas.append({"source": source, "account": account, "title": title, "chunk": i})
    if ids:
        try:
            col.upsert(ids=ids, documents=docs, embeddings=good_embs, metadatas=metas)
        except Exception as e:
            # chroma may be corrupt/unavailable — vault file is already written,
            # so the Second Brain is complete; skip the vector index silently.
            log(f"  [chroma] upsert skipped: {type(e).__name__}")


def extract_doc_text(doc):
    out = []
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            for run in el["paragraph"].get("elements", []):
                if "textRun" in run:
                    out.append(run["textRun"].get("content", ""))
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for c in cell.get("content", []):
                        if "paragraph" in c:
                            for run in c["paragraph"].get("elements", []):
                                if "textRun" in run:
                                    out.append(run["textRun"].get("content", ""))
    return "".join(out)


def sync_calendar(account, vault_dir=None, source="google-calendar"):
    creds = get_creds(account)
    if not creds:
        return
    col = get_col()
    try:
        from datetime import datetime

        time_min = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            f"?maxResults=50&singleEvents=true&orderBy=startTime&timeMin={time_min}"
        )
        data = gapi_get(url, creds, account, "cal")
        for ev in (data or {}).get("items", []):
            title = ev.get("summary", "untitled")
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            body = f"Event: {title}\nWhen: {start}\n"
            if ev.get("description"):
                body += f"\n{ev['description']}\n"
            store(col, account, f"cal-{title}", body, ev["id"], source=source, vault_dir=vault_dir)
        log(f"  {account}: calendar synced")
    except Exception as e:
        log(f"  {account}: calendar skip: {type(e).__name__}: {str(e)[:60]}")


# NOTE: Sheets are no longer a separate sync — they're pulled during the
# unified Drive walk (see sync()/_drive_walk), via the Sheets API per file.


def sync_gmail(account, vault_dir=None, source="google-gmail"):
    creds = get_creds(account)
    if not creds:
        return
    col = get_col()
    try:
        msgs = gapi_get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?"
            "maxResults=30&q=newer_than%3A30d",
            creds,
            account,
            f"{account}/gmail-list",
        )
        mids = (msgs or {}).get("messages", [])
        n = 0
        for m in mids:
            try:
                msg = gapi_get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}"
                    "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date",
                    creds,
                    account,
                    f"mail {m['id']}",
                )
                if not msg:
                    continue
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                snippet = (msg.get("snippet") or "").strip()
                text = (
                    f"From: {headers.get('From', '?')}\n"
                    f"Subject: {headers.get('Subject', '?')}\n"
                    f"Date: {headers.get('Date', '?')}\n\n{snippet[:500]}"
                )
                store(
                    col,
                    account,
                    f"mail-{m['id']}",
                    text,
                    m["id"],
                    source=source,
                    vault_dir=vault_dir,
                )
                n += 1
            except Exception:
                continue
        log(f"  {account}: {n} gmail metadata synced (bodies excluded)")
    except Exception as e:
        log(f"  {account}: gmail skip: {type(e).__name__}: {str(e)[:60]}")


def is_meeting_doc(name):
    """Heuristic: Drive docs that are meeting/call transcripts get routed to
    the meetings folder instead of a generic Drive destination."""
    n = (name or "").lower()
    keys = [
        "meet",
        "transcript",
        "notes by gemini",
        "meeting",
        "company sync",
        "call",
        "1:1",
        "standup",
        "sync -",
        " sync ",
    ]
    return any(k in n for k in keys)


def _drive_list(creds, account, parent=None, drive_id=None):
    q = "trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    items = []
    page = None
    base = "https://www.googleapis.com/drive/v3/files"
    while True:
        url = (
            f"{base}?q={urlquote(q)}"
            f"&pageSize=100&fields=files(id,name,mimeType,parents)"
            + (f"&pageToken={page}" if page else "")
            + (
                f"&corpora=drive&includeItemsFromAllDrives=true"
                f"&supportsAllDrives=true&driveId={urlquote(drive_id)}"
                if drive_id
                else ""
            )
        )
        data = gapi_get(url, creds, account, f"{account}/drive-list")
        if not data:
            break
        items.extend(data.get("files", []))
        page = data.get("nextPageToken")
        if not page:
            break
    return items


_SKIP_MT = {"image/jpeg", "image/png", "image/heic", "image/gif", "image/webp"}


def _drive_fetch_file(creds, account, col, fid, name, mt, vdir, folder=None):
    # FILTER images entirely — do not write stubs or embed anything
    if mt in _SKIP_MT:
        log(f"  skip image: {name}")
        return
    try:
        raw = gapi_get(
            f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media",
            creds,
            account,
            f"dl {name}",
            raw=True,
        )
        if not raw:
            return
        text = ""
        if mt == "application/pdf":
            import io

            import pdfplumber

            try:
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            except Exception:
                text = ""
        elif mt in ("text/csv", "text/plain"):
            text = raw.decode("utf-8", "ignore")
        else:
            try:
                text = raw.decode("utf-8", "ignore")
            except Exception:
                text = ""
        if not text.strip():
            text = f"[Drive file: {name} ({mt}) — no extractable text]"
        store(
            col,
            account,
            name,
            text[:8000],
            fid,
            source="google-drive-file",
            vault_dir=vdir,
            folder=folder,
        )
    except Exception as e:
        log(f"  drive-file {name}: skip {type(e).__name__}: {str(e)[:40]}")


def _fetch_sheet(creds, account, col, fid, name, vdir, folder):
    """Fetch a Google Sheet's cells via the Sheets API; store preserving path."""
    try:
        data = gapi_get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{fid}/values/A1:Z100",
            creds,
            account,
            f"sheet {name}",
        )
        rows = (data or {}).get("values", [])
        if not rows:
            return
        tsv = "\n".join("\t".join(str(c) for c in r) for r in rows[:100])
        if len(tsv) > 50000:
            tsv = tsv[:50000]
        store(col, account, name, tsv, fid, source="google-sheets", vault_dir=vdir, folder=folder)
    except Exception as e:
        log(f"  sheet {name}: skip {type(e).__name__}: {str(e)[:40]}")


def _folder_all_images(creds, account, parent, drive_id=None):
    """True if every descendant of `parent` is an image file (or the folder is
    empty) — i.e. nothing we can parse. Lets us skip image-only folders rather
    than descend and store unreadable stubs."""
    items = _drive_list(creds, account, parent, drive_id=drive_id)
    if not items:
        return True
    for it in items:
        mt = it.get("mimeType", "")
        if mt == "application/vnd.google-apps.folder":
            if not _folder_all_images(creds, account, it["id"], drive_id=drive_id):
                return False
        elif mt in _SKIP_MT:
            continue
        else:
            return False
    return True


def _resolve_vault_dir(base_dir, path_parts, name, text=""):
    """Return the vault section root.

    Special-topic content moves to the configured special section. Everything
    else remains under the account's default root.
    """
    full = "/".join(path_parts + ([name] if name else []))
    route = route_text(full, text)
    if route == "special":
        return VAULT_SPECIAL_DRIVE
    return base_dir


def _safe_drive_part(part):
    """Make one Drive name safe as a local directory component.

    Drive names normally map 1:1. Only path separators and traversal markers
    are normalized because they cannot be represented safely on disk.
    """
    part = str(part).replace("/", "／").replace("\\", "＼")
    return part if part not in ("", ".", "..") else "_"


def _drive_target_dir(base_dir, path_parts, name, text=""):
    """Route the file to a vault section while preserving its full Drive path."""
    root = Path(_resolve_vault_dir(base_dir, path_parts, name, text))
    return root.joinpath(*(_safe_drive_part(p) for p in path_parts))


def _drive_walk(creds, account, col, parent, path_parts, base_dir, drive_source, drive_id=None):
    """ONE unified Drive walk: lists the filesystem via Drive API, then pulls
    CONTENT via the right API per mimeType —
        document    -> Docs API (text)
        spreadsheet -> Sheets API (cells)
        image       -> skipped (unparseable)
        other       -> raw download + extract (PDF/CSV/text)
    Structure is preserved 1:1: <section>/Drive/<full-drive-path>/<name>.md
    Folder routing decides the vault root from folder path semantics; files
    inherit that root and can override only when their own name/content is
    unambiguously personal/nifty/pink."""
    files = _drive_list(creds, account, parent, drive_id=drive_id)
    if path_parts:
        log(f"  ↳ folder: {'/'.join(path_parts)} ({len(files)} items)")
    folder_path = "/".join(path_parts) if path_parts else "(root)"
    # Folder path decides the section root. Files below inherit it.
    folder_root = _drive_target_dir(base_dir, path_parts, "")
    for f in files:
        fid, name, mt = f["id"], f["name"], f.get("mimeType", "")
        if mt == "application/vnd.google-apps.folder":
            # skip image-only folders entirely (nothing parseable inside)
            if _folder_all_images(creds, account, fid, drive_id=drive_id):
                log(f"  skip image-only folder: {name}")
                continue
            _drive_walk(
                creds,
                account,
                col,
                fid,
                path_parts + [name],
                folder_root,
                drive_source,
                drive_id=drive_id,
            )
            continue
        # Use folder-driven root by default; preserve full Drive path under it.
        vdir = _drive_target_dir(folder_root, path_parts, name)
        if mt == "application/vnd.google-apps.document":
            try:
                doc = gapi_get(
                    f"https://docs.googleapis.com/v1/documents/{fid}", creds, account, f"doc {name}"
                )
                text = extract_doc_text(doc) if doc else ""
                if not text.strip():
                    continue
                # Re-check category with document text; path stays intact.
                vdir = _drive_target_dir(folder_root, path_parts, name, text)
                store(
                    col,
                    account,
                    name,
                    text,
                    fid,
                    source=drive_source,
                    vault_dir=vdir,
                    folder=folder_path,
                )
            except Exception as e:
                log(f"  doc {name}: skip {type(e).__name__}: {str(e)[:40]}")
        elif mt == "application/vnd.google-apps.spreadsheet":
            _fetch_sheet(creds, account, col, fid, name, vdir, folder_path)
        else:
            _drive_fetch_file(creds, account, col, fid, name, mt, vdir, folder=folder_path)


def sync(account, drive_vault_dir=None, drive_source="google-drive", drive_id=None):
    """UNIFIED Drive sync for one account.
    Walks the Drive filesystem (incl. shared drives when drive_id is set),
    preserving the EXACT folder layout, pulling file content via the correct
    API (Docs / Sheets / blob). Image-only folders are skipped. Every file
    mirrors to <section>/Drive/<drive-path>/ — no flattening."""
    creds = get_creds(account)
    if not creds:
        return
    col = get_col()
    base_dir = (
        Path(drive_vault_dir)
        if drive_vault_dir
        else VAULT_SPECIAL_DRIVE
        if account == SPECIAL_ACCOUNT
        else VAULT_WORK_DRIVE
        if account == WORK_ACCOUNT
        else VAULT_PERS_DRIVE
    )
    try:
        start_parent = drive_id if drive_id else "root"
        _drive_walk(
            creds, account, col, start_parent, [], base_dir, drive_source, drive_id=drive_id
        )
        log(f"  {account}: drive synced")
    except Exception as e:
        log(f"  {account}: drive skip: {type(e).__name__}: {str(e)[:60]}")


def oauth_auth(account):
    """One-time OAuth for a NEW account. Prints a consent URL; user pastes the
    ?code= back; we exchange for tokens and save to TOKEN_DIR/{account}.json."""
    if not CREDS_FILE.exists():
        log(f"  No credentials file ({CREDS_FILE.name}). Cannot auth {account}.")
        return
    ks = json.loads(CREDS_FILE.read_text())
    cid = ks.get("client_id") or ks.get("installed", {}).get("client_id")
    csec = ks.get("client_secret") or ks.get("installed", {}).get("client_secret")
    if not (cid and csec):
        log(f"  No client_id/secret in {CREDS_FILE.name}.")
        return
    scope = (
        "https://www.googleapis.com/auth/drive.readonly "
        "https://www.googleapis.com/auth/calendar.readonly "
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    )
    redirect = "urn:ietf:wg:oauth:2.0:oob"
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={urlquote(cid)}&redirect_uri={urlquote(redirect)}"
        f"&response_type=code&scope={urlquote(scope)}&access_type=offline&prompt=consent"
    )
    print(f"\nOpen this URL in your browser and authorize {account}:")
    print(auth_url)
    code = input("Paste the authorization code here: ").strip()
    if not code:
        log("  No code provided. Aborting.")
        return
    try:
        res = subprocess.run(
            [
                "curl",
                "-s",
                "-m",
                "40",
                "-X",
                "POST",
                "https://oauth2.googleapis.com/token",
                "-H",
                "Content-Type: application/x-www-form-urlencoded",
                "--data",
                f"code={urlquote(code)}&client_id={urlquote(cid)}"
                f"&client_secret={urlquote(csec)}&redirect_uri={urlquote(redirect)}"
                f"&grant_type=authorization_code",
            ],
            capture_output=True,
            text=True,
            timeout=50,
        )
        tok = json.loads(res.stdout)
        if "access_token" not in tok:
            log(f"  Auth failed: {res.stdout[:120]}")
            return
        creds = {
            "token": tok.get("access_token"),
            "refresh_token": tok.get("refresh_token"),
            "client_id": cid,
            "client_secret": csec,
            "expiry": (
                datetime.datetime.utcnow()
                + datetime.timedelta(seconds=int(tok.get("expires_in", 3600)))
            ).isoformat(),
        }
        save_creds(account, creds)
        log(f"  {account}: OAuth complete, token saved.")
    except Exception as e:
        log(f"  {account}: auth error: {type(e).__name__}: {str(e)[:80]}")


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", help="run interactive OAuth for a configured account")
    ap.add_argument("--account", help="sync a specific account (default: all configured)")
    args = ap.parse_args()

    if args.auth:
        if args.auth not in ACCOUNTS:
            log(f"Unknown account: {args.auth}. Use: {', '.join(ACCOUNTS)}")
            return
        oauth_auth(args.auth)
        return

    accounts = [args.account] if args.account else ACCOUNTS
    for acc in accounts:
        if not get_creds(acc):
            log(f"  {acc}: no credentials (skip)")
            continue
        if acc == WORK_ACCOUNT:
            sync(acc, drive_vault_dir=VAULT_WORK_DRIVE, drive_source="work-drive")
            calendar_dir, mail_dir = VAULT_CALENDAR, VAULT_GMAIL
            # shared drives
            try:
                dlist = gapi_get(
                    "https://www.googleapis.com/drive/v3/drives?pageSize=10",
                    get_creds(acc),
                    acc,
                    f"{acc}/drives",
                )
                for d in (dlist or {}).get("drives", []):
                    sync(
                        acc,
                        drive_vault_dir=VAULT_WORK_DRIVE,
                        drive_source="work-drive",
                        drive_id=d["id"],
                    )
            except Exception as e:
                log(f"  {acc}: shared drives skip: {e}")
        elif acc == SPECIAL_ACCOUNT:
            sync(acc, drive_vault_dir=VAULT_SPECIAL_DRIVE, drive_source="special-drive")
            calendar_dir, mail_dir = VAULT_SPECIAL_CAL, VAULT_SPECIAL_MAIL
        else:
            sync(acc, drive_vault_dir=VAULT_PERS_DRIVE, drive_source="personal-drive")
            calendar_dir, mail_dir = VAULT_PERS_CALENDAR, VAULT_PERS_EMAIL
        sync_calendar(acc, vault_dir=calendar_dir, source="google-calendar")
        sync_gmail(acc, vault_dir=mail_dir, source="google-gmail")
    log("DONE")


if __name__ == "__main__":
    main()
