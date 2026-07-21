#!/usr/bin/env python3
"""Rebuild the second-brain Chroma collection from vault markdown files."""

import os
import re
import shutil
from pathlib import Path

import chromadb
from chromadb.config import Settings

import sync as source


def parse_frontmatter(text):
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    return {
        line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
        for line in match.group(1).splitlines()
        if ":" in line
    }


def chunks(text, size=1500, step=1200):
    return [text[i:i + size] for i in range(0, len(text), step) if text[i:i + size].strip()]


def main():
    if os.path.isdir(source.CHROMA_DIR):
        shutil.rmtree(source.CHROMA_DIR)
    Path(source.CHROMA_DIR).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(source.CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False, allow_reset=True),
    )
    collection = client.get_or_create_collection(name="second_brain")
    files = total = 0

    for root, _, names in os.walk(source.VAULT):
        if any(part in {".git", ".obsidian", "hindsight", "memory-facts"} for part in Path(root).parts):
            continue
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            path = Path(root) / name
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            metadata = parse_frontmatter(text)
            body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
            pieces = chunks(body)
            embeddings = source.embed(pieces)
            ids, docs, vectors, metas = [], [], [], []
            title = metadata.get("title", path.stem)
            origin = metadata.get("source", str(path.parent.relative_to(source.VAULT)))
            for index, (piece, vector) in enumerate(zip(pieces, embeddings)):
                if vector is None:
                    continue
                ids.append(f"{origin}:{title}#{index}")
                docs.append(piece)
                vectors.append(vector)
                metas.append({"source": origin, "title": title, "chunk": index})
            if ids:
                collection.upsert(ids=ids, documents=docs, embeddings=vectors, metadatas=metas)
                total += len(ids)
            files += 1

    print(f"[rebuild] DONE: {files} files, {total} chunks")


if __name__ == "__main__":
    main()
