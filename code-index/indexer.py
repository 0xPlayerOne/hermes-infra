#!/usr/bin/env python3
"""
Code Indexer — walks $DEV_ROOT, discovers all git repos, chunks source
files, embeds with Text Embeddings Inference (TEI) running Qwen/Qwen3-Embedding-0.6B
natively on Apple Silicon Metal, stores in chromadb.

Design:
- AUTO-DISCOVER: any git repo dropped into $DEV_ROOT is indexed automatically.
- INCREMENTAL: per-file content hash tracked; only changed files re-embed.
- CODE-OPTIMIZED chunking: split at function/class boundaries for precision.
- METADATA: repo, owner, rel_path, language, so queries can scope.

Usage:
  indexer.py --index        # full or incremental index of $DEV_ROOT
  indexer.py --reindex      # wipe + full re-index (use after model change)
  indexer.py --status       # show indexed repos + chunk counts
  indexer.py --query "text" [--repo name] [--n 8]
"""
import os, sys, json, hashlib, subprocess, argparse, time
from pathlib import Path

DEV_ROOT = Path(os.path.expanduser(os.environ.get("DEV_ROOT", "~/code")))
CHROMA_DIR = Path(os.environ.get("CHROMA_DIR", os.path.expanduser("~/.hermes/code-index/chroma")))
# CODE INDEX EMBEDDING MODEL — LOCKED.
# This index is built exclusively for Qwen/Qwen3-Embedding-0.6B via TEI (Metal).
# Mixing any other model corrupts cosine search (vectors not comparable).
# TEI serves OpenAI-compatible /v1/embeddings on localhost:3000.
_LOCKED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
MODEL = _LOCKED_MODEL
# 0.6B default dim = 1024 (under chroma/HNSW limits).
EMBED_DIM = 1024
STATE_FILE = Path(os.path.expanduser("~/.hermes/code-index/manifest.json"))

def enforce_model_available():
    """Verify TEI is actually EMBEDDING on localhost:6999 (Metal backend).

    Hard-fail (exit 2) if TEI isn't up, so we don't start a long
    reindex that will fail mid-way.

    NOTE: /health returns 200 even when TEI is WEDGED (dead sockets, 0% CPU,
    /v1/embeddings hangs) — so we probe the real embed endpoint instead.
    """
    err = "unknown"
    try:
        if _tei_probe_ok(timeout=10):
            log(f"embedding model locked + verified (TEI): {MODEL}")
            return
        err = "probe returned non-ok (TEI wedged or model missing)"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    log(f"FATAL: TEI not reachable/responsive on localhost:6999 ({err})")
    sys.exit(2)

# Skip patterns — never index these (incl. agent scratch/worktree dirs)
SKIP_DIRS = {
    "node_modules", ".git", ".next", ".turbo", "dist", "build",
    ".cache", ".venv", "venv", "__pycache__", ".pytest_cache",
    "coverage", ".vercel", ".idea", ".vscode", "target", "bin", "obj",
    # Unity / game-engine build & cache junk (huge, non-source)
    "Library", "BurstCache", "Temp", "Logs", "UserSettings",
    "MemoryCaptures", "Build", "Builds", "ExportedObj",
    # data / cache dumps inside code repos (json rank files, model caches)
    "cached_data", "cache", "data", ".data", "datasets", "models",
    # auto-generated data packages (pink-binder/packages/data = 107K gen files)
    "packages/data",
    # agent scratch / ephemeral worktree dirs that poison the walk
    ".codex-worktrees", "worktrees", ".claude", ".aider",
}
# Repos to skip entirely (set via SKIP_REPOS env, comma-separated).
SKIP_REPOS = set(os.environ.get("SKIP_REPOS", "").split(",")) if os.environ.get("SKIP_REPOS") else set()
# Files that produce more than this many chunks are data dumps, not source.
# Skip them so one giant json/csv can't dominate the whole run.
MAX_CHUNKS_PER_FILE = 120
# Repos with more candidate files than this are skipped by the nightly
# sweep (too large to index in the maintenance window). Index on demand.
MAX_REPO_FILES = int(os.environ.get("MAX_REPO_FILES", 0))  # 0 = uncapped
# Directories we treat as opaque (never recurse into, even if not in SKIP_DIRS)
OPAQUE_DIR_PREFIXES = (".",)  # skip dotdirs by default to avoid .git/.cache blowups
# Extensions we actually care about (code + config)
CODE_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt", ".swift",
    ".sol", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".sh", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".graphql", ".sql",
}
# Max chars per chunk. 0.6B accepts up to 32768 tokens; our chunks are
# <=2000 chars (~500 tok), so 2000 is plenty.
MAX_CHUNK_CHARS = int(os.environ.get("MAX_CHUNK_CHARS", 2000))
CHUNK_OVERLAP = 200
HARD_CHUNK_CAP = 4000    # never embed a chunk larger than this
EMBED_MODEL_CTX = 2000
MAX_FILE_BYTES = 200_000 # skip files > 200KB (build artifacts / data dumps)

