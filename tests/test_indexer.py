import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def module(load_script):
    return load_script("code-index/indexer.py")


def test_enforce_model_available(load_script, monkeypatch):
    indexer = module(load_script)
    monkeypatch.setattr(indexer, "_tei_probe_ok", lambda timeout=10: True)
    indexer.enforce_model_available()
    monkeypatch.setattr(indexer, "_tei_probe_ok", lambda timeout=10: False)
    with pytest.raises(SystemExit) as error:
        indexer.enforce_model_available()
    assert error.value.code == 2


def test_safe_embed_success_truncates_and_context_failure(load_script, monkeypatch):
    indexer = module(load_script)

    class Client:
        def __init__(self):
            self.input = None

        def embed(self, model, input):
            self.input = input
            return {"embeddings": [[1.0]]}

    client = Client()
    assert indexer.safe_embed(client, "x" * 3000) == [1.0]
    assert len(client.input) == 2000

    class ContextClient:
        def embed(self, **kwargs):
            raise RuntimeError("exceeds the context length")

    assert indexer.safe_embed(ContextClient(), "x") is None


def test_safe_embed_retries_with_fresh_client(load_script, monkeypatch):
    indexer = module(load_script)

    class Broken:
        def embed(self, **kwargs):
            raise TimeoutError()

    class Good:
        def embed(self, **kwargs):
            return {"embeddings": [[2.0]]}

    monkeypatch.setattr(indexer, "get_client", lambda: Good())
    monkeypatch.setattr(indexer.time, "sleep", lambda _: None)
    assert indexer.safe_embed(Broken(), "x") == [2.0]


