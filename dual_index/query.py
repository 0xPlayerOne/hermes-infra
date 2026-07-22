"""Standalone dual-index search across code + second-brain ChromaDB."""

from __future__ import annotations

import argparse
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEXER = os.path.join(REPO_ROOT, "code-index", "indexer.py")
_spec = importlib.util.spec_from_file_location("code_index_indexer", INDEXER)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_client = _mod.get_client
get_chroma = _mod.get_chroma
MODEL = _mod.MODEL


def _search_code(chroma, qemb, n):
    col = chroma.get_collection("code")
    res = col.query(query_embeddings=[qemb], n_results=n)
    return [
        {
            "score": 1 - dist,
            "source": "[code]",
            "repo": meta.get("repo", "?"),
            "path": meta.get("path", "?"),
            "label": meta.get("language", meta.get("chunk_type", "")),
            "preview": (doc or "")[:180].replace("\n", " "),
        }
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
        )
    ]


def _search_sb(chroma, qemb, n):
    col = chroma.get_collection("second-brain")
    res = col.query(query_embeddings=[qemb], n_results=n)
    return [
        {
            "score": 1 - dist,
            "source": "[second-brain]",
            "repo": meta.get("folder", ""),
            "path": meta.get("source_file", "?"),
            "label": meta.get("section", ""),
            "preview": (doc or "")[:180].replace("\n", " "),
        }
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
        )
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="search query")
    ap.add_argument("-n", type=int, default=8, help="number of results")
    ap.add_argument("--source", choices=["code", "second-brain", "both"], default="both")
    args = ap.parse_args()

    chroma = get_chroma()
    client = get_client()
    qemb = client.embed(model=MODEL, input=[args.query])["embeddings"][0]

    if args.source == "code":
        hits = _search_code(chroma, qemb, args.n)
    elif args.source == "second-brain":
        hits = _search_sb(chroma, qemb, args.n)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_search_code, chroma, qemb, args.n)
            f2 = pool.submit(_search_sb, chroma, qemb, args.n)
            hits = sorted(f1.result() + f2.result(), key=lambda h: h["score"], reverse=True)[
                : args.n
            ]

    print(f'\nquery: "{args.query}" — top {len(hits)} results:\n')
    for i, h in enumerate(hits, 1):
        location = f"{h['repo']}/{h['path']} § {h['label']}"
        print(f"  [{i}] {h['score']:.3f} {h['source']} {location}")
        print(f"      {h['preview']}")
        print()


if __name__ == "__main__":
    main()