def log(m): print(f"[indexer] {m}", flush=True)

def safe_embed(client, prompt: str, _attempts=2) -> list | None:
    """Embed one prompt, returning None on failure (never crash the run).
    Retries once with a FRESH client if the call times out/wedges."""
    # hard guard: truncate to model context to avoid 500 errors
    if len(prompt) > 2000:
        prompt = prompt[:2000]
    for attempt in range(_attempts):
        try:
            return client.embed(model=MODEL, input=prompt)["embeddings"][0]
        except Exception as e:
            msg = str(e)
            # Context-too-long is a PERMANENT failure for this chunk — don't retry.
            if "exceeds the context length" in msg or "context length" in msg:
                return None
            if attempt < _attempts - 1:
                log(f"  ⚠️ embed stalled ({type(e).__name__}); fresh TEI client + retry")
                try:
                    client = get_client()  # fresh client breaks a wedged socket
                except Exception:
                    pass
                time.sleep(1)
                continue
            log(f"  ⚠️ embed failed ({type(e).__name__}): {msg[:80]}")
            return None

def find_git_repos(root: Path):
    """Return list of (repo_path, repo_name) for every git repo under root.
    Uses os.walk(followlinks=False) so a dangling symlink (pnpm .pnpm,
    .codex-worktrees) can NEVER wedge the traversal."""
    import os
    repos = []
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root_str, followlinks=False):
        # detect a git repo FIRST (before pruning .git from dirnames)
        if ".git" in dirnames or ".git" in filenames:
            repo_path = Path(dirpath)
            try:
                rel = repo_path.relative_to(root)
            except ValueError:
                rel = Path(dirpath)
            repos.append((repo_path, str(rel)))
            dirnames[:] = []  # don't recurse INTO a git repo (nested .git false positives)
            continue
        # prune skipped/opaque dirs so walk never descends into them
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(OPAQUE_DIR_PREFIXES)]
    return sorted(repos)

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def chunk_text(text: str, path: str):
    """Split source into semantically-meaningful chunks.
    Strategy: split on blank-line-separated blocks, then if a block is too
    big, hard-split by line count. Keeps function-level context together."""
    lines = text.splitlines()
    chunks, cur, cur_len = [], [], 0
    for ln in lines:
        cur.append(ln)
        cur_len += len(ln) + 1
        if cur_len >= MAX_CHUNK_CHARS:
            chunks.append("\n".join(cur))
            # keep overlap
            cur = cur[-(CHUNK_OVERLAP // 40):] if CHUNK_OVERLAP else []
            cur_len = sum(len(x) + 1 for x in cur)
    if cur:
        chunks.append("\n".join(cur))
    # fallback: if no newlines (minified), split by char window
    if not chunks and text.strip():
        for i in range(0, len(text), MAX_CHUNK_CHARS - CHUNK_OVERLAP):
            chunks.append(text[i:i + MAX_CHUNK_CHARS])
    return [c for c in chunks if c.strip()]

def lang_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
        ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".py": "python", ".go": "go", ".rs": "rust", ".java": "java",
        ".kt": "kotlin", ".swift": "swift", ".sol": "solidity",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
        ".cs": "csharp", ".rb": "ruby", ".sh": "shell", ".zsh": "shell",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".graphql": "graphql", ".sql": "sql",
    }.get(ext, "other")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"repos": {}, "model": MODEL}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

# --- Embedding backend: Text Embeddings Inference (TEI) -------------
# TEI via Homebrew, Qwen/Qwen3-Embedding-0.6B natively on Apple Silicon
# Metal. No Python embedding stack (sentence-transformers/torch purged).
# TEI serves OpenAI-compatible /v1/embeddings on localhost:6999.
_TEI_URL = os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:6999/v1/embeddings")
_TEI_MODEL = os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
_TEI_DIM = 1024  # 0.6B default; under pgvector's 2000 HNSW limit


