"""Tests for second-brain/scripts/brain_indexer.py.

Focuses on pure functions (frontmatter parsing, chunking, file ops, state).
Heavy ChromaDB/TEI dependencies are mocked or isolated.
"""

import os
import sys

import pytest

# -- helpers ----------------------------------------------------------------


def _load_module(load_script, monkeypatch, tmp_path):
    """Load brain_indexer with patched paths pointing into tmp_path."""
    # Redirect environment paths into tmp_path so we don't touch home dirs
    monkeypatch.setenv("BRAIN_ROOT", str(tmp_path / "brain"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("TEI_EMBED_URL", "http://localhost:0/embeddings")

    # Mock path_utils.resolve_path to be a no-op (just returns the input)
    import types

    fake_path_utils = types.ModuleType("path_utils")
    fake_path_utils.resolve_path = lambda p: os.path.expanduser(p)
    monkeypatch.setitem(__import__("sys").modules, "path_utils", fake_path_utils)

    module = load_script("second-brain/scripts/brain_indexer.py")
    return module


# -- parse_frontmatter tests ------------------------------------------------


def test_parse_frontmatter_empty(load_script, monkeypatch, tmp_path):
    """parse_frontmatter returns empty fm and original text for plain markdown."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "# Hello\n\nThis is content."
    fm, body = module.parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_basic(load_script, monkeypatch, tmp_path):
    """parse_frontmatter extracts YAML frontmatter correctly."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "---\ntitle: My Title\ndate: 2024-01-01\ntags: [dev, ai]\n---\n\n# Content\nBody text."
    fm, body = module.parse_frontmatter(text)
    assert fm.get("title") == "My Title"
    assert fm.get("date") == "2024-01-01"
    assert "Content" in body
    assert "Body text." in body


def test_parse_frontmatter_no_closing(load_script, monkeypatch, tmp_path):
    """parse_frontmatter treats text starting with --- but no closing --- as not frontmatter."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "---\nnot closed\n\nBody"
    fm, body = module.parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_empty_body(load_script, monkeypatch, tmp_path):
    """parse_frontmatter handles frontmatter with empty body."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "---\ntitle: Empty\n---"
    fm, body = module.parse_frontmatter(text)
    assert fm.get("title") == "Empty"
    assert body.strip() == ""


# -- _split_block tests -----------------------------------------------------


def test_split_block_small(load_script, monkeypatch, tmp_path):
    """_split_block returns a single chunk for short text."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    result = module._split_block("Hello world", "section-1")
    assert len(result) == 1
    assert result[0]["text"] == "Hello world"
    assert result[0]["section"] == "section-1"


def test_split_block_large_paragraph(load_script, monkeypatch, tmp_path):
    """_split_block hard-splits a single paragraph that exceeds MAX_CHUNK_CHARS."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    # Create text far exceeding MAX_CHUNK_CHARS (default 1500)
    long_para = "word " * 2000  # ~10000 chars
    result = module._split_block(long_para.strip(), "big-paragraph")
    assert len(result) >= 2
    assert all(chunk["section"] == "big-paragraph" for chunk in result)
    # Each chunk should be at most MAX_CHUNK_CHARS
    for chunk in result:
        assert len(chunk["text"]) <= 3000  # HARD_CHUNK_CAP


def test_split_block_multiple_paragraphs(load_script, monkeypatch, tmp_path):
    """_split_block splits on paragraph boundaries."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    paras = "\n\n".join([f"Para {i} with some content." for i in range(10)])
    result = module._split_block(paras, "multi-para")
    assert len(result) >= 1
    assert all(chunk["section"] == "multi-para" for chunk in result)


# -- chunk_markdown tests ---------------------------------------------------


def test_chunk_markdown_empty(load_script, monkeypatch, tmp_path):
    """chunk_markdown returns [] for empty/whitespace-only text."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    assert module.chunk_markdown("", "test.md") == []
    assert module.chunk_markdown("   \n\n  ", "test.md") == []


def test_chunk_markdown_no_headers(load_script, monkeypatch, tmp_path):
    """chunk_markdown returns one chunk for text with no headers."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "Just a simple paragraph without headers."
    result = module.chunk_markdown(text, "simple.md")
    assert len(result) == 1
    assert result[0]["section"] == "simple"  # stem of filename
    assert result[0]["frontmatter"] == {}


def test_chunk_markdown_with_headers(load_script, monkeypatch, tmp_path):
    """chunk_markdown splits on ## and ### headers."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "## Section One\n\nContent for section one.\n\n### Subsection\n\nSub content.\n\n## Section Two\n\nContent for section two."
    result = module.chunk_markdown(text, "test.md")
    assert len(result) >= 2
    sections = [c["section"] for c in result]
    assert "Section One" in sections
    assert "Section Two" in sections


def test_chunk_markdown_frontmatter(load_script, monkeypatch, tmp_path):
    """chunk_markdown attaches frontmatter to each chunk."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "---\ntitle: Test Doc\n---\n\n## Content\n\nBody."
    result = module.chunk_markdown(text, "front.md")
    assert len(result) >= 1
    for chunk in result:
        assert chunk["frontmatter"].get("title") == "Test Doc"


def test_chunk_markdown_large_block(load_script, monkeypatch, tmp_path):
    """chunk_markdown chunks large sections without headers."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "word " * 2000
    result = module.chunk_markdown(text.strip(), "large.md")
    assert len(result) >= 2


# -- discover_files tests ---------------------------------------------------


def test_discover_files_finds_md(load_script, monkeypatch, tmp_path):
    """discover_files finds .md files recursively."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    (brain_root / "docs").mkdir(parents=True)
    (brain_root / "docs" / "file1.md").write_text("hello", encoding="utf-8")
    (brain_root / "notes.md").write_text("world", encoding="utf-8")
    (brain_root / "readme.txt").write_text("skip", encoding="utf-8")  # not .md

    files = module.discover_files(brain_root)
    assert len(files) == 2
    assert any(f.name == "file1.md" for f in files)
    assert any(f.name == "notes.md" for f in files)


def test_discover_files_skips_hidden(load_script, monkeypatch, tmp_path):
    """discover_files skips files in hidden directories."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    (brain_root / ".hidden" / "secret.md").parents[0].mkdir(parents=True)
    (brain_root / ".hidden" / "secret.md").write_text("shh", encoding="utf-8")
    (brain_root / "visible.md").write_text("hello", encoding="utf-8")

    files = module.discover_files(brain_root)
    assert len(files) == 1
    assert files[0].name == "visible.md"


def test_discover_files_skips_large(load_script, monkeypatch, tmp_path):
    """discover_files skips files larger than MAX_FILE_BYTES."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    brain_root.mkdir(parents=True)
    big = brain_root / "big.md"
    # Write content larger than MAX_FILE_BYTES (default 200000)
    big.write_text("x" * 200_001, encoding="utf-8")
    small = brain_root / "small.md"
    small.write_text("small", encoding="utf-8")

    files = module.discover_files(brain_root)
    assert len(files) == 1
    assert files[0].name == "small.md"


# -- file_hash tests --------------------------------------------------------


def test_file_hash_consistent(load_script, monkeypatch, tmp_path):
    """file_hash returns consistent SHA-256 for the same content."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    f = tmp_path / "data.md"
    f.write_text("consistent content", encoding="utf-8")
    h1 = module.file_hash(f)
    h2 = module.file_hash(f)
    assert h1 == h2


def test_file_hash_different(load_script, monkeypatch, tmp_path):
    """file_hash returns different hashes for different content."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    f1.write_text("content A", encoding="utf-8")
    f2.write_text("content B", encoding="utf-8")
    assert module.file_hash(f1) != module.file_hash(f2)


# -- load_state / save_state tests ------------------------------------------


def test_load_state_missing(load_script, monkeypatch, tmp_path):
    """load_state returns default dict when state file doesn't exist."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    # STATE_FILE path should point to tmp_path/chroma/brain_state.json
    state = module.load_state()
    assert state == {"files": {}, "model": module.MODEL}


def test_save_and_load_state(load_script, monkeypatch, tmp_path):
    """save_state persists state, load_state retrieves it."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    state = {"files": {"test.md": "abc123"}, "model": "test-model"}
    module.save_state(state)
    assert module.STATE_FILE.exists()
    loaded = module.load_state()
    assert loaded["files"]["test.md"] == "abc123"


# -- get_client tests -------------------------------------------------------


def test_get_client_returns_embedded_object(load_script, monkeypatch, tmp_path):
    """get_client returns an object with an .embed() method."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    client = module.get_client()
    assert hasattr(client, "embed")
    assert callable(client.embed)


# -- safe_embed tests -------------------------------------------------------


def test_safe_embed_success(load_script, monkeypatch, tmp_path):
    """safe_embed returns a vector on success."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(success=True)
    result = module.safe_embed(mock_client, "hello world")
    assert result == [0.1, 0.2, 0.3]


def test_safe_embed_retry_then_succeed(load_script, monkeypatch, tmp_path):
    """safe_embed retries on transient errors."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(fail_n_times=1, success=True)
    result = module.safe_embed(mock_client, "hello")
    assert result == [0.1, 0.2, 0.3]


def test_safe_embed_context_length(load_script, monkeypatch, tmp_path):
    """safe_embed returns None on context-length errors (no retry)."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(context_length_error=True)
    result = module.safe_embed(mock_client, "hello")
    assert result is None


def test_safe_embed_all_fail(load_script, monkeypatch, tmp_path):
    """safe_embed returns None when all attempts fail."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(success=False)
    result = module.safe_embed(mock_client, "hello")
    assert result is None


def test_safe_embed_truncates_long_input(load_script, monkeypatch, tmp_path):
    """safe_embed truncates input longer than 2000 chars."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    long_text = "x" * 5000
    mock_client = FakeEmbedClient(success=True)
    result = module.safe_embed(mock_client, long_text)
    assert result is not None


# -- safe_embed_batch tests -------------------------------------------------


def test_safe_embed_batch_success(load_script, monkeypatch, tmp_path):
    """safe_embed_batch returns vectors for all texts."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(success=True)
    result = module.safe_embed_batch(mock_client, ["a", "b", "c"])
    assert len(result) == 3
    assert all(v == [0.1, 0.2, 0.3] for v in result)


def test_safe_embed_batch_context_length_fallback(load_script, monkeypatch, tmp_path):
    """safe_embed_batch falls back to individual embed on context-length errors."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(fail_with_context=True)
    result = module.safe_embed_batch(mock_client, ["a", "b"])
    assert len(result) == 2
    # Falls back to per-text embedding, which succeeds


def test_safe_embed_batch_all_fail(load_script, monkeypatch, tmp_path):
    """safe_embed_batch returns [None, ...] when all retries fail."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    mock_client = FakeEmbedClient(success=False)
    result = module.safe_embed_batch(mock_client, ["a", "b"])
    assert result == [None, None]


# -- discover_files edge cases ----------------------------------------------


def test_split_block_paragraph_accumulation(load_script, monkeypatch, tmp_path):
    """_split_block accumulates small paragraphs, flushing when limit exceeded."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    # Use a low MAX_CHUNK_CHARS to force paragraph accumulation boundaries
    monkeypatch.setattr(module, "MAX_CHUNK_CHARS", 50)
    monkeypatch.setattr(module, "CHUNK_OVERLAP", 10)

    # Paragraphs that fit in one chunk will accumulate; the 3rd one tips over
    result = module._split_block(
        "short para one.\n\nshort para two.\n\nthis para tips over the fifty char boundary easily",
        "acc",
    )
    assert len(result) >= 2
    assert all(c["section"] == "acc" for c in result)


def test_split_block_single_hard_split_with_preceding(load_script, monkeypatch, tmp_path):
    """_split_block flushes accumulated paragraphs when a huge paragraph is encountered."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "MAX_CHUNK_CHARS", 100)
    text = "small preamble.\n\n" + "hugeword " * 200 + "\n\ntrailer."
    result = module._split_block(text, "mixed")
    assert len(result) >= 2
    # preamble should be in an earlier chunk
    assert any("preamble" in c["text"] for c in result)


def test_discover_files_skips_on_oserror(load_script, monkeypatch, tmp_path):
    """discover_files gracefully skips files that raise OSError."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    brain_root.mkdir(parents=True)
    good = brain_root / "good.md"
    good.write_text("ok", encoding="utf-8")

    # Create a dangling symlink that will raise OSError on stat
    bad = brain_root / "bad.md"
    try:
        bad.symlink_to(tmp_path / "nonexistent")
    except OSError:
        pytest.skip("platform does not support symlinks")

    files = module.discover_files(brain_root)
    assert any(f.name == "good.md" for f in files)
    assert not any(f.name == "bad.md" for f in files)


def test_get_client_embed_error(load_script, monkeypatch, tmp_path):
    """The embed method of the TEI client handles errors gracefully."""
    monkeypatch.setenv("TEI_EMBED_URL", "http://127.0.0.1:1/embeddings")
    module = _load_module(load_script, monkeypatch, tmp_path)
    client = module.get_client()
    import urllib.error

    with pytest.raises((urllib.error.URLError, ConnectionError, OSError, Exception)):
        client.embed(module.MODEL, "test")


def test_discover_files_skips_node_modules(load_script, monkeypatch, tmp_path):
    """discover_files skips node_modules directories."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    (brain_root / "node_modules" / "lib.md").parents[0].mkdir(parents=True)
    (brain_root / "node_modules" / "lib.md").write_text("dep", encoding="utf-8")
    (brain_root / "real.md").write_text("content", encoding="utf-8")

    files = module.discover_files(brain_root)
    assert len(files) == 1
    assert files[0].name == "real.md"


# -- main() CLI tests -------------------------------------------------------


def test_main_help(load_script, monkeypatch, tmp_path, capsys):
    """main() prints help and returns 1 with no args."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    # Mock sub-commands to avoid heavy dependencies
    monkeypatch.setattr(module, "cmd_index", lambda reindex=False: 0)
    monkeypatch.setattr(module, "cmd_status", lambda: None)
    monkeypatch.setattr(module, "cmd_query", lambda q, n=8: 0)
    monkeypatch.setattr(sys, "argv", ["brain_indexer.py"])

    result = module.main()
    assert result == 1


def test_main_index(load_script, monkeypatch, tmp_path):
    """main() calls cmd_index(reindex=False) for --index."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(module, "cmd_index", lambda reindex=False: calls.append(("index", reindex)))
    monkeypatch.setattr(sys, "argv", ["brain_indexer.py", "--index"])
    result = module.main()
    assert result is None or result == 0
    assert ("index", False) in calls


def test_main_reindex(load_script, monkeypatch, tmp_path):
    """main() calls cmd_index(reindex=True) for --reindex."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        module, "cmd_index", lambda reindex=False: calls.append(("reindex", reindex))
    )
    monkeypatch.setattr(sys, "argv", ["brain_indexer.py", "--reindex"])
    module.main()
    assert ("reindex", True) in calls


def test_main_status(load_script, monkeypatch, tmp_path):
    """main() calls cmd_status for --status."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(module, "cmd_status", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["brain_indexer.py", "--status"])
    module.main()
    assert called == [True]


def test_main_query(load_script, monkeypatch, tmp_path):
    """main() calls cmd_query for --query."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    query_args = []
    monkeypatch.setattr(module, "cmd_query", lambda q, n=8: query_args.append((q, n)))
    monkeypatch.setattr(sys, "argv", ["brain_indexer.py", "--query", "test search", "-n", "5"])
    module.main()
    assert ("test search", 5) in query_args


# -- log test ----------------------------------------------------------------


def test_log(load_script, monkeypatch, tmp_path, capsys):
    """log writes to stdout with prefix."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    module.log("test message")
    out = capsys.readouterr().out
    assert "[brain-indexer] test message" in out


# -- helper: FakeEmbedClient ------------------------------------------------


class FakeEmbedClient:
    """A fake TEI client that returns predictable results or failures."""

    def __init__(
        self, success=True, fail_n_times=0, context_length_error=False, fail_with_context=False
    ):
        self.success = success
        self.fail_n_times = fail_n_times
        self.call_count = 0
        self.context_length_error = context_length_error
        self.fail_with_context = fail_with_context

    def embed(self, model, input):
        self.call_count += 1
        if self.call_count <= self.fail_n_times:
            raise ConnectionError("transient failure")
        if self.context_length_error:
            raise ValueError("exceeds the context length")
        if self.fail_with_context and self.call_count == 1:
            raise ValueError("exceeds the context length")
        if not self.success:
            raise RuntimeError("API error")

        if isinstance(input, str):
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        return {"embeddings": [[0.1, 0.2, 0.3] for _ in input]}


# -- cmd_index tests ------------------------------------------------------


def test_cmd_index_incremental(load_script, monkeypatch, tmp_path):
    """cmd_index runs incremental index with mocked ChromaDB and TEI."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    # Mock ChromaDB collection
    mock_collection = FakeChromaCollection()

    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=True))
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "save_state", lambda state: None)
    monkeypatch.setattr(module, "discover_files", lambda root: [])
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_index(reindex=False)
    assert result == 0


def test_cmd_index_reindex(load_script, monkeypatch, tmp_path):
    """cmd_index with reindex=True wipes the collection first."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection.delete_count = 0
    original_delete = mock_collection.delete

    def tracking_delete(**kwargs):
        mock_collection.delete_count += 1
        return original_delete(**kwargs)

    mock_collection.delete = tracking_delete

    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=True))
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "save_state", lambda state: None)
    monkeypatch.setattr(module, "discover_files", lambda root: [])
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_index(reindex=True)
    assert result == 0
    assert mock_collection.delete_count > 0


