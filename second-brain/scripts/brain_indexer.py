#!/usr/bin/env python3
"""
Second-Brain Indexer — walks ~/Developer/second-brain, chunks markdown
prose by section headers, embeds with TEI (Qwen/Qwen3-Embedding-0.6B),
stores in a separate ChromaDB collection 'second-brain'.

Design:
- MARKDOWN-AWARE: splits on ## / ### headers, keeps paragraphs together.
- INCREMENTAL: per-file content hash; only changed files re-embed.
- PROSE OPTIMIZED: chunk size tuned for natural language, not code.
- SAME MODEL as code-index — vectors are comparable for cross-collection search.

Usage:
  brain_indexer.py --index        # incremental index
  brain_indexer.py --reindex      # wipe + full re-index
  brain_indexer.py --status       # show stats
  brain_indexer.py --query "text" [--n 8]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BRAIN_ROOT = Path(os.path.expanduser(os.environ.get("BRAIN_ROOT", "~/Developer/second-brain")))
CHROMA_DIR = Path(os.environ.get("CHROMA_DIR", os.path.expanduser("~/.hermes/code-index/chroma")))
COLLECTION = "second-brain"
STATE_FILE = CHROMA_DIR / "brain_state.json"

# Embedding model — MUST match code-index (Qwen3-Embedding-0.6B via TEI).
# Mixing models corrupts cosine search.
MODEL = "Qwen/Qwen3-Embedding-0.6B"
EMBED_DIM = 1024
TEI_URL = os.environ.get("TEI_EMBED_URL", "http://127.0.0.1:6999/v1/embeddings")

# Prose chunking parameters
MAX_CHUNK_CHARS = int(os.environ.get("MAX_CHUNK_CHARS", 1500))
CHUNK_OVERLAP = 200
HARD_CHUNK_CAP = 3000
MAX_FILE_BYTES = 200_000  # skip files > 200KB


def log(m):
    print(f"[brain-indexer] {m}", flush=True)


# ---------------------------------------------------------------------------
# TEI client
# ---------------------------------------------------------------------------
def get_client():
    """Return an embedding client backed by TEI on localhost:6999.

    Exposes .embed(model, input) -> {"embeddings": [[...], ...]}
    Matches the code-index indexer's client interface exactly.
    """
    import json as _json
    import urllib.request

    class _TEIClient:
        def embed(self, model, input, timeout=None):
            if isinstance(input, str):
                input = [input]
            body = _json.dumps({"model": MODEL, "input": list(input)}).encode()
            req = urllib.request.Request(
                TEI_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout or 60) as resp:
                data = _json.loads(resp.read().decode())
            return {"embeddings": [d["embedding"] for d in data["data"]]}

    return _TEIClient()


EMBED_BATCH = 16  # texts per TEI call (Metal serial ~1s/seq → 16 texts ≈ 16s)


def safe_embed_batch(client, texts: list[str], _attempts=2) -> list[list | None]:
    """Embed a batch of texts, returning list of vectors (None on failure)."""
    truncated = [t[:2000] for t in texts]
    for attempt in range(_attempts):
        try:
            result = client.embed(model=MODEL, input=truncated)
            return result["embeddings"]
        except Exception as e:
            msg = str(e)
            if "exceeds the context length" in msg or "context length" in msg:
                # Fall back to individual embedding
                return [safe_embed(client, t) for t in truncated]
            if attempt < _attempts - 1:
                log(f"  ⚠️ batch embed stalled ({type(e).__name__}); retry")
                time.sleep(1)
                continue
            log(f"  ⚠️ batch embed failed ({type(e).__name__}): {msg[:80]}")
            return [None] * len(texts)
    return [None] * len(texts)


def safe_embed(client, prompt: str, _attempts=2) -> list | None:
    """Embed one prompt, returning None on failure."""
    if len(prompt) > 2000:
        prompt = prompt[:2000]
    for attempt in range(_attempts):
        try:
            return client.embed(model=MODEL, input=prompt)["embeddings"][0]
        except Exception as e:
            msg = str(e)
            if "exceeds the context length" in msg or "context length" in msg:
                return None
            if attempt < _attempts - 1:
                log(f"  ⚠️ embed stalled ({type(e).__name__}); retry")
                time.sleep(1)
                continue
            log(f"  ⚠️ embed failed ({type(e).__name__}): {msg[:80]}")
            return None


# ---------------------------------------------------------------------------
# Markdown-aware chunking
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Strip YAML frontmatter, return (metadata, body)."""
    fm = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            raw = parts[1].strip()
            body = parts[2].strip()
            for line in raw.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"').strip("'")
            return fm, body
    return fm, text


