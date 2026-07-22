import io
import json
import os
from pathlib import Path
from types import SimpleNamespace


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Collection:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def upsert(self, **kwargs):
        if self.fail:
            raise RuntimeError()
        self.calls.append(kwargs)


def module(load_script):
    return load_script("second-brain/scripts/sync.py")


def test_write_vault_file_and_null_collection(load_script, tmp_path):
    sync = module(load_script)
    path = tmp_path / "nested" / "note.md"
    sync.write_vault_file(str(path), "héllo")
    assert path.read_text(encoding="utf-8") == "héllo"
    null = sync._NullCollection()
    assert null.upsert() is None and null.delete() is None
    assert null.count() == 0 and null.get() == {}


def test_get_col_success_and_failure(load_script, monkeypatch):
    sync = module(load_script)
    collection = object()
    client = SimpleNamespace(get_or_create_collection=lambda name: collection)
    monkeypatch.setattr("chromadb.PersistentClient", lambda **kwargs: client)
    assert sync.get_col() is collection
    monkeypatch.setattr("chromadb.PersistentClient", lambda **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert isinstance(sync.get_col(), sync._NullCollection)


def test_embed_success_retry_and_failure(load_script, monkeypatch):
    sync = module(load_script)
    payload = json.dumps({"data": [{"embedding": [1]}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    assert sync.embed(["text"]) == [[1]]
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise OSError()

    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert sync.embed(["text"]) == [None]
    assert len(calls) == 3


def test_ensure_tei_paths(load_script, monkeypatch):
    sync = module(load_script)
    good = json.dumps({"data": [{"embedding": [0] * 1024}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(good))
    assert sync._ensure_tei()
    bad = json.dumps({"data": [{"embedding": [0]}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(bad))
    assert not sync._ensure_tei()


def test_embed_and_store_writes_and_indexes(load_script, tmp_path, monkeypatch):
    sync = module(load_script)
    monkeypatch.setattr(sync, "embed", lambda chunks: [[1.0]] * len(chunks))
    col = Collection()
    sync.embed_and_store(col, "docs", "Title", "x" * 2000,
                         vault_md="markdown", vault_dir=str(tmp_path))
    assert (tmp_path / "Title.md").read_text(encoding="utf-8") == "markdown"
    assert len(col.calls[0]["ids"]) == 2
    sync.embed_and_store(Collection(fail=True), "docs", "Other", "body")
    sync.embed_and_store(col, "docs", "Empty", "   ")


def test_gh_helpers(load_script, monkeypatch):
    sync = module(load_script)
    result = SimpleNamespace(returncode=0, stdout="Rust, Python\n")
    monkeypatch.setattr(sync.subprocess, "run", lambda *a, **k: result)
    assert sync._gh_api("path") == result.stdout
    assert sync._gh_languages("owner", "repo") == "Rust, Python"
    result.returncode = 1
    assert sync._gh_api("path") is None


def test_extract_pdf(load_script, monkeypatch):
    sync = module(load_script)
    page = SimpleNamespace(extract_text=lambda: "text")
    class Pdf:
        pages = [page]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    pdf = Pdf()
    monkeypatch.setattr("pdfplumber.open", lambda path: pdf)
    assert sync.extract_pdf("file.pdf") == "text"
    monkeypatch.setattr("pdfplumber.open", lambda path: (_ for _ in ()).throw(OSError()))
    assert "extraction failed" in sync.extract_pdf("file.pdf")


def test_sync_hindsight_success_and_failure(load_script, tmp_path, monkeypatch):
    sync = module(load_script)
    sync.DIRS["hindsight"] = str(tmp_path)
    payload = json.dumps({"memories": [{"id": "one", "content": "observation"}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    sync.sync_hindsight(Collection())
    assert (tmp_path / "one.md").exists()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    sync.sync_hindsight(Collection())
    assert (tmp_path / "_STATUS.md").exists()


def test_pause_resume_hindsight(load_script, monkeypatch):
    sync = module(load_script)
    calls = []
    monkeypatch.setattr(sync.subprocess, "run", lambda args, **kwargs: calls.append(args))
    sync._pause_hindsight_daemon()
    sync._resume_hindsight_daemon()
    assert calls[0][:2] == ["launchctl", "unload"]
    assert calls[-1][:2] == ["launchctl", "load"]


def test_ensure_symlinks_default_and_profile(load_script, tmp_path, monkeypatch):
    sync = module(load_script)
    home = tmp_path / "home"
    hermes = home / ".hermes"
    for name in ("MEMORY.md", "USER.md", "SOUL.md"):
        path = hermes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
    (hermes / "skills").mkdir()
    sync.VAULT = str(tmp_path / "brain")
    original = sync.os.path.expanduser
    monkeypatch.setattr(sync.os.path, "expanduser", lambda path: path.replace("~", str(home), 1) if path.startswith("~") else original(path))
    sync._ensure_symlinks()
    destination = tmp_path / "brain" / "System" / "Hermes"
    assert (destination / "MEMORY.md").is_symlink()
    profile = hermes / "profiles" / "test"
    profile.mkdir(parents=True)
    (profile / "MEMORY.md").write_text("profile", encoding="utf-8")
    monkeypatch.setenv("HERMES_PROFILE", "test")
    sync._ensure_symlinks()
    assert os.readlink(destination / "MEMORY.md") == str(profile / "MEMORY.md")


def test_sync_github_success_skip_and_no_repos(load_script, tmp_path, monkeypatch):
    load_script("second-brain/scripts/google_sync.py", name="google_sync")
    sync = module(load_script)
    sync.VAULT = str(tmp_path / "brain")
    encoded = __import__("base64").b64encode(b"README body").decode()

    def api(path, jq=None):
        if path.startswith("user/repos"):
            return "owner/repo"
        if path.endswith("/readme"):
            return encoded
        if path.endswith("/languages"):
            return "Rust"
        return None

    stored = []
    monkeypatch.setattr(sync, "_gh_api", api)
    monkeypatch.setattr(sync, "embed_and_store", lambda *a, **k: stored.append((a, k)))
    sync.sync_github(object())
    assert len(stored) == 1
    monkeypatch.setattr(sync, "_gh_api", lambda *a, **k: None)
    sync.sync_github(object())


def test_main_source_all_unknown_and_cleanup(load_script, tmp_path, monkeypatch):
    sync = module(load_script)
    sync.VAULT = str(tmp_path / "brain")
    sync.DIRS = {"one": str(tmp_path / "brain" / "one")}
    calls = []
    monkeypatch.setattr(sync, "_ensure_symlinks", lambda: calls.append("links"))
    monkeypatch.setattr(sync, "_ensure_tei", lambda: calls.append("tei"))
    monkeypatch.setattr(sync, "_pause_hindsight_daemon", lambda: calls.append("pause"))
    monkeypatch.setattr(sync, "_resume_hindsight_daemon", lambda: calls.append("resume"))
    monkeypatch.setattr(sync, "get_col", lambda: object())
    for name in ("sync_github", "sync_apple_notes", "sync_documents", "sync_google_drive", "sync_hindsight", "_sync_memory_facts"):
        monkeypatch.setattr(sync, name, lambda col, name=name: calls.append(name))
    monkeypatch.setattr(__import__("sys"), "argv", ["sync", "--source", "github"])
    sync.main()
    assert "sync_github" in calls and calls[-1] == "resume"
    calls.clear()
    monkeypatch.setattr(__import__("sys"), "argv", ["sync"])
    sync.main()
    assert sum(name.startswith("sync_") for name in calls) == 5
    monkeypatch.setattr(__import__("sys"), "argv", ["sync", "--source", "unknown"])
    with __import__("pytest").raises(SystemExit):
        sync.main()


def test_sync_documents_routes_and_skips(load_script, tmp_path, monkeypatch):
    google = load_script("second-brain/scripts/google_sync.py", name="google_sync")
    sync = module(load_script)
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "personal.txt").write_text("ordinary", encoding="utf-8")
    (documents / "business.md").write_text("work business", encoding="utf-8")
    (documents / "binary.docx").write_bytes(b"binary")
    (documents / "skip.exe").write_bytes(b"skip")
    sync.VAULT = str(tmp_path / "brain")
    sync.DIRS["docs"] = str(tmp_path / "brain" / "Personal" / "Documents")
    monkeypatch.setenv("DOCUMENTS_DIR", str(documents))
    calls = []
    monkeypatch.setattr(sync, "embed_and_store", lambda *a, **k: calls.append((a, k)))
    sync.sync_documents(object())
    assert len(calls) == 3
    destinations = {call[1]["vault_dir"] for call in calls}
    assert sync.DIRS["docs"] in destinations
    assert os.path.join(sync.VAULT, sync.WORK_SECTION, "Business") in destinations