def test_cmd_index_tei_unreachable(load_script, monkeypatch, tmp_path):
    """cmd_index returns 1 when TEI is not reachable."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=False))
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "save_state", lambda state: None)
    monkeypatch.setattr(module, "discover_files", lambda root: [])
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_index(reindex=False)
    assert result == 1


def test_cmd_index_with_files(load_script, monkeypatch, tmp_path):
    """cmd_index processes markdown files and upserts chunks."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    brain_root = tmp_path / "brain"
    brain_root.mkdir(parents=True)
    doc = brain_root / "doc.md"
    doc.write_text("# Hello\n\nWorld content here.", encoding="utf-8")

    mock_collection = FakeChromaCollection()
    mock_collection.upsert_count = 0
    original_upsert = mock_collection.upsert

    def tracking_upsert(**kwargs):
        mock_collection.upsert_count += 1
        return original_upsert(**kwargs)

    mock_collection.upsert = tracking_upsert

    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=True))
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "save_state", lambda state: None)
    monkeypatch.setattr(module, "discover_files", lambda root: [doc])
    monkeypatch.setattr(module, "file_hash", lambda p: "abc123")
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_index(reindex=False)
    assert result == 0


def test_cmd_status(load_script, monkeypatch, tmp_path):
    """cmd_status prints collection stats."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection._count = 5
    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(
        module, "load_state", lambda: {"files": {"doc.md": "hash1"}, "model": module.MODEL}
    )
    monkeypatch.setattr(module, "log", lambda msg: None)

    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        module.cmd_status()
    output = f.getvalue()
    assert "second-brain" in output
    assert "Files indexed: 1" in output
    assert "Total chunks: 5" in output


def test_cmd_status_empty_collection(load_script, monkeypatch, tmp_path):
    """cmd_status handles empty collection gracefully."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection._count = 0
    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "log", lambda msg: None)

    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        module.cmd_status()
    output = f.getvalue()
    assert "second-brain" in output
    assert "Files indexed: 0" in output