def test_find_git_repos_prunes_nested_and_hidden(load_script, tmp_path):
    indexer = module(load_script)
    (tmp_path / "one" / ".git").mkdir(parents=True)
    (tmp_path / "one" / "nested" / ".git").mkdir(parents=True)
    (tmp_path / ".cache" / "hidden" / ".git").mkdir(parents=True)
    (tmp_path / "two").mkdir()
    (tmp_path / "two" / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    assert indexer.find_git_repos(tmp_path) == [
        (tmp_path / "one", "one"), (tmp_path / "two", "two")]


def test_file_hash(load_script, tmp_path):
    indexer = module(load_script)
    path = tmp_path / "file"
    path.write_bytes(b"content")
    assert indexer.file_hash(path) == hashlib.sha256(b"content").hexdigest()


def test_chunk_text_empty_overlap_and_minified(load_script, monkeypatch):
    indexer = module(load_script)
    assert indexer.chunk_text("", "file") == []
    monkeypatch.setattr(indexer, "MAX_CHUNK_CHARS", 20)
    monkeypatch.setattr(indexer, "CHUNK_OVERLAP", 5)
    chunks = indexer.chunk_text("line one\nline two\nline three\nline four", "file")
    assert len(chunks) >= 2
    minified = indexer.chunk_text("x" * 50, "file")
    assert all(len(chunk) <= 20 for chunk in minified)


@pytest.mark.parametrize(
    ("filename", "language"),
    [("a.ts", "typescript"), ("a.py", "python"), ("a.rs", "rust"),
     ("a.yaml", "yaml"), ("a.cs", "csharp"), ("README", "other")],
)
def test_lang_for(load_script, filename, language):
    assert module(load_script).lang_for(Path(filename)) == language


def test_state_round_trip(load_script, tmp_path):
    indexer = module(load_script)
    indexer.STATE_FILE = tmp_path / "nested" / "state.json"
    assert indexer.load_state() == {"repos": {}, "model": indexer.MODEL}
    state = {"repos": {"one": {}}, "model": indexer.MODEL}
    indexer.save_state(state)
    assert indexer.load_state() == state


def test_tei_probe(load_script, monkeypatch):
    indexer = module(load_script)
    payload = json.dumps({"data": [{"embedding": [1]}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    assert indexer._tei_probe_ok()
    response = Response(payload)
    response.status = 503
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)
    assert not indexer._tei_probe_ok()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert not indexer._tei_probe_ok()


def test_tei_client_normalizes_inputs(load_script, monkeypatch):
    indexer = module(load_script)
    requests = []

    def open_url(request, timeout):
        requests.append(json.loads(request.data))
        return Response(json.dumps({"data": [{"embedding": [1]}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    client = indexer.get_client()
    assert client.embed("model", "text") == {"embeddings": [[1]]}
    assert requests[0]["input"] == ["text"]


def test_get_chroma_creates_directory(load_script, tmp_path, monkeypatch):
    indexer = module(load_script)
    indexer.CHROMA_DIR = tmp_path / "chroma"
    fake = SimpleNamespace(PersistentClient=lambda path: ("client", path))
    monkeypatch.setitem(__import__("sys").modules, "chromadb", fake)
    assert indexer.get_chroma() == ("client", str(indexer.CHROMA_DIR))
    assert indexer.CHROMA_DIR.is_dir()


def test_restart_tei_success_and_reentrant_guard(load_script, monkeypatch):
    indexer = module(load_script)
    indexer._tei_restart_in_progress = True
    assert not indexer.restart_tei()
    indexer._tei_restart_in_progress = False
    monkeypatch.setattr(indexer.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(indexer.time, "sleep", lambda _: None)
    monkeypatch.setattr(indexer, "_tei_probe_ok", lambda timeout=10: True)
    assert indexer.restart_tei()
    assert not indexer._tei_restart_in_progress


def test_embed_batch_success_and_failure(load_script, monkeypatch):
    indexer = module(load_script)
    monkeypatch.setattr(indexer, "EMBED_BATCH", 2)
    monkeypatch.setattr(indexer, "EMBED_BATCH_DELAY", 0)
    monkeypatch.setattr(indexer, "_embed_with_timeout", lambda client, batch: [[len(x)] for x in batch])
    assert indexer.embed_batch(object(), ["a", "bb", "ccc"]) == [[1], [2], [3]]

    def fail(client, batch):
        raise RuntimeError("failed")

    monkeypatch.setattr(indexer, "_embed_with_timeout", fail)
    assert indexer.embed_batch(object(), ["a"]) == [None]


def test_embed_timeout_and_upsert_helpers(load_script):
    indexer = module(load_script)
    client = SimpleNamespace(embed=lambda **kwargs: {"embeddings": [[1.0]]})
    assert indexer._embed_with_timeout(client, ["text"], timeout=1) == [[1.0]]
    failing = SimpleNamespace(embed=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad")))
    with pytest.raises(RuntimeError):
        indexer._embed_with_timeout(failing, ["text"], timeout=1)

    class Collection:
        def upsert(self, **kwargs):
            self.kwargs = kwargs

    assert indexer.timeout_upsert(Collection(), ["id"], ["doc"], [[1]], [{}], limit=1)
    class Broken:
        def upsert(self, **kwargs):
            raise RuntimeError("bad")
    assert not indexer.timeout_upsert(Broken(), [], [], [], [], limit=1)


def test_cmd_index_full_incremental_and_reindex(load_script, tmp_path, monkeypatch):
    indexer = module(load_script)
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "main.py"
    source.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    indexer.DEV_ROOT = tmp_path
    indexer.CHROMA_DIR = tmp_path / "chroma"
    state = {"repos": {}, "model": indexer.MODEL}
    saved = []

    class Collection:
        pass
    collection = Collection()
    chroma = SimpleNamespace(get_or_create_collection=lambda **kwargs: collection)
    monkeypatch.setattr(indexer, "load_state", lambda: state)
    monkeypatch.setattr(indexer, "save_state", lambda value: saved.append(value.copy()))
    monkeypatch.setattr(indexer, "get_chroma", lambda: chroma)
    monkeypatch.setattr(indexer, "get_client", lambda: object())
    monkeypatch.setattr(indexer, "find_git_repos", lambda root: [(repo, "repo")])
    monkeypatch.setattr(indexer, "embed_batch", lambda client, texts: [[1.0]] * len(texts))
    monkeypatch.setattr(indexer, "timeout_upsert", lambda *args, **kwargs: True)
    indexer.cmd_index()
    assert saved and "main.py" in saved[-1]["repos"]["repo"]["files"]

    state = saved[-1]
    saved.clear()
    indexer.cmd_index()
    assert saved[-1]["repos"]["repo"]["files"]["main.py"] == indexer.file_hash(source)

    indexer.CHROMA_DIR.mkdir()
    (indexer.CHROMA_DIR / "old").write_text("old", encoding="utf-8")
    indexer.cmd_index(reindex=True)
    assert not (indexer.CHROMA_DIR / "old").exists()


def test_cmd_status_and_query(load_script, monkeypatch, capsys):
    indexer = module(load_script)
    collection = SimpleNamespace(
        count=lambda: 3,
        query=lambda **kwargs: {
            "documents": [["document"]],
            "metadatas": [[{"repo": "repo", "path": "main.py", "chunk": 0,
                              "n_chunks": 1, "lang": "python"}]],
            "distances": [[0.1]],
        },
    )
    chroma = SimpleNamespace(get_collection=lambda name: collection)
    monkeypatch.setattr(indexer, "get_chroma", lambda: chroma)
    monkeypatch.setattr(indexer, "load_state", lambda: {
        "model": indexer.MODEL, "repos": {"repo": {"files": {"main.py": "hash"}}}})
    monkeypatch.setattr(indexer, "get_client", lambda: SimpleNamespace(
        embed=lambda **kwargs: {"embeddings": [[1.0]]}))
    indexer.cmd_status()
    indexer.cmd_query("query", repo="repo", n=1)
    output = capsys.readouterr().out
    assert "Total chunks in store: 3" in output
    assert "repo / main.py" in output