def _tei_probe_ok(timeout=8):
    """Real TEI readiness check: must actually EMBED, not just answer /health.

    /health returns 200 even when TEI is wedged (dead sockets, 0% CPU,
    /v1/embeddings hangs), so probe the live embed endpoint with a tiny
    payload and require a valid response within `timeout` seconds.
    """
    import urllib.request
    import json as _json
    body = _json.dumps({"model": MODEL, "input": ["__probe__"]}).encode()
    req = urllib.request.Request(
        _TEI_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = _json.loads(resp.read().decode())
            return isinstance(data, dict) and "data" in data
    except Exception:
        return False


def get_client():
    """Return an embedding client compatible with the indexer's API.

    The client exposes .embed(model, input) -> {"embeddings": [[...], ...]}
    backed by TEI (Rust, Metal) on localhost:6999. No Ollama, no Python.
    """
    import urllib.request
    import json as _json

    class _TEIClient:
        def embed(self, model, input, timeout=None):
            if isinstance(input, str):
                input = [input]
            body = _json.dumps({"model": _TEI_MODEL, "input": list(input)}).encode()
            req = urllib.request.Request(
                _TEI_URL, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout or 60) as resp:
                data = _json.loads(resp.read().decode())
            # OpenAI-compatible shape: {"data":[{"embedding":[...]}, ...]}
            return {"embeddings": [d["embedding"] for d in data["data"]]}

    return _TEIClient()


def get_chroma():
    import chromadb
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


# Chunks per embed call. TEI on Metal processes sequences serially:
# ~1s/sequence, so 16 texts ≈ 16-20s/batch (safe under the 120s timeout).
# 32 worked but sat close to the edge under sustained load. 16 is stable.
EMBED_BATCH = 16
# Delay between embed batches (seconds). Tiny breath; doesn't affect throughput.
EMBED_BATCH_DELAY = 0.05

# TEI Metal occasionally wedges under sustained load (hangs at 0% CPU).
# When that happens we restart it via launchd and retry the batch.
TEI_PLIST = os.path.join(
    os.path.expanduser(os.environ.get("HERMES_LAUNCH_AGENTS_DIR", "~/Library/LaunchAgents")),
    "com.hermes.tei.plist")
_tei_restart_in_progress = False

def restart_tei():
    """Kill any wedged TEI and let launchd respawn a fresh one.
    Blocks until TEI is serving again (or gives up after 3 tries)."""
    global _tei_restart_in_progress
    if _tei_restart_in_progress:
        return False
    _tei_restart_in_progress = True
    try:
        log("  🔄 TEI wedged — restarting via launchd")
        subprocess.run(["pkill", "-9", "-f", "text-embeddings"],
                       capture_output=True, timeout=10)
        time.sleep(2)
        # unload + reload to force a clean respawn
        subprocess.run(["launchctl", "unload", TEI_PLIST],
                       capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["launchctl", "load", TEI_PLIST],
                       capture_output=True, timeout=10)
        # wait for warmup (~50s on Metal) then verify
        for _ in range(20):
            time.sleep(5)
            # Probe the REAL embed endpoint — /health lies when TEI is wedged.
            if _tei_probe_ok(timeout=10):
                # extra breathe so the HTTP server is fully ready
                time.sleep(2)
                log("  ✅ TEI restarted + healthy")
                return True
        log("  ⚠️ TEI restart failed to come healthy")
        return False
    finally:
        _tei_restart_in_progress = False

def embed_batch(client, texts):
    """Embed a list of texts via TEI (Qwen3-Embedding-0.6B on Metal).
    Returns list of vectors; failed/missing entries are None.
    If TEI wedges (hangs > EMBED_TIMEOUT), we skip the batch.
    """
    out = [None] * len(texts)
    i = 0
    n = len(texts)
    while i < n:
        batch = texts[i:i + EMBED_BATCH]
        try:
            vecs = _embed_with_timeout(client, batch)
            for j, v in enumerate(vecs):
                out[i + j] = v
            time.sleep(EMBED_BATCH_DELAY)  # breathe between batches
        except _EmbedWedge as e:
            # TEI Metal hung — restart it and retry this batch once healthy.
            log(f"  ⚠️ embed wedge on batch {i}-{i+len(batch)} — restarting TEI")
            if restart_tei():
                try:
                    client = get_client()
                    vecs = _embed_with_timeout(client, batch)
                    for j, v in enumerate(vecs):
                        out[i + j] = v
                    time.sleep(EMBED_BATCH_DELAY)
                except Exception:
                    log(f"  ⚠️ embed failed on batch {i}-{i+len(batch)} — skipping")
            else:
                log(f"  ⚠️ TEI restart failed — skipping batch {i}-{i+len(batch)}")
        except Exception as e:
            msg = str(e)
            if "exceeds the context length" in msg or "context length" in msg:
                for k, t in enumerate(batch):
                    try:
                        vv = _embed_with_timeout(client, [t[:EMBED_MODEL_CTX]])
                        out[i + k] = vv[0]
                    except Exception:
                        out[i + k] = None
            else:
                # Transient TEI error (not a wedge) — retry once, restarting
                # TEI first if it looks wedged, then re-embed.
                try:
                    client = get_client()
                    vecs = _embed_with_timeout(client, batch)
                    for j, v in enumerate(vecs):
                        out[i + j] = v
                except _EmbedWedge:
                    if restart_tei():
                        try:
                            client = get_client()
                            vecs = _embed_with_timeout(client, batch)
                            for j, v in enumerate(vecs):
                                out[i + j] = v
                        except Exception:
                            log(f"  ⚠️ embed failed on batch {i}-{i+len(batch)} — skipping")
                    else:
                        log(f"  ⚠️ TEI restart failed — skipping batch {i}-{i+len(batch)}")
                except Exception:
                    log(f"  ⚠️ embed failed on batch {i}-{i+len(batch)} — skipping")
        i += EMBED_BATCH
    return out


class _EmbedWedge(Exception):
    pass


def _embed_with_timeout(client, batch, timeout=90):
    """Embed a batch via the HuggingFace client.

    The TEI/HTTP path is a socket call (no in-process MPS), so a
    thread + join(timeout) is our safety net: if TEI ever hangs, we
    raise _EmbedWedge and skip the batch.
    """
    import threading
    res = {}
    def _run():
        try:
            res["v"] = client.embed(model=MODEL, input=batch)["embeddings"]
        except Exception as e:
            res["err"] = e
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise _EmbedWedge("timeout")
    if "err" in res:
        raise res["err"]
    return res["v"]


import threading

def timeout_upsert(col, ids, docs, embeddings, metas, limit=120):
    """Run chroma upsert in a worker thread. chroma 1.5.x Rust HNSW
    bindings can deadlock (block on poll) on large segments; if it does not
    return within `limit` seconds we abandon the call and return False so the
    main loop can proceed instead of freezing the whole run."""
    res = {}
    def _run():
        try:
            col.upsert(ids=ids, documents=docs,
                       embeddings=embeddings, metadatas=metas)
            res["ok"] = True
        except Exception as e:
            res["err"] = f"{type(e).__name__}: {str(e)[:80]}"
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(limit)
    if t.is_alive():
        log(f"  ⚠️ upsert deadlocked (> {limit}s) — abandoning this file, continuing")
        return False
    if "err" in res:
        log(f"  ⚠️ upsert error: {res['err']}")
        return False
    return res.get("ok", False)

def cmd_index(reindex=False):
    state = load_state() if not reindex else {"repos": {}, "model": MODEL}
    # MODEL MISMATCH GUARD: if the manifest was written by a different embedding
    # model (e.g. a different TEI model), force a clean reindex so we never mix
    # vectors from two models in one collection (breaks cosine search).
    manifest_model = state.get("model")
    if manifest_model and manifest_model != MODEL and not reindex:
        log(f"MODEL MISMATCH: manifest={manifest_model} but code={MODEL} — forcing clean reindex")
        reindex = True
    if reindex:
        log("REINDEX requested — wiping chroma store")
        import shutil
        if CHROMA_DIR.exists():
            shutil.rmtree(CHROMA_DIR)
        state = {"repos": {}, "model": MODEL}
    print("[DEBUG] before get_chroma", flush=True)
    chroma = get_chroma()
    print("[DEBUG] after get_chroma", flush=True)
    col = chroma.get_or_create_collection(
        name="code", metadata={"model": MODEL, "dev_root": str(DEV_ROOT)},
        embedding_function=None,  # we supply embeddings directly via TEI
    )
    client = get_client()
    print("[DEBUG] before find_git_repos", flush=True)
    repos = find_git_repos(DEV_ROOT)
    print(f"[DEBUG] after find_git_repos: {len(repos)} repos", flush=True)
    log(f"discovered {len(repos)} git repos under {DEV_ROOT}")
    total_new, total_upd, total_skip = 0, 0, 0
    for repo_path, repo_name in repos:
        print(f"[DEBUG] processing repo {repo_name}...", flush=True)
        # TEI model is loaded once (server-side, resident) — no
        # per-repo restart needed.
        client = get_client()
        if repo_name in SKIP_REPOS:
            log(f"  ⚠️ {repo_name}: in SKIP_REPOS — skipping")
            continue
        repo_state = state["repos"].get(repo_name, {"files": {}})
        file_states = repo_state.setdefault("files", {})
        repo_new = repo_upd = repo_skip = 0
        # accumulators for the single batched upsert at end of repo
        repo_ids, repo_docs, repo_embeddings, repo_metas, repo_pending = [], [], [], [], {}
        # collect files — os.walk(followlinks=False) so broken symlinks can't wedge it
        candidates = []
        import os as _os
        _too_big = False
        for dirpath, dirnames, filenames in _os.walk(str(repo_path), followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(OPAQUE_DIR_PREFIXES)]
            for fn in filenames:
                p = Path(dirpath) / fn
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                low = str(p).lower()
                if any(x in low for x in ("/.next/", "/.turbo/", "/dist/", "/build/",
                                           "/coverage/", "/.vercel/", "/node_modules/")):
                    continue
                if p.suffix.lower() not in CODE_EXTS:
                    continue
                if p.stat().st_size > MAX_FILE_BYTES:  # skip huge generated/data files
                    continue
                candidates.append(p)
                if MAX_REPO_FILES and len(candidates) > MAX_REPO_FILES:
                    _too_big = True
                    break
            if _too_big:
                break
        if _too_big or (MAX_REPO_FILES and len(candidates) > MAX_REPO_FILES):
            log(f"  ⚠️ {repo_name}: {len(candidates)}+ files — TOO LARGE, skipping (raise MAX_REPO_FILES to include)")
            continue
        # Phase 1: collect all (rel, lang, chunk) for this repo WITHOUT embedding.
        # Phase 2 (below) embeds them in large batches via single TEI calls —
        # one HTTP round-trip returns N vectors, so we don't pay per-file latency.
        collected = []  # list of (rel, lang, chunk)
        for p in candidates:
            try:
                fh = file_hash(p)
            except Exception:
                continue
            rel = str(p.relative_to(repo_path))
            old = file_states.get(rel)
            if old == fh:
                repo_skip += 1
                total_skip += 1
                continue
            try:
                text = p.read_text(errors="ignore")
            except Exception:
                continue
            try:
                chunks = chunk_text(text, str(p))
                if not chunks:
                    continue
                # Only skip DATA files (json/csv/sql) that explode into huge
                # chunk counts — real source (.cs/.py/.ts) is worth indexing
                # even when large. A 120-chunk json is a rank/db dump, not code.
                if p.suffix.lower() in (".json", ".csv", ".sql", ".parquet") \
                        and len(chunks) > MAX_CHUNKS_PER_FILE:
                    log(f"  ⚠️ {rel}: {len(chunks)} chunks — data dump, skipping")
                    continue
                # hard-cap each chunk (defensive, even though chunk_text bounds it)
                chunks = [c[:HARD_CHUNK_CAP] for c in chunks]
                lang = lang_for(p)
                for c in chunks:
                    collected.append((rel, lang, c))
                repo_pending[rel] = fh
                if old is None:
                    repo_new += 1; total_new += 1
                else:
                    repo_upd += 1; total_upd += 1
            except Exception as e:
                log(f"  ⚠️ error processing {rel}: {type(e).__name__}: {str(e)[:80]}")
                continue
        # Phase 2: embed all collected chunks in big batches (one TEI call each).
        if collected:
            for b0 in range(0, len(collected), EMBED_BATCH):
                b1 = min(b0 + EMBED_BATCH, len(collected))
                batch = [c for (_, _, c) in collected[b0:b1]]
                log(f"  >> batch {b0}-{b1}")
                try:
                    embeddings = embed_batch(client, batch)
                    log(f"  << batch {b0}-{b1} none={embeddings.count(None)}")
                except Exception as crash_err:
                    log(f"  ⚠️ embed crashed on batch {b0}-{b1} — skipping (TEI down)")
                    continue
                for k, (rel, lang, ch) in enumerate(collected[b0:b1]):
                    emb = embeddings[k]
                    if emb is None:
                        continue
                    i = sum(1 for mm in repo_metas if mm["path"] == rel)
                    base = f"{repo_name}::{rel}"
                    repo_ids.append(f"{base}#{i}")
                    repo_docs.append(ch)
                    repo_embeddings.append(emb)
                    repo_metas.append({
                        "repo": repo_name, "path": rel, "lang": lang,
                        "chunk": i, "n_chunks": 0,
                    })
        # Batched upsert per repo, split into SMALL batches (100 vectors) to
        # avoid chromadb HNSW deadlock on large segments. Each batch is guarded
        # by timeout_upsert; if one batch deadlocks we abandon it and continue
        # (the file hashes are only committed for batches that landed).
        if repo_ids:
            BATCH = 20  # smaller batches avoid chromadb HNSW deadlock on large repos
            all_ok = True
            landed = {}
            for b0 in range(0, len(repo_ids), BATCH):
                b1 = min(b0 + BATCH, len(repo_ids))
                ok = timeout_upsert(
                    col, repo_ids[b0:b1], repo_docs[b0:b1],
                    repo_embeddings[b0:b1], repo_metas[b0:b1], limit=60)
                if not ok:
                    all_ok = False
                    log(f"  ⚠️ upsert batch {b0}-{b1} failed/deadlocked for {repo_name}")
                else:
                    # commit hashes for files whose chunks landed in this batch
                    for rel in set(repo_ids[i].split("#")[0].split("::")[1]
                                   for i in range(b0, b1)):
                        landed[rel] = repo_pending.get(rel)
            if not all_ok:
                log(f"  ⚠️ some upsert batches failed for {repo_name} — partial index")
            for rel, fh in landed.items():
                file_states[rel] = fh
        state["repos"][repo_name] = {"files": file_states, "path": str(repo_path)}
        log(f"  {repo_name}: +{repo_new} new, ~{repo_upd} upd, {repo_skip} skip")
        save_state(state)  # CHECKPOINT: persist after each repo so interruptions don't lose progress
    log(f"DONE. new={total_new} updated={total_upd} skipped={total_skip} repos={len(repos)}")

def cmd_status():
    state = load_state()
    col = get_chroma().get_collection("code")
    n = col.count()
    print(f"Model: {state.get('model')}")
    print(f"Total chunks in store: {n}")
    print(f"Repos tracked: {len(state.get('repos', {}))}")
    for name, rs in sorted(state.get("repos", {}).items()):
        print(f"  - {name}: {len(rs.get('files', {}))} files")

def cmd_query(q, repo=None, n=8):
    print("[DEBUG] before get_chroma", flush=True)
    chroma = get_chroma()
    print("[DEBUG] after get_chroma", flush=True)
    col = chroma.get_collection("code")
    client = get_client()
    # get_client() returns our custom _TEIClient with .embed(model, input) ->
    # {"embeddings": [[...], ...]}. Query is a single prompt -> take [0].
    qemb = client.embed(model=MODEL, input=[q])["embeddings"][0]
    where = {"repo": repo} if repo else None
    res = col.query(query_embeddings=[qemb], n_results=n, where=where)
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        print(f"\n=== {meta['repo']} / {meta['path']} (chunk {meta['chunk']}/{meta['n_chunks']}, {meta['lang']}) dist={dist:.3f} ===")
        print(doc[:1500])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--query")
    ap.add_argument("--repo")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()
    # Enforce the locked embedding model before any embed operation.
    # --status is read-only (no embed) so it skips the check.
    if args.index or args.reindex or args.query:
        enforce_model_available()
    if args.index: cmd_index()
    elif args.reindex: cmd_index(reindex=True)
    elif args.status: cmd_status()
    elif args.query: cmd_query(args.query, args.repo, args.n)
    else:
        print("use --index | --reindex | --status | --query 'text' [--repo name] [--n 8]")