def test_cmd_query(load_script, monkeypatch, tmp_path):
    """cmd_query performs semantic search and prints results."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection._count = 3
    mock_collection._query_result = {
        "documents": [["Hello world", "Goodbye world"]],
        "metadatas": [
            [
                {
                    "source_file": "doc.md",
                    "section": "Intro",
                    "folder": ".",
                    "chunk_index": 0,
                    "total_chunks": 2,
                },
                {
                    "source_file": "doc.md",
                    "section": "Outro",
                    "folder": ".",
                    "chunk_index": 1,
                    "total_chunks": 2,
                },
            ],
        ],
        "distances": [[0.1, 0.3]],
    }

    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=True))
    monkeypatch.setattr(module, "load_state", lambda: {"files": {}, "model": module.MODEL})
    monkeypatch.setattr(module, "log", lambda msg: None)

    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        result = module.cmd_query("hello", n=2)
    output = f.getvalue()
    assert result == 0
    assert "query:" in output
    assert "score=" in output


def test_cmd_query_empty_collection(load_script, monkeypatch, tmp_path):
    """cmd_query returns 1 when collection is empty."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection._count = 0
    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_query("hello", n=2)
    assert result == 1


def test_cmd_query_embed_fail(load_script, monkeypatch, tmp_path):
    """cmd_query returns 1 when embedding fails."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_collection._count = 3
    monkeypatch.setattr(module, "get_collection", lambda: mock_collection)
    monkeypatch.setattr(module, "get_client", lambda: FakeEmbedClient(success=False))
    monkeypatch.setattr(module, "log", lambda msg: None)

    result = module.cmd_query("hello", n=2)
    assert result == 1


# -- get_collection tests --------------------------------------------------


def test_get_collection_returns_collection(load_script, monkeypatch, tmp_path):
    """get_collection returns a ChromaDB collection with correct metadata."""
    module = _load_module(load_script, monkeypatch, tmp_path)

    mock_collection = FakeChromaCollection()
    mock_client_instance = FakeChromaClient(mock_collection)

    import chromadb

    monkeypatch.setattr(chromadb, "PersistentClient", lambda **kwargs: mock_client_instance)

    col = module.get_collection()
    assert col is mock_collection


# -- chunk_markdown edge cases ---------------------------------------------


def test_chunk_markdown_single_header(load_script, monkeypatch, tmp_path):
    """chunk_markdown handles text with only a header and no body."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "## Just a Header"
    result = module.chunk_markdown(text, "header-only.md")
    assert result == []


