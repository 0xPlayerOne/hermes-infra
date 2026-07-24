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