def chunk_markdown(text: str, path: str) -> list[dict]:
    """Split markdown into chunks respecting header structure.

    Returns list of {"text": ..., "section": ...} dicts.
    Strategy:
      1. Split on ## and ### headers (section boundaries).
      2. If a section exceeds MAX_CHUNK_CHARS, split on paragraph breaks.
      3. If a paragraph still exceeds, hard-split by character window.
    """
    fm, body = parse_frontmatter(text)
    if not body.strip():
        return []

    # Split on markdown headers (## or ###)
    header_re = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)
    parts = header_re.split(body)

    chunks = []
    current_header = fm.get("title", Path(path).stem)

    # parts[0] is text before the first header
    if parts[0].strip():
        chunks.extend(_split_block(parts[0].strip(), current_header))

    # Process header/content pairs
    i = 1
    while i < len(parts) - 1:
        header = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # Clean header: remove leading # for metadata
        current_header = re.sub(r"^#+\s*", "", header)
        if content:
            chunks.extend(_split_block(content, current_header))
        i += 2

    # Attach frontmatter metadata to each chunk
    for c in chunks:
        c["frontmatter"] = fm

    return chunks


def _split_block(text: str, section: str) -> list[dict]:
    """Split a block of text into appropriately sized chunks."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [{"text": text, "section": section}]

    # Split on double-newlines (paragraphs)
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, cur, cur_len = [], [], 0

    for para in paragraphs:
        # Single paragraph too big — hard-split
        if len(para) > MAX_CHUNK_CHARS:
            if cur:
                chunks.append({"text": "\n\n".join(cur), "section": section})
                cur, cur_len = [], 0
            for i in range(0, len(para), MAX_CHUNK_CHARS - CHUNK_OVERLAP):
                piece = para[i : i + MAX_CHUNK_CHARS].strip()
                if piece:
                    chunks.append({"text": piece, "section": section})
            continue

        # Would adding this paragraph exceed the limit?
        if cur_len + len(para) + 2 > MAX_CHUNK_CHARS:
            if cur:
                chunks.append({"text": "\n\n".join(cur), "section": section})
                # Keep overlap: last paragraph for context
                cur = cur[-1:] if CHUNK_OVERLAP else []
                cur_len = sum(len(x) + 2 for x in cur)
            cur.append(para)
            cur_len += len(para) + 2
        else:
            cur.append(para)
            cur_len += len(para) + 2

    if cur:
        chunks.append({"text": "\n\n".join(cur), "section": section})

    return [c for c in chunks if c["text"].strip()]


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_files(root: Path) -> list[Path]:
    """Find all markdown files under root, skipping hidden dirs and large files."""
    files = []
    for p in sorted(root.rglob("*.md")):
        # Skip hidden dirs, node_modules, .git, etc.
        if any(part.startswith(".") or part == "node_modules" for part in p.parts):
            continue
        try:
            if p.stat().st_size <= MAX_FILE_BYTES and p.stat().st_size > 0:
                files.append(p)
        except OSError:
            continue
    return files


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"files": {}, "model": MODEL}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------
def get_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_index(reindex=False):
    """Index or re-index all second-brain markdown files."""
    log(f"scanning {BRAIN_ROOT} ...")
    files = discover_files(BRAIN_ROOT)
    log(f"found {len(files)} markdown files")

    col = get_collection()
    state = load_state() if not reindex else {"files": {}, "model": MODEL}

    if reindex:
        log("wiping collection for reindex ...")
        col.delete(where={})  # delete all

    # Ensure TEI is alive
    client = get_client()
    try:
        client.embed(model=MODEL, input="test")
        log(f"TEI verified: {MODEL}")
    except Exception as e:
        log(f"FATAL: TEI not reachable: {e}")
        return 1

    new, updated, skipped, failed = 0, 0, 0, 0
    chunk_total = 0
    t0 = time.time()

    for fi, fpath in enumerate(files):
        rel = str(fpath.relative_to(BRAIN_ROOT))
        fhash = file_hash(fpath)
        prev = state["files"].get(rel)

        if prev == fhash and not reindex:
            skipped += 1
            continue

        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log(f"  read error: {rel}: {e}")
            failed += 1
            continue

        # Remove old chunks for this file
        try:
            old_ids = col.get(where={"source_file": rel})["ids"]
            if old_ids:
                col.delete(ids=old_ids)
        except Exception:
            pass

        chunks = chunk_markdown(text, rel)
        if not chunks:
            skipped += 1
            state["files"][rel] = fhash
            continue

        # Batch embed (16 at a time for TEI throughput)
        ids, docs, metas, embeddings = [], [], [], []
        texts = [c["text"][:2000] for c in chunks]
        for bi in range(0, len(texts), EMBED_BATCH):
            batch = texts[bi : bi + EMBED_BATCH]
            vecs = safe_embed_batch(client, batch)
            for ci, (vec, chunk) in enumerate(
                zip(vecs, chunks[bi : bi + EMBED_BATCH], strict=True)
            ):
                if vec is None:
                    failed += 1
                    continue
                chunk_id = f"sb:{rel}:{bi + ci}"
                ids.append(chunk_id)
                docs.append(texts[bi + ci])
                metas.append(
                    {
                        "source_file": rel,
                        "section": chunk["section"],
                        "folder": str(fpath.parent.relative_to(BRAIN_ROOT)),
                        "chunk_index": bi + ci,
                        "total_chunks": len(chunks),
                    }
                )
                embeddings.append(vec)

        if ids:
            col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
            chunk_total += len(ids)
            if prev:
                updated += 1
            else:
                new += 1
            state["files"][rel] = fhash

        if (fi + 1) % 100 == 0:
            log(f"  progress: {fi + 1}/{len(files)} files ...")

    elapsed = time.time() - t0
    save_state(state)
    log(f"done in {elapsed:.1f}s: {new} new, {updated} updated, {skipped} skipped, {failed} failed")
    log(f"collection '{COLLECTION}': {col.count()} total chunks")
    return 0


def cmd_status():
    """Show indexer status."""
    col = get_collection()
    state = load_state()
    count = col.count()
    file_count = len(state.get("files", {}))

    print(f"Collection: {COLLECTION}")
    print(f"Files indexed: {file_count}")
    print(f"Total chunks: {count}")
    print(f"Embedding model: {state.get('model', 'unknown')}")

    # Show folder breakdown
    if count > 0:
        try:
            all_meta = col.get(include=["metadatas"])
            folders = {}
            for m in all_meta["metadatas"]:
                folder = m.get("folder", "unknown")
                folders[folder] = folders.get(folder, 0) + 1
            print("\nBy folder:")
            for folder, cnt in sorted(folders.items(), key=lambda x: -x[1])[:15]:
                print(f"  {folder}: {cnt} chunks")
        except Exception:
            pass


def cmd_query(query_text: str, n: int = 8):
    """Semantic search over the second-brain collection."""
    col = get_collection()
    if col.count() == 0:
        log("collection empty — run --index first")
        return 1

    client = get_client()
    vec = safe_embed(client, query_text)
    if vec is None:
        log("embedding failed")
        return 1

    results = col.query(query_embeddings=[vec], n_results=n)
    print(f'\nquery: "{query_text}" — top {n} results:\n')

    for i, (doc, meta, dist) in enumerate(
        zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            strict=True,
        )
    ):
        score = 1 - dist  # cosine distance → similarity
        source = meta.get("source_file", "?")
        section = meta.get("section", "?")
        preview = doc[:120].replace("\n", " ")
        print(f"  [{i + 1}] score={score:.3f} | {source} § {section}")
        print(f"      {preview}...")
        print()

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Second-Brain prose indexer")
    parser.add_argument("--index", action="store_true", help="incremental index")
    parser.add_argument("--reindex", action="store_true", help="wipe + full reindex")
    parser.add_argument("--status", action="store_true", help="show stats")
    parser.add_argument("--query", type=str, help="semantic search query")
    parser.add_argument("-n", type=int, default=8, help="number of results")
    args = parser.parse_args()

    if args.reindex:
        return cmd_index(reindex=True)
    if args.index:
        return cmd_index(reindex=False)
    if args.status:
        cmd_status()
        return 0
    if args.query:
        return cmd_query(args.query, args.n)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