def test_chunk_markdown_multiple_headers_same_content(load_script, monkeypatch, tmp_path):
    """chunk_markdown correctly assigns sections to multiple headers."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "## Alpha\n\nAlpha body.\n\n## Beta\n\nBeta body."
    result = module.chunk_markdown(text, "multi.md")
    sections = [c["section"] for c in result]
    assert "Alpha" in sections
    assert "Beta" in sections


def test_chunk_markdown_deep_headers(load_script, monkeypatch, tmp_path):
    """chunk_markdown handles ### (level 3) headers."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "## Section\n\nContent.\n\n### Deep Subsection\n\nDeep content."
    result = module.chunk_markdown(text, "deep.md")
    sections = [c["section"] for c in result]
    assert "Section" in sections
    assert "Deep Subsection" in sections


def test_chunk_markdown_frontmatter_only(load_script, monkeypatch, tmp_path):
    """chunk_markdown returns empty list when frontmatter has no body content."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    text = "---\ntitle: Only Frontmatter\n---"
    result = module.chunk_markdown(text, "fm-only.md")
    assert result == []


# -- discover_files edge cases ---------------------------------------------


def test_discover_files_empty_dir(load_script, monkeypatch, tmp_path):
    """discover_files returns empty list for directory with no .md files."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    brain_root.mkdir(parents=True)
    (brain_root / "readme.txt").write_text("not markdown", encoding="utf-8")
    files = module.discover_files(brain_root)
    assert files == []


def test_discover_files_zero_size_skipped(load_script, monkeypatch, tmp_path):
    """discover_files skips zero-byte files."""
    module = _load_module(load_script, monkeypatch, tmp_path)
    brain_root = tmp_path / "brain"
    brain_root.mkdir(parents=True)
    empty = brain_root / "empty.md"
    empty.write_text("", encoding="utf-8")
    (brain_root / "real.md").write_text("content", encoding="utf-8")
    files = module.discover_files(brain_root)
    assert len(files) == 1
    assert files[0].name == "real.md"


# -- helper classes for mocking ChromaDB -----------------------------------


class FakeChromaCollection:
    """Fake ChromaDB collection for testing."""

    def __init__(self):
        self._count = 0
        self._stored = {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
        self.delete_count = 0
        self._query_result = None

    def count(self):
        return self._count

    def delete(self, **kwargs):
        self.delete_count += 1

    def upsert(self, **kwargs):
        ids = kwargs.get("ids", [])
        docs = kwargs.get("documents", [])
        metas = kwargs.get("metadatas", [])
        embs = kwargs.get("embeddings", [])
        self._stored["ids"].extend(ids)
        self._stored["documents"].extend(docs)
        self._stored["metadatas"].extend(metas)
        self._stored["embeddings"].extend(embs)
        self._count = len(self._stored["ids"])

    def get(self, **kwargs):
        where = kwargs.get("where", {})
        ids = self._stored["ids"]
        docs = self._stored["documents"]
        metas = self._stored["metadatas"]
        if where:
            source_file = where.get("source_file")
            if source_file:
                filtered = [
                    (i, d, m)
                    for i, d, m in zip(ids, docs, metas, strict=True)
                    if m.get("source_file") == source_file
                ]
                if filtered:
                    ids, docs, metas = [list(x) for x in zip(*filtered, strict=True)]
                else:
                    return {"ids": [], "documents": [], "metadatas": []}
        return {"ids": ids, "documents": docs, "metadatas": metas}

    def query(self, **kwargs):
        if self._query_result is not None:
            return self._query_result
        n_results = kwargs.get("n_results", 1)
        return {
            "documents": [[d] for d in self._stored["documents"][:n_results]],
            "metadatas": [[m] for m in self._stored["metadatas"][:n_results]],
            "distances": [[0.1] for _ in range(min(n_results, len(self._stored["ids"])))],
        }


class FakeChromaClient:
    """Fake ChromaDB persistent client."""

    def __init__(self, collection):
        self._collection = collection

    def get_or_create_collection(self, name, **kwargs):
        return self._collection
